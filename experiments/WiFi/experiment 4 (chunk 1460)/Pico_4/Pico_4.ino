#include <Arduino.h>

const int LED_PIN = 25;

const int NUM_PAYLOADS = 19;
const long PAYLOAD_SIZES[NUM_PAYLOADS] = {
  1, 2, 4, 8, 16, 32, 64, 128, 256, 512,
  1024, 2048, 4096, 8192, 16384, 32768, 65536,
  131072, 262144
  // 524288 excluded — ESP32-C3 heap fragmentation above ~262KB across repeated runs
};
const int SETTLE_MS          = 1000;
const int START_DELAY_MS     = 500;
const int FLOW_WINDOW        = 64;
const int ESP32_BOOT_TIMEOUT = 15000;

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
  while (millis() - t < 120000) {
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

bool waitForESP32Boot() {
  unsigned long t = millis();
  while (millis() - t < ESP32_BOOT_TIMEOUT) {
    if (Serial1.available()) {
      String msg = Serial1.readStringUntil('\n');
      msg.trim();
      if (msg == "BOOT") return true;
    }
    delay(10);
  }
  return false;
}

void setup() {
  Serial.begin(115200);
  Serial1.begin(115200);
  pinMode(LED_PIN, OUTPUT);
  delay(2000);

  Serial.println("[Pico] Waiting for ESP32 boot...");
  if (waitForESP32Boot()) {
    Serial.println("[Pico] ESP32 booted.");
  } else {
    Serial.println("[Pico] WARNING: ESP32 boot timeout on startup.");
  }
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
      delay(10);
    }
    return;
  }

  bool skipRun = false;

  for (int i = 0; i < NUM_PAYLOADS; i++) {
    if (skipRun) break;

    long size  = PAYLOAD_SIZES[i];
    char digit = '0' + (i % 10);

    Serial1.println(size);

    delay(5);
    while (Serial1.available()) Serial1.read();

    long sent = 0;
    bool transferFail = false;

    while (sent < size) {
      Serial1.write(digit);
      sent++;

      if (sent % FLOW_WINDOW == 0 && sent < size) {
        unsigned long t = millis();
        bool gotRdy = false;
        while (millis() - t < 5000) {
          if (Serial1.available()) {
            String msg = Serial1.readStringUntil('\n');
            msg.trim();
            if (msg == "RDY")  { gotRdy = true; break; }
            if (msg == "FAIL") { transferFail = true; break; }
          }
          delay(1);
        }
        if (!gotRdy) { transferFail = true; break; }
      }
    }

    if (transferFail) {
      Serial.print("ESP32_FAIL ");
      Serial.println(size);
      waitForAckOrSkip(skipRun);
      skipRun = true;
      continue;
    }

    String esp32Response = "";
    unsigned long t = millis();
    while (millis() - t < 120000) {
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

  Serial1.println("DONE");
  Serial.println("[Pico] Sent DONE to ESP32, waiting for reboot...");
  if (!waitForESP32Boot()) {
    Serial.println("[Pico] WARNING: ESP32 reboot timeout after run.");
  } else {
    Serial.println("[Pico] ESP32 rebooted cleanly.");
  }

  Serial.println("DONE");
  flashLED(3);
  started = false;
}