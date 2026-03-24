// =============================================================
// EXPERIMENT 1 — Byte-by-byte relay (ESP32 WiFi module)
//
// Receives bytes from Pico over UART one at a time.
// Each byte is written to the open TCP connection immediately.
// client.setNoDelay(true) disables Nagle's algorithm so the
// TCP stack does NOT wait to batch bytes — they are sent as
// individual segments, giving true byte-level forwarding.
// =============================================================

#include <WiFi.h>

HardwareSerial picoSerial(1);
const int RX_PIN = 20;  // XIAO D7  →  Pico GP0 (TX)
const int TX_PIN = 21;  // XIAO D6  →  Pico GP1 (RX)

const char* AP_SSID  = "esp32_test";
const char* AP_PASS  = "esp32test";
const char* MAC_IP   = "192.168.4.2";
const int   MAC_PORT = 8080;

#define MAX_PAYLOAD 1024
#define RX_TIMEOUT_MS 10000

void setup() {
  Serial.begin(115200);
  delay(2000);
  picoSerial.begin(115200, SERIAL_8N1, RX_PIN, TX_PIN);

  WiFi.mode(WIFI_AP);
  WiFi.softAP(AP_SSID, AP_PASS);

  Serial.println("[ESP32 EXP1] AP started");
  Serial.print("[ESP32 EXP1] IP: ");
  Serial.println(WiFi.softAPIP());
  Serial.println("[ESP32 EXP1] Byte-by-byte relay ready.");
}

void loop() {
  if (!picoSerial.available()) return;

  // --- Read size header ---
  int payloadSize = picoSerial.parseInt();
  picoSerial.readStringUntil('\n'); // consume rest of header line

  if (payloadSize <= 0 || payloadSize > MAX_PAYLOAD) {
    Serial.print("[ESP32 EXP1] Invalid size: ");
    Serial.println(payloadSize);
    return;
  }

  Serial.print("[ESP32 EXP1] Expecting ");
  Serial.print(payloadSize);
  Serial.println(" bytes — opening TCP connection...");

  WiFiClient client;
  client.setNoDelay(true); // disable Nagle: send each write immediately
  if (!client.connect(MAC_IP, MAC_PORT)) {
    Serial.println("[ESP32 EXP1] ERROR: Cannot connect to Mac.");
    return;
  }

  // Forward size header to Mac
  client.println(payloadSize);

  // --- Stream bytes one by one ---
  int received       = 0;
  unsigned long deadline = millis() + RX_TIMEOUT_MS;

  while (received < payloadSize && millis() < deadline) {
    if (picoSerial.available()) {
      uint8_t b = picoSerial.read();
      client.write(b);   // write single byte
      // No explicit flush needed — setNoDelay ensures immediate send
      received++;
      if (received % 32 == 0) Serial.print("."); // progress dots
    }
  }

  client.write('\n'); // end-of-message marker
  client.stop();

  Serial.println();
  Serial.print("[ESP32 EXP1] Done. Forwarded ");
  Serial.print(received);
  Serial.println(" bytes byte-by-byte.");
  Serial.println("--------------------------------------------------");
}
