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

// Read exactly `len` bytes from Serial1 before deadline.
// Returns number of bytes actually read (< len only on timeout).
static int readAll(uint8_t* buf, int len, uint32_t deadline) {
  int got = 0;
  while (got < len && millis() < deadline) {
    if (Serial1.available()) buf[got++] = Serial1.read();
  }
  return got;
}

// Send `len` bytes over BLE in BLE_CHUNK-sized notifications.
// Retries each write until it succeeds so no bytes are silently dropped
// when the TX queue is momentarily full.
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

  // ── Buffer the entire payload from UART before sending anything over BLE ──
  // This measures the latency impact of loading the full message onto the
  // module first, rather than streaming bytes through as they arrive.
  uint8_t* buf = (uint8_t*) malloc(size);
  if (!buf) {
    bleuart.write((uint8_t*)"FAIL\n", 5);
    // Drain any partial payload bytes the Pico is still sending over UART.
    // Wait until 500 ms of silence — then the line is clean for the next size.
    uint32_t lastActivity = millis();
    while (millis() - lastActivity < 500) {
      if (Serial1.available()) {
        Serial1.read();
        lastActivity = millis();
      }
    }
    return;
  }

  // Allow generous time: 15 s headroom + 1 ms per byte at 115200 baud
  uint32_t deadline = millis() + 15000UL + (uint32_t)size;
  int got = readAll(buf, size, deadline);

  if (got != size) {
    free(buf);
    bleuart.write((uint8_t*)"FAIL\n", 5);
    return;
  }

  // LED: fast blink = about to send
  digitalWrite(LED_RED, LOW); delay(30); digitalWrite(LED_RED, HIGH);

  // ── Entire payload is in RAM — now send SIZE header then payload over BLE ──
  char hdr[24];
  snprintf(hdr, sizeof(hdr), "SIZE:%d\n", size);
  bleSend((uint8_t*) hdr, strlen(hdr));
  bleSend(buf, size);

  free(buf);

  // LED: 3 quick flashes = done
  for (int i = 0; i < 3; i++) {
    digitalWrite(LED_RED, LOW); delay(30); digitalWrite(LED_RED, HIGH); delay(30);
  }
}
