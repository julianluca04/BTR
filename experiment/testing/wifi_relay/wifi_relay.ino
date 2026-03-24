#include <WiFi.h>

HardwareSerial picoSerial(1);
const int RX_PIN = 20;  // XIAO D7, connects to Pico GP0 (TX)
const int TX_PIN = 21;  // XIAO D6, connects to Pico GP1 (RX)

const char* AP_SSID = "esp32_test";
const char* AP_PASS = "esp32test";

WiFiClient client;

#define MAX_PAYLOAD 1024

void setup() {
  Serial.begin(115200);
  delay(2000);
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
    Serial.println("----------------------------------");
    Serial.println("[ESP32] *** DATA RECEIVED FROM PICO ***");

    int payloadSize = picoSerial.parseInt();
    picoSerial.readStringUntil('\n');

    Serial.print("[ESP32] Payload size: ");
    Serial.println(payloadSize);

    if (payloadSize > 0 && payloadSize <= MAX_PAYLOAD) {
      String msg = picoSerial.readStringUntil('\n');
      msg.trim();

      Serial.print("[ESP32] Message: ");
      Serial.println(msg);
      Serial.print("[ESP32] Message length: ");
      Serial.println(msg.length());

      Serial.println("[ESP32] Forwarding to Mac...");
      if (client.connect("192.168.4.2", 8080)) {
        client.println(msg);
        client.stop();
        Serial.println("[ESP32] *** SUCCESSFULLY SENT TO MAC ***");
      } else {
        Serial.println("[ESP32] ERROR: Could not reach Mac at 192.168.4.2:8080");
        Serial.println("[ESP32] Check Mac is on esp32_test WiFi and receiver.py is running");
      }
    } else {
      Serial.print("[ESP32] WARNING: Invalid payload size: ");
      Serial.println(payloadSize);
    }
    Serial.println("----------------------------------");
  }
}