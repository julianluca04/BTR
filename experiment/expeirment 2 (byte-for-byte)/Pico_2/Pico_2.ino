#include <Arduino.h>

const int LED_PIN = 25;

const int NUM_PAYLOADS = 21;
const long PAYLOAD_SIZES[NUM_PAYLOADS] = {
  1, 2, 4, 8, 16, 32, 64, 128, 256, 512,
  1024, 2048, 4096, 8192, 16384, 32768, 65536,
  131072, 262144, 524288, 1048576
};
const int SETTLE_MS      = 1000;
const int START_DELAY_MS = 500;
const int WINDOW         = 64;

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

    // Flush any stale bytes from previous transfer before starting
    delay(5);
    while (Serial1.available()) Serial1.read();

    long sent = 0;
    bool transferFail = false;

    while (sent < size) {
      Serial1.write(digit);
      sent++;

      // After every WINDOW bytes, wait for RDY — but only if more bytes remain
      if (sent % WINDOW == 0 && sent < size) {
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

    // Wait for final OK/FAIL from ESP32
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

  Serial.println("DONE");
  flashLED(3);
  started = false;
}