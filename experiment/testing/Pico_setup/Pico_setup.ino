#include <Arduino.h>

const int LED_PIN = 25;

const int NUM_PAYLOADS = 21;
const int PAYLOAD_SIZES[NUM_PAYLOADS] = {
  1, 2, 4, 8, 16, 32, 64, 128, 256, 512,
  1024, 2048, 4096, 8192, 16384, 32768, 65536,
  131072, 262144, 524288, 1048576
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
  // Timeout waiting for ACK — treat as skip
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

    // Tell ESP32 payload size
    Serial1.println(size);
    delay(50);

    // Send payload in 256B chunks
    int sent = 0;
    while (sent < size) {
      int chunk = min(256, size - sent);
      for (int j = 0; j < chunk; j++) Serial1.write(digit);
      sent += chunk;
      delay(10);
    }
    Serial1.println();  // trailing newline

    // Wait for ESP32 response over UART (OK or FAIL)
    String esp32Response = "";
    unsigned long t = millis();
    while (millis() - t < 15000) {
      if (Serial1.available()) {
        esp32Response = Serial1.readStringUntil('\n');
        esp32Response.trim();
        break;
      }
      delay(10);
    }

    if (esp32Response == "FAIL") {
      Serial.print("ESP32_FAIL ");
      Serial.println(size);
      // Tell Python to skip remaining
      waitForAckOrSkip(skipRun);
      skipRun = true;
    } else {
      // OK or unknown — report sent and wait for Python ACK
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