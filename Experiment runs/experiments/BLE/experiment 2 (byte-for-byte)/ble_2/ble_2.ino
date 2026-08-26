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

void loop() {
  if (!g_connected) {
    digitalWrite(LED_RED, LOW);  delay(100);
    digitalWrite(LED_RED, HIGH); delay(900);
    return;
  }

  if (!Serial1.available()) return;

  // Read size line from Pico e.g. "256\n"
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

  // Send SIZE header to Mac
  char hdr[24];
  snprintf(hdr, sizeof(hdr), "SIZE:%d\n", size);
  int offset = 0;
  while (offset < (int)strlen(hdr)) {
    int sent = bleuart.write((uint8_t*)hdr + offset, strlen(hdr) - offset);
    if (sent > 0) offset += sent;
    else delay(1);
  }

  // ── BLE-gated byte-for-byte relay ────────────────────────────────────────
  // Flow per byte:
  //   1. nRF waits for one byte from Pico on UART
  //   2. nRF calls bleuart.write(&b, 1) — retries until the BLE TX queue
  //      accepts it (queue full → yield so BLE stack can drain it)
  //   3. Once accepted, nRF sends "OK\n" to Pico — no Mac confirmation needed
  //   4. Pico sends the next byte
  //
  // "Accepted into TX queue" is the gate — the BLE stack guarantees delivery
  // to the connected central once the byte is in the queue.
  // ─────────────────────────────────────────────────────────────────────────

  uint32_t ble_sent = 0;
  uint32_t deadline = millis() + 15000UL + (uint32_t)size * 15UL;

  digitalWrite(LED_RED, LOW);

  while (ble_sent < (uint32_t)size) {
    if (millis() > deadline) {
      while (Serial1.available()) Serial1.read();
      Serial1.println("FAIL");
      digitalWrite(LED_RED, HIGH);
      return;
    }

    // Wait for one byte from Pico
    if (!Serial1.available()) { yield(); continue; }
    uint8_t b = Serial1.read();

    // Send it over BLE — retry until the TX queue accepts it
    while (bleuart.write(&b, 1) == 0) {
      yield();  // queue full — let BLE stack drain before retrying
    }

    // TX queue accepted the byte — tell Pico to send the next one
    Serial1.println("OK");
    ble_sent++;
  }

  digitalWrite(LED_RED, HIGH);

  for (int i = 0; i < 3; i++) {
    digitalWrite(LED_RED, LOW); delay(30);
    digitalWrite(LED_RED, HIGH); delay(30);
  }
}
