#include <WiFi.h>

const char* AP_SSID = "esp32_test";
const char* AP_PASS = "esp32test";

WiFiServer server(5000);
const size_t CHUNK_SIZE = 1024;

// Example file content
const char fileData[] =
"This file is transferred over TCP.\n"
"It supports automatic chunking.\n"
"Larger files will also work.\n";

const size_t fileSize = sizeof(fileData) - 1;

void setup() {
  Serial.begin(115200);
  delay(2000);

  WiFi.mode(WIFI_AP);
  WiFi.softAP(AP_SSID, AP_PASS);

  Serial.println("Access Point started");
  Serial.print("ESP32 IP: ");
  Serial.println(WiFi.softAPIP());

  server.begin();
}

void loop() {
  WiFiClient client = server.available();

  if (client) {
    Serial.println("Client connected");

    // Send file size first (8 bytes)
    client.write((uint8_t*)&fileSize, sizeof(fileSize));

    size_t offset = 0;

    while (offset < fileSize) {
      size_t len = min(CHUNK_SIZE, fileSize - offset);
      client.write((uint8_t*)fileData + offset, len);
      offset += len;
    }

    Serial.println("File sent");
    client.stop();
  }
}