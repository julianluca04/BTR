// =============================================================
// EXPERIMENT 2 — 20-byte chunked relay (ESP32 WiFi module)
//
// Buffers incoming UART bytes from Pico. When the buffer reaches
// CHUNK_SIZE (20 bytes) OR the message ends, the chunk is sent
// over WiFi to the Mac as a single TCP write.
//
// 20 bytes chosen to match classic BLE ATT MTU payload size.
// Adjust CHUNK_SIZE to experiment with other values (e.g. 64, 128).
// =============================================================

#include <WiFi.h>

HardwareSerial picoSerial(1);
const int RX_PIN = 20;
const int TX_PIN = 21;

const char* AP_SSID  = "esp32_test";
const char* AP_PASS  = "esp32test";
const char* MAC_IP   = "192.168.4.2";
const int   MAC_PORT = 8080;

#define CHUNK_SIZE   20    // bytes per TCP write
#define MAX_PAYLOAD  1024
#define RX_TIMEOUT_MS 10000

void setup() {
  Serial.begin(115200);
  delay(2000);
  picoSerial.begin(115200, SERIAL_8N1, RX_PIN, TX_PIN);

  WiFi.mode(WIFI_AP);
  WiFi.softAP(AP_SSID, AP_PASS);

  Serial.println("[ESP32 EXP2] AP started");
  Serial.print("[ESP32 EXP2] IP: ");
  Serial.println(WiFi.softAPIP());
  Serial.print("[ESP32 EXP2] Chunked relay ready (chunk size = ");
  Serial.print(CHUNK_SIZE);
  Serial.println(" bytes).");
}

void loop() {
  if (!picoSerial.available()) return;

  // --- Read size header ---
  int payloadSize = picoSerial.parseInt();
  picoSerial.readStringUntil('\n');

  if (payloadSize <= 0 || payloadSize > MAX_PAYLOAD) {
    Serial.print("[ESP32 EXP2] Invalid size: ");
    Serial.println(payloadSize);
    return;
  }

  Serial.print("[ESP32 EXP2] Expecting ");
  Serial.print(payloadSize);
  Serial.print(" bytes in ");
  Serial.print(CHUNK_SIZE);
  Serial.println("-byte chunks...");

  WiFiClient client;
  client.setNoDelay(true);
  if (!client.connect(MAC_IP, MAC_PORT)) {
    Serial.println("[ESP32 EXP2] ERROR: Cannot connect to Mac.");
    return;
  }

  // Forward size header to Mac
  client.println(payloadSize);

  // --- Read bytes into chunk buffer, flush every CHUNK_SIZE bytes ---
  uint8_t chunkBuf[CHUNK_SIZE];
  int bufPos        = 0;
  int received      = 0;
  int chunksSent    = 0;
  unsigned long deadline = millis() + RX_TIMEOUT_MS;

  while (received < payloadSize && millis() < deadline) {
    if (picoSerial.available()) {
      uint8_t b = picoSerial.read();
      chunkBuf[bufPos++] = b;
      received++;

      if (bufPos == CHUNK_SIZE) {
        // Chunk is full → send it
        client.write(chunkBuf, CHUNK_SIZE);
        chunksSent++;
        bufPos = 0;
        Serial.print("C"); // one dot per chunk sent
      }
    }
  }

  // Send any remaining bytes (last partial chunk)
  if (bufPos > 0) {
    client.write(chunkBuf, bufPos);
    chunksSent++;
    Serial.print("c"); // lowercase = partial chunk
  }

  client.write('\n'); // end-of-message marker
  client.stop();

  Serial.println();
  Serial.print("[ESP32 EXP2] Done. ");
  Serial.print(received);
  Serial.print(" bytes in ");
  Serial.print(chunksSent);
  Serial.println(" chunks.");
  Serial.println("--------------------------------------------------");
}
