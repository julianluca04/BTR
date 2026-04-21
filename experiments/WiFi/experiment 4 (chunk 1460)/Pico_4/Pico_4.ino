#include <Arduino.h>

const int LED_PIN = 25;

const int NUM_PAYLOADS = 20;
const long PAYLOAD_SIZES[NUM_PAYLOADS] = {
  1, 2, 4, 8, 16, 32, 64, 128, 256, 512,
  1024, 2048, 4096, 8192, 16384, 32768, 65536,
  131072, 262144, 524288
};
const int SETTLE_MS          = 1000;
const int START_DELAY_MS     = 500;
const int CHUNK_SIZE         = 1460;
const int ESP32_BOOT_TIMEOUT = 15000;
const int TCP_CONNECT_WAIT_MS   = 400;
const int INTER_CHUNK_DELAY_MS  = 10;

bool started     = false;
bool warmRestarted = false;  // true after the initial warm-restart cycle completes

void flashLED(int times) {
  for (int i = 0; i < times; i++) {
    digitalWrite(LED_PIN, HIGH); delay(80);
    digitalWrite(LED_PIN, LOW);  delay(80);
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

  // Wait for ESP32's initial cold-boot BOOT signal
  Serial.println("[Pico] Waiting for ESP32 cold boot...");
  if (!waitForESP32Boot()) {
    Serial.println("[Pico] WARNING: ESP32 cold boot timeout.");
  } else {
    Serial.println("[Pico] ESP32 cold boot received.");
  }

  // Immediately trigger a warm restart on the ESP32 so that all runs
  // start from a consistent post-restart heap state (not cold-boot heap).
  // This eliminates the attempt-1 failure caused by cold-boot heap fragmentation.
  Serial.println("[Pico] Triggering ESP32 warm restart...");
  Serial1.println("DONE");
  delay(500);  // give ESP32 time to call ESP.restart()

  if (!waitForESP32Boot()) {
    Serial.println("[Pico] WARNING: ESP32 warm restart timeout.");
  } else {
    Serial.println("[Pico] ESP32 warm restart complete — heap state normalised.");
  }

  warmRestarted = true;
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
    delay(TCP_CONNECT_WAIT_MS);
    while (Serial1.available()) Serial1.read();

    static uint8_t sendBuf[CHUNK_SIZE];
    memset(sendBuf, (uint8_t)digit, CHUNK_SIZE);

    long sent = 0;
    while (sent < size) {
      int chunkBytes = (int)min((long)CHUNK_SIZE, size - sent);
      Serial1.write(sendBuf, chunkBytes);
      sent += chunkBytes;
      if (sent < size) delay(INTER_CHUNK_DELAY_MS);
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
