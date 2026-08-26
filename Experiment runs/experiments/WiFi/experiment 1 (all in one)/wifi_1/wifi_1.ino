#include <WiFi.h>
#include <esp_wifi.h>

HardwareSerial picoSerial(1);
const int RX_PIN = 20;
const int TX_PIN = 21;

const char* AP_SSID  = "esp32_test";
const char* AP_PASS  = "esp32test";
const char* MAC_IP   = "192.168.4.2";
const int   MAC_PORT = 8080;

const size_t TCP_CHUNK    = 1460;  // Standard TCP MSS
const size_t MAX_PAYLOAD  = 524288; // 512 KiB limit

void setup() {
  Serial.begin(115200);
  delay(2000);
  picoSerial.begin(115200, SERIAL_8N1, RX_PIN, TX_PIN);

  WiFi.mode(WIFI_AP);
  WiFi.softAP(AP_SSID, AP_PASS);
  WiFi.setTxPower(WIFI_POWER_8_5dBm);

  Serial.print("[ESP32] AP IP: ");
  Serial.println(WiFi.softAPIP());
  Serial.print("[ESP32] Free heap: ");
  Serial.println(ESP.getFreeHeap());
  Serial.println("[ESP32] Ready.");

  picoSerial.println("BOOT");
}

void loop() {
  if (!picoSerial.available()) {
    delay(10);
    return;
  }

  String cmd = picoSerial.readStringUntil('\n');
  cmd.trim();

  // Only restart at end of complete run
  if (cmd == "DONE") {
    Serial.println("[ESP32] Run complete, restarting...");
    picoSerial.flush();
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

  if (payloadSize > MAX_PAYLOAD) {
    Serial.print("[ESP32] Size too large: ");
    Serial.println(payloadSize);
    picoSerial.println("FAIL");
    return;
  }

  size_t free_heap = ESP.getFreeHeap();
  Serial.print("[ESP32] Free heap: ");
  Serial.print(free_heap);
  Serial.print("B, requesting ");
  Serial.print(payloadSize);
  Serial.println("B");

  // ── BUFFER ENTIRE PAYLOAD FROM UART INTO RAM ──
  uint8_t* buffer = (uint8_t*) malloc(payloadSize);
  if (!buffer) {
    Serial.print("[ESP32] malloc failed (heap: ");
    Serial.print(free_heap);
    Serial.print("B, needed: ");
    Serial.print(payloadSize);
    Serial.println("B)");
    picoSerial.println("FAIL");
    // Drain leftover UART bytes
    delay(500);
    while (picoSerial.available()) picoSerial.read();
    return;
  }

  Serial.print("[ESP32] Buffering ");
  Serial.print(payloadSize);
  Serial.println("B from UART...");

  // Read entire payload with generous timeout
  unsigned long uart_timeout = 90000 + (payloadSize / 10);
  size_t bytes_read = 0;
  unsigned long start_time = millis();
  unsigned long deadline = start_time + uart_timeout;
  
  while (bytes_read < payloadSize && millis() < deadline) {
    if (picoSerial.available()) {
      buffer[bytes_read++] = picoSerial.read();
    }
  }

  if (bytes_read != payloadSize) {
    Serial.print("[ESP32] UART timeout after ");
    Serial.print(millis() - start_time);
    Serial.print("ms: ");
    Serial.print(bytes_read);
    Serial.print("/");
    Serial.print(payloadSize);
    Serial.println("B");
    free(buffer);
    picoSerial.println("FAIL");
    return;
  }

  unsigned long uart_time = millis() - start_time;
  Serial.print("[ESP32] Buffered ");
  Serial.print(payloadSize);
  Serial.print("B in ");
  Serial.print(uart_time);
  Serial.println("ms");

  // ── CONNECT TO MAC VIA TCP ──
  WiFiClient client;
  client.setNoDelay(true);
  
  unsigned long connect_start = millis();
  if (!client.connect(MAC_IP, MAC_PORT)) {
    Serial.println("[ESP32] ERROR: Could not connect to Mac.");
    free(buffer);
    picoSerial.println("FAIL");
    return;
  }

  Serial.print("[ESP32] Connected in ");
  Serial.print(millis() - connect_start);
  Serial.println("ms");

  // ── SEND SIZE HEADER ──
  char header[32];
  snprintf(header, sizeof(header), "SIZE:%ld\n", payloadSize);
  client.write((uint8_t*)header, strlen(header));
  client.flush();

  // ── SEND PAYLOAD IN TCP CHUNKS ──
  Serial.print("[ESP32] Sending ");
  Serial.print(payloadSize);
  Serial.println("B...");

  size_t bytes_sent = 0;
  unsigned long tx_start = millis();
  
  while (bytes_sent < payloadSize) {
    size_t chunk_size = (payloadSize - bytes_sent < TCP_CHUNK) 
                        ? payloadSize - bytes_sent 
                        : TCP_CHUNK;
    
    size_t written = client.write(buffer + bytes_sent, chunk_size);
    
    if (written > 0) {
      bytes_sent += written;
    } else {
      delay(1);
    }
    
    if (bytes_sent % (TCP_CHUNK * 10) == 0) {
      client.flush();
    }
  }
  
  client.flush();
  unsigned long tx_time = millis() - tx_start;

  client.stop();
  free(buffer);

  Serial.print("[ESP32] Sent ");
  Serial.print(payloadSize);
  Serial.print("B in ");
  Serial.print(tx_time);
  Serial.print("ms (");
  Serial.print(payloadSize * 1000 / tx_time / 1024);
  Serial.println(" KB/s)");
  
  Serial.print("[ESP32] Heap after: ");
  Serial.println(ESP.getFreeHeap());
  
  picoSerial.println("OK");
  delay(100);
}