#include <bluefruit.h>

BLEUart bleuart;

#define CHUNK_SIZE 180

void setup() {
  Serial.begin(115200);
  Serial1.begin(115200);

  Bluefruit.begin();
  Bluefruit.setTxPower(4);
  Bluefruit.setName("NRF_UART");

  bleuart.begin();

  Bluefruit.Advertising.addFlags(BLE_GAP_ADV_FLAGS_LE_ONLY_GENERAL_DISC_MODE);
  Bluefruit.Advertising.addTxPower();
  Bluefruit.Advertising.addService(bleuart);
  Bluefruit.Advertising.addName();

  Bluefruit.Advertising.start(0);

  Serial.println("BLE UART ready");
}

int readLine(char* buf, int maxLen, int timeoutMs) {
  int idx = 0;
  unsigned long start = millis();

  while (millis() - start < timeoutMs) {
    while (Serial1.available()) {
      char c = Serial1.read();
      if (c == '\n') {
        buf[idx] = 0;
        return idx;
      }
      if (idx < maxLen - 1) {
        buf[idx++] = c;
      }
    }
  }
  return -1;
}

int readExact(uint8_t* buf, int len, int timeoutMs) {
  int got = 0;
  unsigned long start = millis();

  while (got < len && millis() - start < timeoutMs) {
    if (Serial1.available()) {
      buf[got++] = Serial1.read();
    }
  }
  return got;
}

void loop() {
  if (!bleuart.notifyEnabled()) return;

  char line[32];
  int len = readLine(line, sizeof(line), 30000);
  if (len <= 0) return;

  int size = atoi(line);
  if (size <= 0) return;

  bleuart.print("SIZE:");
  bleuart.println(size);

  uint8_t buf[CHUNK_SIZE];
  int remaining = size;

  while (remaining > 0) {
    int toRead = remaining > CHUNK_SIZE ? CHUNK_SIZE : remaining;
    int got = readExact(buf, toRead, 5000);

    if (got != toRead) {
      Serial.println("UART FAIL");
      return;
    }

    bleuart.write(buf, got);
    remaining -= got;
  }

  while (Serial1.available()) Serial1.read();
}