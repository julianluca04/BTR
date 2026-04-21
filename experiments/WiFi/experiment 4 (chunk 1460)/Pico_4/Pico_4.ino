#include <Arduino.h>

const int LED_PIN = 25;

const int NUM_PAYLOADS = 20;
const long PAYLOAD_SIZES[NUM_PAYLOADS] = {
  1, 2, 4, 8, 16, 32, 64, 128, 256, 512,
  1024, 2048, 4096, 8192, 16384, 32768, 65536,
  131072, 262144, 524288
};
const int SETTLE_MS             = 1000;
const int START_DELAY_MS        = 500;
const int CHUNK_SIZE            = 1460;
const int ESP32_BOOT_TIMEOUT    = 15000;
const int INTER_CHUNK_DELAY_MS  = 10;

// Wait after sending the size line before blasting payload bytes.
// Must cover: ESP32 parsing size + apReady check + client.connect() (~200 ms).
// 800 ms gives comfortable headroom after a post-run restart.
const int TCP_CONNECT_WAIT_MS = 800;

bool started = false;

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

  // Drain anything the ESP32 may have sent during cold boot.
  delay(3000);
  while (Serial1.available()) Serial1.read();

  // Unconditionally force a warm restart so every run starts from a consistent
  // post-restart heap state regardless of cold-boot timing.
  Serial.println("[Pico] Forcing ESP32 warm restart...");
  Serial1.println("DONE");

  if (waitForESP32Boot()) {
    Serial.println("[Pico] ESP32 warm restart complete.");
  } else {
    Serial.println("[Pico] ESP32 warm restart timeout — continuing anyway.");
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

    // Send size line then wait for ESP32 to open TCP connection.
    Serial1.println(size);
    delay(TCP_CONNECT_WAIT_MS);
    // Drain any stale bytes (e.g. lingering OK from previous payload).
    while (Serial1.available()) Serial1.read();

    static uint8_t sendBuf[CHUNK_SIZE];
    memset(sendBuf, (uint8_t)digit, CHUNK_SIZE);

    long sent = 0;
    while (sent < size) {
      int chunkBytes = (int)min((long)CHUNK_SIZE, size - sent);
      Serial1.write(sendBuf, chunkBytes);
      sent += chunkBytes;
      // Brief inter-chunk gap prevents the ESP32 UART RX buffer from filling
      // faster than it drains into TCP. Skip delay after the last chunk.
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
