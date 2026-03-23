#include <WiFi.h>

HardwareSerial picoSerial(1);
const int RX_PIN = 6;  // D6 RX, connects to Pico GP4 (TX)
const int TX_PIN = 7;  // D7 TX, connects to Pico GP3 (RX)

const char* AP_SSID = "esp32_test";
const char* AP_PASS = "esp32test";

WiFiClient client;

#define MAX_PAYLOAD 1024

void setup() {
  Serial.begin(115200);
  picoSerial.begin(115200, SERIAL_8N1, RX_PIN, TX_PIN);

  WiFi.mode(WIFI_AP);
  WiFi.softAP(AP_SSID, AP_PASS);

  Serial.println("[ESP32] AP started");
  Serial.print("[ESP32] IP: ");
  Serial.println(WiFi.softAPIP());
  Serial.println("[ESP32] Waiting for data from Pico...");
}

void loop() {
  if (picoSerial.available()) {
    Serial.println("[ESP32] Data detected on UART!");

    int payloadSize = picoSerial.parseInt();
    picoSerial.readStringUntil('\n');

    Serial.print("[ESP32] Parsed payload size: ");
    Serial.println(payloadSize);

    if (payloadSize > 0 && payloadSize <= MAX_PAYLOAD) {
      String msg = picoSerial.readStringUntil('\n');
      msg.trim();

      Serial.print("[ESP32] Message received from Pico: ");
      Serial.println(msg);

      if (client.connect("192.168.4.2", 8080)) {
        client.println(msg);
        client.stop();
        Serial.println("[ESP32] Successfully sent to Mac!");
      } else {
        Serial.println("[ESP32] ERROR: Failed to connect to Mac at 192.168.4.2:8080");
      }
    } else {
      Serial.print("[ESP32] WARNING: Invalid payload size received: ");
      Serial.println(payloadSize);
    }
  }
}
