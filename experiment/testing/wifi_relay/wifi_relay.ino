#include <WiFi.h>

HardwareSerial picoSerial(1);
const int RX_PIN = 20;
const int TX_PIN = 21;

const char* AP_SSID = "esp32_test";
const char* AP_PASS = "esp32test";
const char* MAC_IP  = "192.168.4.2";
const int   MAC_PORT = 8080;

const int MAX_PAYLOAD = 1048576;

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

  int payloadSize = picoSerial.parseInt();
  picoSerial.readStringUntil('\n');

  if (payloadSize <= 0 || payloadSize > MAX_PAYLOAD) {
    Serial.print("[ESP32] Rejected size: ");
    Serial.println(payloadSize);
    picoSerial.println("FAIL");
    return;
  }

  Serial.print("[ESP32] Expecting ");
  Serial.print(payloadSize);
  Serial.println("B");

  // Try malloc — signal FAIL to Pico if heap too small
  uint8_t* buf = (uint8_t*)malloc(payloadSize);
  if (!buf) {
    Serial.print("[ESP32] MALLOC_FAIL for ");
    Serial.println(payloadSize);
    picoSerial.println("FAIL");  // Pico will forward to Python

    // Drain incoming bytes so Pico doesn't get stuck
    int drained = 0;
    unsigned long t = millis();
    while (drained < payloadSize && millis() - t < 20000) {
      if (picoSerial.available()) { picoSerial.read(); drained++; }
    }
    picoSerial.readStringUntil('\n');
    return;
  }

  // Read exactly payloadSize bytes
  int received = 0;
  unsigned long t = millis();
  while (received < payloadSize && millis() - t < 20000) {
    if (picoSerial.available()) {
      buf[received++] = picoSerial.read();
    }
  }
  picoSerial.readStringUntil('\n');

  if (received != payloadSize) {
    Serial.print("[ESP32] INCOMPLETE: got ");
    Serial.print(received);
    Serial.println("B");
    picoSerial.println("FAIL");
    free(buf);
    return;
  }

  // Forward to Mac
  WiFiClient client;
  if (client.connect(MAC_IP, MAC_PORT)) {
    String header = "SIZE:" + String(received) + "\n";
    client.print(header);
    client.write(buf, received);
    client.stop();
    picoSerial.println("OK");
    Serial.print("[ESP32] Sent ");
    Serial.print(received);
    Serial.println("B OK.");
  } else {
    Serial.println("[ESP32] ERROR: Could not reach Mac.");
    picoSerial.println("FAIL");
  }

  free(buf);
}