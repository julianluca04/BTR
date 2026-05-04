#include <Arduino.h>

const int LED_PIN = 25;
const int NUM_PAYLOADS = 20;
const long PAYLOAD_SIZES[NUM_PAYLOADS] = {
  1, 2, 4, 8, 16, 32, 64, 128, 256, 512,
  1024, 2048, 4096, 8192, 16384, 32768, 65536,
  131072, 262144, 524288
};

const int UART_CHUNK      = 244; // BLE MTU limit
const int SETTLE_MS       = 1000;
const int START_DELAY_MS  = 500;
const int ACK_TIMEOUT     = 10000; 

bool started = false;

// Wait for Mac to say "ACK" or "SKIP" via USB
void waitForAckOrSkip(bool &skipRun) {
  unsigned long t = millis();
  while (millis() - t < 30000) { 
    if (Serial.available()) {
      String msg = Serial.readStringUntil('\n');
      msg.trim();
      if (msg == "ACK")  return;
      if (msg == "SKIP") { skipRun = true; return; }
    }
  }
  skipRun = true; 
}

// Wait for nRF to send a specific signal over UART
bool waitForNRF(const char* expected) {
  unsigned long t = millis();
  while (millis() - t < ACK_TIMEOUT) {
    if (Serial1.available()) {
      String msg = Serial1.readStringUntil('\n');
      msg.trim();
      if (msg == expected) return true;
    }
  }
  return false;
}

void setup() {
  Serial.begin(115200);
  Serial1.begin(115200);
  pinMode(LED_PIN, OUTPUT);
}

void loop() {
  // Nag loop: Keep shouting READY until Python sends "go"
  if (!started) {
    Serial.println("READY");
    digitalWrite(LED_PIN, HIGH); delay(100);
    digitalWrite(LED_PIN, LOW);

    if (Serial.available()) {
      String cmd = Serial.readStringUntil('\n');
      cmd.trim();
      if (cmd == "go") {
        Serial.print("START_IN_"); Serial.println(START_DELAY_MS);
        delay(START_DELAY_MS);
        started = true;
      }
    }
    delay(900);
    return;
  }

  bool skipRun = false;
  for (int i = 0; i < NUM_PAYLOADS; i++) {
    if (skipRun) break;

    long size  = PAYLOAD_SIZES[i];
    char digit = '0' + (i % 10);

    // 1. Tell nRF the size and wait for "READY_TO_RECV" (TCPOK equivalent)
    while(Serial1.available()) Serial1.read(); 
    Serial1.println(size);

    if (!waitForNRF("READY_TO_RECV")) {
      Serial.print("NRF_FAIL "); Serial.println(size);
      skipRun = true;
      continue;
    }

    // 2. Chunking loop
    long sent = 0;
    while (sent < size) {
      int to_send = (int)min((long)UART_CHUNK, size - sent);
      for (int j = 0; j < to_send; j++) {
        Serial1.write(digit);
      }
      sent += to_send;

      // 3. Wait for "N" (CHUNKACK equivalent) if more data is left
      if (sent < size) {
        if (!waitForNRF("N")) {
          skipRun = true;
          break;
        }
      }
    }

    if (!skipRun) {
      Serial.print("SENT "); Serial.print(size); Serial.println("B");
      waitForAckOrSkip(skipRun); // Wait for Mac script to finish logging
      delay(SETTLE_MS);
    }
  }

  Serial.println("DONE");
  started = false;
}