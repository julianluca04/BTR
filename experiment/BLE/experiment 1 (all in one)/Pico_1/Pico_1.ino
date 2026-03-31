

/*
 * Pico_ble_full.ino  —  Raspberry Pi Pico (host)
 * Strategy: full_payload, Module: nRF52840 BLE
 *
 * Identical handshake to Pico_1.ino so test_ble_full.py can reuse
 * the same READY / go / START_IN_<ms> / ACK / SKIP / DONE protocol.
 *
 * Sends to nRF over Serial1 (UART):
 *   "<size>\n"          — payload size as ASCII integer
 *   <size bytes>        — raw payload bytes (repeating digit)
 *   "\n"                — trailing newline (mirrors wifi behaviour)
 * Waits for nRF to reply "OK\n" or "FAIL\n".
 */

#include <Arduino.h>

const int LED_PIN = 25;

const int NUM_PAYLOADS = 18;   // 1B … 131072B  (21 sizes minus 262144, 524288, 1MB)
const int PAYLOAD_SIZES[NUM_PAYLOADS] = {
  1, 2, 4, 8, 16, 32, 64, 128, 256, 512,
  1024, 2048, 4096, 8192, 16384, 32768, 65536,
  131072
};

const int SETTLE_MS      = 1000;
const int START_DELAY_MS = 500;

bool started = false;

void flashLED(int times) {
  for (int i = 0; i < times; i++) {
    digitalWrite(LED_PIN, HIGH);
    delay(80);
    digitalWrite(LED_PIN, LOW);
    delay(80);
  }
}

void waitForAckOrSkip(bool &skipRun) {
  unsigned long t = millis();
  while (millis() - t < 15000) {
    if (Serial.available()) {
      String msg = Serial.readStringUntil('\n');
      msg.trim();
      if (msg == "ACK")  { return; }
      if (msg == "SKIP") { skipRun = true; return; }
    }
    delay(10);
  }
  skipRun = true;
}

void setup() {
  Serial.begin(115200);
  Serial1.begin(115200);
  pinMode(LED_PIN, OUTPUT);
  delay(2000);
}

void loop() {
  if (!started) {
    Serial.println("READY");
    unsigned long t = millis();
    while (millis() - t < 500) {
      if (Serial.available()) {
        String cmd = Serial.readStringUntil('\n');
        cmd.trim();
        if (cmd == "go") {
          Serial.print("START_IN_");
          Serial.println(START_DELAY_MS);
          delay(START_DELAY_MS);
          started = true;
          return;
        }
      }
    }
    return;
  }

  bool skipRun = false;

  for (int i = 0; i < NUM_PAYLOADS; i++) {
    if (skipRun) break;

    int size   = PAYLOAD_SIZES[i];
    char digit = '0' + (i % 10);

    // Tell nRF the size
    Serial1.println(size);
    delay(50);

    // Send payload bytes in 256-byte chunks
    int sent = 0;
    while (sent < size) {
      int chunk = min(256, size - sent);
      for (int j = 0; j < chunk; j++) Serial1.write(digit);
      sent += chunk;
      delay(10);
    }
    Serial1.println();  // trailing newline

    // Wait for nRF reply: "OK" or "FAIL"
    String nrfResp = "";
    unsigned long t = millis();
    while (millis() - t < 60000) {  // generous: large payloads take time over BLE
      if (Serial1.available()) {
        nrfResp = Serial1.readStringUntil('\n');
        nrfResp.trim();
        break;
      }
      delay(10);
    }

    if (nrfResp != "OK") {
      Serial.print("NRF_FAIL ");
      Serial.println(size);
      waitForAckOrSkip(skipRun);
      skipRun = true;
    } else {
      Serial.print("SENT ");
      Serial.print(size);
      Serial.println("B");
      flashLED(1);
      waitForAckOrSkip(skipRun);
    }

    if (!skipRun) delay(SETTLE_MS);
  }

  Serial.println("DONE");
  flashLED(3);
  started = false;
}