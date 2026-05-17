#include <WiFi.h>
#include <esp_wifi.h>

HardwareSerial picoSerial(1);
const int RX_PIN = 20;
const int TX_PIN = 21;

const char* AP_SSID = "esp32_test";
const char* AP_PASS = "esp32test";
const char* MAC_IP  = "192.168.4.2";
const int   MAC_PORT = 8080;

void setup() {
  Serial.begin(115200);
  delay(2000);
  picoSerial.begin(115200, SERIAL_8N1, RX_PIN, TX_PIN);

  WiFi.mode(WIFI_AP);
  WiFi.softAP(AP_SSID, AP_PASS);
  WiFi.setTxPower(WIFI_POWER_8_5dBm);

  Serial.print("[ESP32] AP IP: ");
  Serial.println(WiFi.softAPIP());
  Serial.println("[ESP32] Ready.");

  picoSerial.println("BOOT");
}

void loop() {
  if (!picoSerial.available()) return;

  String cmd = picoSerial.readStringUntil('\n');
  cmd.trim();

  if (cmd == "DONE") {
    Serial.println("[ESP32] Run complete, restarting...");
    delay(200);
    ESP.restart();
    return;
  }

  long payloadSize = cmd.toInt();
  if (payloadSize <= 0) {
    if (cmd.length() > 0)
      Serial.println("[ESP32] Ignoring: '" + cmd + "'");
    return;
  }

  Serial.print("[ESP32] Expecting ");
  Serial.print(payloadSize);
  Serial.println("B");

  WiFiClient client;
  client.setNoDelay(true);  // disable Nagle — force immediate send per write()
  if (!client.connect(MAC_IP, MAC_PORT)) {
    Serial.println("[ESP32] ERROR: Could not reach Mac.");
    picoSerial.println("FAIL");
    return;
  }

  client.print("SIZE:" + String(payloadSize) + "\n");

  long forwarded = 0;
  unsigned long lastByte = millis();

  while (forwarded < payloadSize) {
    if (millis() - lastByte > 10000) {
      Serial.println("[ESP32] Timeout waiting for byte.");
      break;
    }

    if (!picoSerial.available()) continue;

    uint8_t b = picoSerial.read();
    client.write(&b, 1);
    forwarded++;
    lastByte = millis();

    // ACK every single byte so Pico never has more than 1 byte in flight
    picoSerial.println("RDY");
  }

  client.flush();
  delay(20);
  client.stop();

  if (forwarded == payloadSize) {
    Serial.print("[ESP32] Done ");
    Serial.println(payloadSize);
    picoSerial.println("OK");
  } else {
    Serial.print("[ESP32] INCOMPLETE ");
    Serial.print(forwarded);
    Serial.print("/");
    Serial.println(payloadSize);
    picoSerial.println("FAIL");
  }
}