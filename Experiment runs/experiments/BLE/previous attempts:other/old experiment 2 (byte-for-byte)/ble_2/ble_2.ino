#include <bluefruit.h>

BLEUart bleuart;
volatile bool g_connected = false;

void connect_callback(uint16_t conn_handle) {
  (void) conn_handle;
  g_connected = true;
}

void disconnect_callback(uint16_t conn_handle, uint8_t reason) {
  (void) conn_handle;
  (void) reason;
  g_connected = false;
}

void setup() {
  pinMode(LED_RED, OUTPUT);
  digitalWrite(LED_RED, HIGH);

  // Must be before Bluefruit.begin(). Raises ATT MTU cap to 247 bytes
  // (244 bytes data per notification) and hvn_qsize to 3.
  Bluefruit.configPrphBandwidth(BANDWIDTH_MAX);

  Serial1.begin(115200);
  delay(100);

  Bluefruit.begin();
  Bluefruit.setTxPower(4);
  Bluefruit.Periph.setConnectCallback(connect_callback);
  Bluefruit.Periph.setDisconnectCallback(disconnect_callback);

  bleuart.begin();

  Bluefruit.Advertising.addFlags(BLE_GAP_ADV_FLAGS_LE_ONLY_GENERAL_DISC_MODE);
  Bluefruit.Advertising.addTxPower();
  Bluefruit.Advertising.addService(bleuart);
  Bluefruit.ScanResponse.addName();
  Bluefruit.Advertising.restartOnDisconnect(true);
  Bluefruit.Advertising.start(0);
}

// Send `len` bytes over BLE in BLE_CHUNK-sized notifications.
// Retries each write until it succeeds so no bytes are silently dropped.
#define BLE_CHUNK 240

static void bleSend(const uint8_t* buf, int len) {
  int offset = 0;
  while (offset < len) {
    int chunk = (len - offset < BLE_CHUNK) ? len - offset : BLE_CHUNK;
    int sent = bleuart.write(buf + offset, chunk);
    if (sent > 0) {
      offset += sent;
    } else {
      delay(1);  // TX queue full — yield and retry
    }
  }
}


void loop() {
  // Gate only on connection — not notifyEnabled() which can return false
  // even after the central has subscribed on this device/library version.
  if (!g_connected) {
    digitalWrite(LED_RED, LOW);  delay(100);
    digitalWrite(LED_RED, HIGH); delay(900);
    return;
  }

  if (!Serial1.available()) return;

  // Read size line from Pico, e.g. "8192\n"
  String line = "";
  uint32_t lineDeadline = millis() + 1000;
  while (millis() < lineDeadline) {
    if (Serial1.available()) {
      char c = Serial1.read();
      if (c == '\n') break;
      line += c;
    }
  }
  line.trim();
  int size = line.toInt();
  if (size <= 0) return;

  // ── Send SIZE header as a single BLE notification so the Mac can parse it ──
  char hdr[24];
  snprintf(hdr, sizeof(hdr), "SIZE:%d\n", size);
  bleSend((uint8_t*)hdr, strlen(hdr));

  // ── Byte-for-byte relay — 1 byte stored on nRF at a time ──
  // The Pico paces its UART output to one byte every ~10 ms (≥ 1 BLE
  // connection interval), so bytes never pile up here. pending_byte is the
  // only buffer: at most 1 byte is held on the nRF at any moment.
  // bleuart.write(&b, 1) is non-blocking: if the TX queue is momentarily
  // full (returns 0) we retry next iteration without losing the byte.
  bool     has_pending  = false;
  uint8_t  pending_byte = 0;
  uint32_t ble_sent     = 0;
  uint32_t deadline     = millis() + 15000UL + (uint32_t)size * 15UL;

  digitalWrite(LED_RED, LOW);

  while (ble_sent < (uint32_t)size) {
    if (millis() > deadline) {
      while (Serial1.available()) Serial1.read();
      break;
    }

    // Read one UART byte into the pending slot (only when slot is empty).
    if (!has_pending && Serial1.available()) {
      pending_byte = Serial1.read();
      has_pending  = true;
    }

    // Send pending byte as its own BLE notification (non-blocking).
    // yield() when queue is full so the FreeRTOS BLE tasks can drain it —
    // without this the app task spins tight and inflates the power reading.
    if (has_pending) {
      if (bleuart.write(&pending_byte, 1) > 0) {
        has_pending = false;
        ble_sent++;
      } else {
        yield();  // queue full — let BLE stack run before retrying
      }
    }
  }

  digitalWrite(LED_RED, HIGH);

  // 3 quick flashes = done
  for (int i = 0; i < 3; i++) {
    digitalWrite(LED_RED, LOW); delay(30); digitalWrite(LED_RED, HIGH); delay(30);
  }
}
