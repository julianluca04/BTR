/*
 * ble_1.ino  —  nRF52840 (XIAO BLE / Seeed)
 * Strategy: full_payload
 *
 * Uses the same custom characteristic + fileChar.notify() pattern
 * as the working uploaddoc.ino, adapted for the experiment protocol.
 *
 * Custom Service UUID : 12345678-1234-1234-1234-1234567890ab
 * TX Char UUID        : 12345678-1234-1234-1234-1234567890ac  (notify -> Mac)
 *
 * Protocol:
 *   1. Wait for BLE central to connect
 *   2. Wait for <size>\n from Pico via UART (Serial1)
 *   3. Read exactly size bytes from Pico
 *   4. Notify "SIZE:<n>\n" header over TX characteristic
 *   5. Notify payload in chunks
 *   6. Reply "OK\n" to Pico on success, "FAIL\n" on error
 */

#include <bluefruit.h>

#define PICO_BAUD    115200
#define MAX_PAYLOAD  131072
#define CHUNK_SIZE   180

// Use same UUIDs as working uploaddoc.ino
BLEService        dataService("12345678-1234-1234-1234-1234567890ab");
BLECharacteristic dataChar("12345678-1234-1234-1234-1234567890ac");

static uint8_t* g_buf = nullptr;

// ── Setup ────────────────────────────────────────────────────────────────────
void setup() {
  Serial.begin(115200);
  delay(2000);

  Serial1.begin(PICO_BAUD);

  g_buf = (uint8_t*)malloc(MAX_PAYLOAD);
  if (!g_buf) {
    Serial.println("[BLE] FATAL: malloc failed");
    while (1) { delay(1000); }
  }

  Bluefruit.begin();
  Bluefruit.setName("XIAO-FILE-SENDER");
  Bluefruit.setTxPower(4);

  dataService.begin();

  dataChar.setProperties(CHR_PROPS_NOTIFY);
  dataChar.setPermission(SECMODE_OPEN, SECMODE_NO_ACCESS);
  dataChar.setFixedLen(CHUNK_SIZE);
  dataChar.begin();

  Bluefruit.Advertising.addService(dataService);
  Bluefruit.Advertising.addName();
  Bluefruit.Advertising.restartOnDisconnect(true);
  Bluefruit.Advertising.setInterval(32, 244);
  Bluefruit.Advertising.setFastTimeout(30);
  Bluefruit.Advertising.start(0);

  Serial.println("[BLE] Advertising — waiting for central...");
}

// ── Helpers ──────────────────────────────────────────────────────────────────
int readLineFromPico(char* out, int maxLen, unsigned long timeoutMs = 10000) {
  int pos = 0;
  unsigned long t = millis();
  while (millis() - t < timeoutMs) {
    if (Serial1.available()) {
      char c = (char)Serial1.read();
      if (c == '\n') {
        out[pos] = '\0';
        if (pos > 0 && out[pos-1] == '\r') out[--pos] = '\0';
        return pos;
      }
      if (pos < maxLen - 1) out[pos++] = c;
    }
  }
  out[pos] = '\0';
  return -1;
}

int readExactFromPico(uint8_t* dst, int needed, unsigned long timeoutMs = 60000) {
  int got = 0;
  unsigned long t = millis();
  while (got < needed && millis() - t < timeoutMs) {
    if (Serial1.available()) {
      dst[got++] = (uint8_t)Serial1.read();
    }
  }
  return got;
}

bool sendOverBLE(const uint8_t* data, int len) {
  // Send header "SIZE:<n>\n"
  char header[32];
  snprintf(header, sizeof(header), "SIZE:%d\n", len);
  dataChar.notify((uint8_t*)header, strlen(header));
  delay(5);

  // Send data in chunks
  int offset = 0;
  while (offset < len) {
    if (!Bluefruit.connected()) return false;
    int chunk = min((int)CHUNK_SIZE, len - offset);
    dataChar.notify(data + offset, chunk);
    offset += chunk;
    delay(10);  // same delay as working uploaddoc.ino
  }
  return true;
}

// ── Main loop ────────────────────────────────────────────────────────────────
void loop() {
  if (!Bluefruit.connected()) {
    delay(10);
    return;
  }

  if (!Serial1.available()) return;

  char lineBuf[32];
  int lineLen = readLineFromPico(lineBuf, sizeof(lineBuf), 30000);

  if (lineLen < 0) {
    Serial.println("[BLE] Timeout waiting for SIZE line from Pico");
    return;
  }

  int payloadSize = 0;
  if (strncmp(lineBuf, "SIZE:", 5) == 0) {
    payloadSize = atoi(lineBuf + 5);
  } else {
    payloadSize = atoi(lineBuf);
  }

  if (payloadSize <= 0 || payloadSize > MAX_PAYLOAD) {
    Serial.print("[BLE] Rejected size: ");
    Serial.println(payloadSize);
    Serial1.println("FAIL");
    return;
  }

  Serial.print("[BLE] Expecting ");
  Serial.print(payloadSize);
  Serial.println("B from Pico...");

  int got = readExactFromPico(g_buf, payloadSize, 60000);

  // Consume trailing '\n'
  unsigned long t = millis();
  while (millis() - t < 500) {
    if (Serial1.available()) { Serial1.read(); break; }
  }

  if (got != payloadSize) {
    Serial.print("[BLE] INCOMPLETE: ");
    Serial.print(got);
    Serial.print("/");
    Serial.println(payloadSize);
    Serial1.println("FAIL");
    return;
  }

  Serial.print("[BLE] Buffered ");
  Serial.print(got);
  Serial.println("B — sending over BLE...");

  if (sendOverBLE(g_buf, got)) {
    Serial.print("[BLE] Sent ");
    Serial.print(got);
    Serial.println("B OK.");
    Serial1.println("OK");
  } else {
    Serial.println("[BLE] BLE send failed.");
    Serial1.println("FAIL");
  }
}
