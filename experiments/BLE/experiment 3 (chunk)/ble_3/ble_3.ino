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
#define BLE_CHUNK 244  // ATT MTU 247 - 3 bytes overhead = 244 bytes max payload

static void bleSend(const uint8_t* buf, int len) {
  int offset = 0;
  while (offset < len) {
    int chunk = (len - offset < BLE_CHUNK) ? len - offset : BLE_CHUNK;
    int sent = bleuart.write(buf + offset, chunk);
    if (sent > 0) {
      offset += sent;
    } else {
      yield();  // TX queue full — let BLE stack drain before retrying
    }
  }
}

// UART chunk size matches BLE_CHUNK so each UART buffer fills exactly one
// BLE notification. The nRF buffers UART_CHUNK bytes, sends them over BLE,
// then immediately reads the next chunk — at most 244 bytes in RAM at once.
#define UART_CHUNK 244

void loop() {
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

  // Send SIZE header so the Mac knows how many bytes to expect
  char hdr[24];
  snprintf(hdr, sizeof(hdr), "SIZE:%d\n", size);
  bleSend((uint8_t*)hdr, strlen(hdr));

  // ── Chunked relay: buffer UART_CHUNK bytes, send immediately over BLE ──
  // At most UART_CHUNK (244) bytes are held in RAM at any moment.
  // This is the key difference from full_payload (entire message in RAM)
  // and byte_for_byte (1 byte in RAM at a time).
  uint8_t buf[UART_CHUNK];
  uint32_t total_sent = 0;
  uint32_t deadline   = millis() + 15000UL + (uint32_t)size;

  digitalWrite(LED_RED, LOW);

  while (total_sent < (uint32_t)size) {
    if (millis() > deadline) {
      // Drain remaining UART bytes so the line is clean for the next run
      while (Serial1.available()) Serial1.read();
      break;
    }

    // Fill the chunk buffer from UART up to UART_CHUNK bytes or remaining size
    int to_read = min((int)UART_CHUNK, (int)(size - total_sent));
    int got     = 0;
    uint32_t chunkDeadline = millis() + 5000UL + (uint32_t)to_read;
    while (got < to_read && millis() < chunkDeadline) {
      if (Serial1.available()) {
        buf[got++] = Serial1.read();
      } else {
        yield();  // drain BLE TX queue while waiting for next UART byte
      }
    }

    if (got == 0) continue;

    // Immediately relay this chunk over BLE before reading the next one
    bleSend(buf, got);
    total_sent += got;
  }

  digitalWrite(LED_RED, HIGH);

  // 3 quick flashes = done
  for (int i = 0; i < 3; i++) {
    digitalWrite(LED_RED, LOW); delay(30); digitalWrite(LED_RED, HIGH); delay(30);
  }
}
