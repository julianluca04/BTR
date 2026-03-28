#include <WiFi.h>
#include <esp_wifi.h>

HardwareSerial picoSerial(1);
const int RX_PIN = 20;
const int TX_PIN = 21;

const char* AP_SSID = "esp32_test";
const char* AP_PASS = "esp32test";
const char* MAC_IP  = "192.168.4.2";
const int   MAC_PORT = 8080;

const int WINDOW = 64;

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
}

void loop() {
  if (!picoSerial.available()) return;

  String cmd = picoSerial.readStringUntil('\n');
  cmd.trim();

  if (cmd == "WIFI_OFF") {
    esp_wifi_stop();
    picoSerial.println("WIFI_OFF_OK");
    return;
  }
  if (cmd == "WIFI_ON") {
    esp_wifi_start();
    WiFi.softAP(AP_SSID, AP_PASS);
    picoSerial.println("WIFI_ON_OK");
    return;
  }
  if (cmd == "SLEEP") {
    picoSerial.println("SLEEP_OK");
    delay(100);
    esp_deep_sleep_start();
    return;
  }

  long payloadSize = cmd.toInt();
  if (payloadSize <= 0) {
    picoSerial.println("FAIL");
    return;
  }

  Serial.print("[ESP32] Expecting ");
  Serial.print(payloadSize);
  Serial.println("B");

  WiFiClient client;
  if (!client.connect(MAC_IP, MAC_PORT)) {
    Serial.println("[ESP32] ERROR: Could not reach Mac.");
    picoSerial.println("FAIL");
    return;
  }

  client.print("SIZE:" + String(payloadSize) + "\n");

  long forwarded = 0;
  int windowCount = 0;
  uint8_t windowBuf[WINDOW];  // accumulate a full window before writing to TCP
  unsigned long lastByte = millis();

  while (forwarded < payloadSize) {
    if (picoSerial.available()) {
      windowBuf[windowCount] = picoSerial.read();
      windowCount++;
      forwarded++;
      lastByte = millis();

      if (windowCount >= WINDOW || forwarded == payloadSize) {
        // Write the whole window to TCP in one call
        client.write(windowBuf, windowCount);

        // Only signal RDY if more bytes remain
        if (forwarded < payloadSize) {
          picoSerial.println("RDY");
        }
        windowCount = 0;
      }
    } else if (millis() - lastByte > 10000) {
      Serial.println("[ESP32] Timeout waiting for bytes.");
      break;
    }
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