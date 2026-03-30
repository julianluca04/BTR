/*
 * ble_full.ino  —  nRF52840 (XIAO BLE / Seeed)
 * Strategy: full_payload
 *
 * Protocol:
 *   1. Wait for SIZE:<n>\n from Pico via UART (Serial1)
 *   2. Read exactly n bytes from Pico
 *   3. Buffer is complete → send SIZE:<n>\n header over BLE NUS TX
 *   4. Stream buffer in MTU-sized chunks over BLE NUS TX notifications
 *   5. Reply "OK\n" to Pico on success, "FAIL\n" on error
 *
 * BLE: Nordic UART Service (NUS)
 *   Service UUID : 6E400001-B5A3-F393-E0A9-E50E24DCCA9E
 *   TX char UUID : 6E400003-B5A3-F393-E0A9-E50E24DCCA9E  (notify, nRF→Central)
 *   RX char UUID : 6E400002-B5A3-F393-E0A9-E50E24DCCA9E  (write,  Central→nRF)
 */

#include <bluefruit.h>

// ── UART (Pico) ──────────────────────────────────────────────────────────────
// XIAO BLE Sense: Serial1 = D6(TX)/D7(RX) by default
#define PICO_BAUD   115200
#define MAX_PAYLOAD 131072   // 128 KB ceiling; matches Python PAYLOAD_SIZES top

// ── BLE NUS ──────────────────────────────────────────────────────────────────
BLEUart bleuart;

// MTU negotiated at connect; we learn it then.
// Safe default before negotiation.
static uint16_t g_mtu_payload = 20;  // updated in connect callback

// ── State ────────────────────────────────────────────────────────────────────
static uint8_t* g_buf        = nullptr;
static bool     g_connected  = false;

// ── Callbacks ────────────────────────────────────────────────────────────────
void connect_callback(uint16_t conn_handle) {
  g_connected = true;

  // Request larger MTU; peer (bleak) must also support it.
  // Bluefruit default negotiates up to 247.  After negotiation,
  // BLEUart::write() auto-fragments, but we manage chunks ourselves
  // to keep timing deterministic.
  BLEConnection* conn = Bluefruit.Connection(conn_handle);
  conn->requestMtuExchange(247);

  Serial.println("[BLE] Central connected.");
}

void mtu_callback(uint16_t conn_handle, uint16_t mtu) {
  // ATT_MTU includes 3 bytes overhead → payload = mtu - 3
  g_mtu_payload = mtu - 3;
  Serial.print("[BLE] MTU exchanged: ");
  Serial.print(mtu);
  Serial.print(" → payload bytes per notif: ");
  Serial.println(g_mtu_payload);
}

void disconnect_callback(uint16_t conn_handle, uint8_t reason) {
  g_connected = false;
  Serial.print("[BLE] Disconnected, reason=0x");
  Serial.println(reason, HEX);
  // Restart advertising so Mac can reconnect for next run
  Bluefruit.Advertising.start(0);
}

// ── Setup ────────────────────────────────────────────────────────────────────
void setup() {
  Serial.begin(115200);
  delay(2000);

  Serial1.begin(PICO_BAUD);

  // Allocate buffer once
  g_buf = (uint8_t*)malloc(MAX_PAYLOAD);
  if (!g_buf) {
    Serial.println("[BLE] FATAL: malloc failed for g_buf");
    while (1) { delay(1000); }
  }

  Bluefruit.begin();
  Bluefruit.setName("NRF-BLE-FULL");
  Bluefruit.setTxPower(4);  // dBm; 4 is reasonable for bench work

  Bluefruit.Callbacks.setConnected(connect_callback);
  Bluefruit.Callbacks.setDisconnected(disconnect_callback);
  Bluefruit.Callbacks.setMtuExchanged(mtu_callback);

  bleuart.begin();

  Bluefruit.Advertising.addFlags(BLE_GAP_ADV_FLAGS_LE_ONLY_GENERAL_DISC_MODE);
  Bluefruit.Advertising.addTxPower();
  Bluefruit.Advertising.addService(bleuart);
  Bluefruit.Advertising.addName();
  Bluefruit.Advertising.restartOnDisconnect(true);
  Bluefruit.Advertising.setInterval(32, 244);  // units of 0.625 ms
  Bluefruit.Advertising.setFastTimeout(30);
  Bluefruit.Advertising.start(0);

  Serial.println("[BLE] Advertising started — waiting for central...");
}

// ── Helpers ──────────────────────────────────────────────────────────────────

// Read a '\n'-terminated line from Serial1 (Pico UART).
// Returns number of chars (not including '\n'), or -1 on timeout.
int readLineFromPico(char* out, int maxLen, unsigned long timeoutMs = 10000) {
  int pos = 0;
  unsigned long t = millis();
  while (millis() - t < timeoutMs) {
    if (Serial1.available()) {
      char c = (char)Serial1.read();
      if (c == '\n') {
        out[pos] = '\0';
        // Trim '\r' if present
        if (pos > 0 && out[pos-1] == '\r') out[--pos] = '\0';
        return pos;
      }
      if (pos < maxLen - 1) out[pos++] = c;
    }
  }
  out[pos] = '\0';
  return -1;  // timeout
}

// Read exactly `needed` bytes from Serial1 into dst.
// Returns actual bytes read.
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

// Send buffer over BLE NUS in MTU-sized chunks.
// Returns true if all bytes sent without error.
bool sendOverBLE(const uint8_t* data, int len) {
  if (!g_connected) return false;

  // 1. Header: "SIZE:<n>\n"
  char header[32];
  snprintf(header, sizeof(header), "SIZE:%d\n", len);
  bleuart.write((const uint8_t*)header, strlen(header));
  delay(5);  // brief gap so central can parse header before data flood

  // 2. Data chunks
  int offset = 0;
  while (offset < len) {
    if (!g_connected) return false;
    int chunk = min((int)g_mtu_payload, len - offset);
    bleuart.write(data + offset, chunk);
    offset += chunk;
    // Small yield to allow BLE stack to flush; tune if needed
    delay(1);
  }
  return true;
}

// ── Main loop ────────────────────────────────────────────────────────────────
void loop() {
  // Wait for Pico to send SIZE:<n>\n
  if (!Serial1.available()) return;

  char lineBuf[32];
  int lineLen = readLineFromPico(lineBuf, sizeof(lineBuf), 30000);

  if (lineLen < 0) {
    Serial.println("[BLE] Timeout waiting for SIZE line from Pico");
    return;
  }

  // Parse "SIZE:<n>" or bare "<n>" (Pico sends bare int then newline)
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

  // Read full payload from Pico
  int got = readExactFromPico(g_buf, payloadSize, 60000);

  // Consume trailing '\n' that Pico appends after data
  unsigned long t = millis();
  while (millis() - t < 500) {
    if (Serial1.available()) { Serial1.read(); break; }
  }

  if (got != payloadSize) {
    Serial.print("[BLE] INCOMPLETE from Pico: ");
    Serial.print(got);
    Serial.print("/");
    Serial.println(payloadSize);
    Serial1.println("FAIL");
    return;
  }

  Serial.print("[BLE] Buffered ");
  Serial.print(got);
  Serial.println("B — sending over BLE...");

  // Wait for BLE connection if not yet connected
  t = millis();
  while (!g_connected && millis() - t < 30000) {
    delay(100);
  }
  if (!g_connected) {
    Serial.println("[BLE] No central connected — FAIL");
    Serial1.println("FAIL");
    return;
  }

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
