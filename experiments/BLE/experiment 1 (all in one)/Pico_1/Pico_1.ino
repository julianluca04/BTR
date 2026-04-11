#include <Arduino.h>

const int LED_PIN = 25;
const int NUM_PAYLOADS = 18;
const int PAYLOAD_SIZES[NUM_PAYLOADS] = {
  1, 2, 4, 8, 16, 32, 64, 128, 256, 512,
  1024, 2048, 4096, 8192, 16384, 32768, 65536,
  131072
};
const int SETTLE_MS      = 1000;
const int START_DELAY_MS = 500;

void flashLED(int times) {
  for (int i = 0; i < times; i++) {
    digitalWrite(LED_PIN, HIGH); delay(80);
    digitalWrite(LED_PIN, LOW);  delay(80);
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

void runExperiment() {
  bool skipRun = false;

  for (int i = 0; i < NUM_PAYLOADS; i++) {
    if (skipRun) break;

    int size   = PAYLOAD_SIZES[i];
    char digit = '0' + (i % 10);

    // Send SIZE marker so Mac knows what to expect
    Serial1.print("SIZE:");
    Serial1.println(size);
    delay(50);

    // Send payload bytes
    int sent = 0;
    while (sent < size) {
      int chunk = min(256, size - sent);
      for (int j = 0; j < chunk; j++) Serial1.write(digit);
      sent += chunk;
      delay(10);
    }

    // Send END marker
    Serial1.println("END");

    Serial.print("SENT ");
    Serial.print(size);
    Serial.println("B");
    flashLED(1);

    waitForAckOrSkip(skipRun);
    if (!skipRun) delay(SETTLE_MS);
  }

  Serial.println("DONE");
  flashLED(3);
}

void setup() {
  Serial.begin(115200);
  Serial1.begin(115200);
  pinMode(LED_PIN, OUTPUT);
  delay(2000);
}

void loop() {
  Serial.println("READY");
  while (true) {
    if (Serial.available()) {
      String cmd = Serial.readStringUntil('\n');
      cmd.trim();
      if (cmd == "go") {
        Serial.print("START_IN_");
        Serial.println(START_DELAY_MS);
        delay(START_DELAY_MS);
        runExperiment();
        break;
      }
    }
    delay(50);
  }
}