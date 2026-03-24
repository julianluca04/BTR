// =============================================================
// EXPERIMENT 3 — Full-buffer relay (ESP32 WiFi module)
//
// Receives ALL bytes from Pico over UART into a local buffer.
// Only AFTER the complete message is received does it open a
// TCP connection and send everything in a single write.
//
// This minimises the number of TCP segments and gives the
// lowest per-message overhead — at the cost of higher latency
// before the first byte arrives at the Mac.
// =============================================================

#include <WiFi.h>

HardwareSerial picoSerial(1);
const int RX_PIN = 20;
const int TX_PIN = 21;

const char* AP_SSID  = "esp32_test";
const char* AP_PASS  = "esp32test";
const char* MAC_IP   = "192.168.4.2";
const int   MAC_PORT = 8080;

#define MAX_PAYLOAD   1024
#define RX_TIMEOUT_MS 10000

uint8_t msgBuffer[MAX_PAYLOAD]; // holds the entire message before sending

void setup() {
  Serial.begin(115200);
  delay(2000);
  picoSerial.begin(115200, SERIAL_8N1, RX_PIN, TX_PIN);

  WiFi.mode(WIFI_AP);
  WiFi.softAP(AP_SSID, AP_PASS);

  Serial.println("[ESP32 EXP3] AP started");
  Serial.print("[ESP32 EXP3] IP: ");
  Serial.println(WiFi.softAPIP());
  Serial.println("[ESP32 EXP3] Full-buffer relay ready.");
}

void loop() {
  if (!picoSerial.available()) return;

  // --- Read size header ---
  int payloadSize = picoSerial.parseInt();
  picoSerial.readStringUntil('\n');

  if (payloadSize <= 0 || payloadSize > MAX_PAYLOAD) {
    Serial.print("[ESP32 EXP3] Invalid size: ");
    Serial.println(payloadSize);
    return;
  }

  Serial.print("[ESP32 EXP3] Buffering ");
  Serial.print(payloadSize);
  Serial.println(" bytes before sending...");

  // --- Buffer the ENTIRE message first ---
  int received      = 0;
  unsigned long deadline = millis() + RX_TIMEOUT_MS;

  while (received < payloadSize && millis() < deadline) {
    if (picoSerial.available()) {
      msgBuffer[received++] = picoSerial.read();
      if (received % 64 == 0) Serial.print("."); // progress indicator
    }
  }
  Serial.println();

  if (received < payloadSize) {
    Serial.println("[ESP32 EXP3] WARNING: Timeout — message incomplete.");
  }

  Serial.print("[ESP32 EXP3] Buffer full (");
  Serial.print(received);
  Serial.println(" bytes). Opening TCP connection...");

  // --- Now connect and send everything at once ---
  WiFiClient client;
  if (!client.connect(MAC_IP, MAC_PORT)) {
    Serial.println("[ESP32 EXP3] ERROR: Cannot connect to Mac.");
    return;
  }

  // Send size header
  client.println(payloadSize);

  // Send entire buffered message in one write
  client.write(msgBuffer, received);
  client.write('\n'); // end-of-message marker
  client.stop();

  Serial.println("[ESP32 EXP3] Done. Sent full message in one TCP write.");
  Serial.println("--------------------------------------------------");
}
