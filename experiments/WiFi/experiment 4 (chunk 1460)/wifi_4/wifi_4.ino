#include <WiFi.h>
#include <esp_wifi.h>
#include <lwip/ip4_addr.h>

HardwareSerial picoSerial(1);
const int RX_PIN = 20;
const int TX_PIN = 21;

const char* AP_SSID  = "esp32_test";
const char* AP_PASS  = "esp32test";
const int   MAC_PORT = 8080;

// 1460 = TCP MSS (Ethernet MTU 1500 - IP header 20 - TCP header 20)
#define CHUNK_SIZE 1460

static uint8_t chunkBuf[CHUNK_SIZE];
static String  clientIP = "";

void onWifiEvent(WiFiEvent_t event, WiFiEventInfo_t info) {
  if (event == ARDUINO_EVENT_WIFI_AP_STAIPASSIGNED) {
    ip4_addr_t addr;
    addr.addr = info.wifi_ap_staipassigned.ip.addr;
    clientIP = String(ip4addr_ntoa(&addr));
    Serial.println("[ESP32] Client assigned IP: " + clientIP);
  } else if (event == ARDUINO_EVENT_WIFI_AP_STADISCONNECTED) {
    Serial.println("[ESP32] Client disconnected.");
    clientIP = "";
  }
}

void setup() {
  Serial.begin(115200);
  delay(2000);
  // 32 KB RX buffer: at 115200 baud (11520 B/s), 32768 B ≈ 2.84 s of headroom.
  picoSerial.begin(115200, SERIAL_8N1, RX_PIN, TX_PIN, false, 32768);

  WiFi.onEvent(onWifiEvent);
  WiFi.mode(WIFI_AP);
  WiFi.softAP(AP_SSID, AP_PASS);
  WiFi.setTxPower(WIFI_POWER_8_5dBm);

  Serial.print("[ESP32] AP IP: ");
  Serial.println(WiFi.softAPIP());
  Serial.println("[ESP32] Ready. Waiting for Mac to connect...");

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
  Serial.print("B  heap=");
  Serial.println(ESP.getFreeHeap());

  String targetIP = clientIP.length() > 0 ? clientIP : "192.168.4.2";
  Serial.println("[ESP32] Connecting to " + targetIP + ":" + String(MAC_PORT));

  WiFiClient client;
  if (!client.connect(targetIP.c_str(), MAC_PORT)) {
    Serial.println("[ESP32] ERROR: connect() FAILED to " + targetIP);
    picoSerial.println("FAIL");
    return;
  }
  client.setNoDelay(true);
  Serial.println("[ESP32] TCP connected.");

  client.print("SIZE:" + String(payloadSize) + "\n");

  long          forwarded   = 0;
  int           chunkCount  = 0;
  unsigned long lastByte    = millis();

  // Per-byte idle timeout: must comfortably cover the Pico's INTER_CHUNK_DELAY_MS
  // (10 ms) plus UART clock time for one 1460-byte chunk (~127 ms) plus WiFi
  // stack latency.  500 ms is safe; 10 s was the original wifi_3 value.
  const unsigned long BYTE_TIMEOUT_MS = 2000;

  while (forwarded < payloadSize) {
    if (millis() - lastByte > BYTE_TIMEOUT_MS) {
      Serial.print("[ESP32] UART timeout after ");
      Serial.print(forwarded);
      Serial.print("/");
      Serial.println(payloadSize);
      break;
    }

    if (!picoSerial.available()) continue;

    if (forwarded == 0) {
      Serial.print("[ESP32] First byte arrived, avail=");
      Serial.println(picoSerial.available());
    }

    chunkBuf[chunkCount++] = picoSerial.read();
    forwarded++;
    lastByte = millis();

    // Flush to TCP when the 1460-byte chunk is full, or the payload is complete.
    if (chunkCount >= CHUNK_SIZE || forwarded == payloadSize) {
      int written = client.write(chunkBuf, chunkCount);
      Serial.print("[ESP32] TCP wrote ");
      Serial.print(written);
      Serial.print("/");
      Serial.print(chunkCount);
      Serial.print("B  total=");
      Serial.print(forwarded);
      Serial.print("/");
      Serial.println(payloadSize);
      chunkCount = 0;
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
