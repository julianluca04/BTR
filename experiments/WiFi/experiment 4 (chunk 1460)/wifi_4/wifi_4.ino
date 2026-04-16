#include <WiFi.h>
#include <esp_wifi.h>

HardwareSerial picoSerial(1);
const int RX_PIN = 20;
const int TX_PIN = 21;

const char* AP_SSID  = "esp32_test";
const char* AP_PASS  = "esp32test";
const char* MAC_IP   = "192.168.4.2";
const int   MAC_PORT = 8080;

// 1460 bytes = TCP MSS (Ethernet MTU 1500 - IP header 20 - TCP header 20)
// One UART chunk = one TCP segment — no IP fragmentation.
#define CHUNK_SIZE 1460

static uint8_t chunkBuf[CHUNK_SIZE];

void setup() {
  Serial.begin(115200);
  delay(2000);
  // 32 KB RX buffer: at 115200 baud (11520 B/s), 32768 B = ~2.84 s of headroom.
  // TCP write rate (~11453 B/s) is fractionally below UART rate (11520 B/s), so
  // cumulative lag (~2.8 KB after a full 524288 B transfer) plus brief WiFi stalls
  // overflowed the previous 16 KB buffer. 32 KB absorbs both.
  picoSerial.begin(115200, SERIAL_8N1, RX_PIN, TX_PIN, false, 32768);

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
  if (payloadSize <= 0) return;

  Serial.print("[ESP32] Expecting ");
  Serial.print(payloadSize);
  Serial.println("B");

  WiFiClient client;
  if (!client.connect(MAC_IP, MAC_PORT)) {
    Serial.println("[ESP32] ERROR: Could not reach Mac.");
    picoSerial.println("FAIL");
    return;
  }

  // Send SIZE header so Mac knows how many bytes to expect
  client.print("SIZE:" + String(payloadSize) + "\n");

  long     forwarded  = 0;
  int      chunkCount = 0;
  unsigned long lastByte = millis();

  // Timeout: 60 s base + actual UART transfer time (payloadSize bytes at 115200 baud,
  // 10 bits/byte → payloadSize * 10 / 115 ms), doubled for WiFi jitter headroom.
  // 60 s minimum gives the UART hardware buffer time to drain after a WiFi stall.
  unsigned long timeout_ms = 60000UL + (unsigned long)payloadSize * 20UL / 115UL;

  while (forwarded < payloadSize) {
    if (millis() - lastByte > timeout_ms) {
      Serial.println("[ESP32] Timeout waiting for UART bytes.");
      break;
    }

    // Read all available bytes at once — prevents UART RX buffer overflow
    // when client.write() briefly stalls the loop.
    int avail = picoSerial.available();
    if (avail > 0) {
      int toRead = min(avail, CHUNK_SIZE - chunkCount);
      for (int j = 0; j < toRead; j++) {
        chunkBuf[chunkCount++] = picoSerial.read();
      }
      forwarded += toRead;
      lastByte = millis();

      // Flush to TCP when chunk is full or payload is complete
      if (chunkCount >= CHUNK_SIZE || forwarded == payloadSize) {
        client.write(chunkBuf, chunkCount);
        chunkCount = 0;
      }
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
