#include <WiFi.h>
#include <esp_wifi.h>
#include <lwip/ip4_addr.h>

HardwareSerial picoSerial(1);
const int RX_PIN = 20;
const int TX_PIN = 21;

const char* AP_SSID  = "esp32_test";
const char* AP_PASS  = "esp32test";
const int   MAC_PORT = 8080;

#define CHUNK_SIZE    1460
#define TCP_WRITE_SIZE 512

// Minimum write timeout (ms) regardless of payload size.
// Scales up by 1 second per 4096 bytes for large payloads.
#define WRITE_TIMEOUT_BASE_MS   15000UL
#define WRITE_TIMEOUT_PER_4K_MS  1000UL

// UART idle timeout: how long to wait for the next byte from the Pico.
// 5000 ms gives enough headroom for the Pico inter-chunk delay + UART TX time.
#define UART_BYTE_TIMEOUT_MS    5000UL

static uint8_t chunkBuf[CHUNK_SIZE];
static String  clientIP = "";
static bool    apReady  = false;

void onWifiEvent(WiFiEvent_t event, WiFiEventInfo_t info) {
  if (event == ARDUINO_EVENT_WIFI_AP_STAIPASSIGNED) {
    ip4_addr_t addr;
    addr.addr = info.wifi_ap_staipassigned.ip.addr;
    clientIP  = String(ip4addr_ntoa(&addr));
    apReady   = true;
    Serial.println("[ESP32] Client assigned IP: " + clientIP);
  } else if (event == ARDUINO_EVENT_WIFI_AP_STADISCONNECTED) {
    Serial.println("[ESP32] Client disconnected.");
    clientIP = "";
    apReady  = false;
  }
}

// Write all bytes without flush() inside the loop.
// Timeout scales with payload size so large transfers don't expire mid-stream.
bool writeAll(WiFiClient &client, const uint8_t *buf, int len, unsigned long timeoutMs) {
  int sent = 0;
  unsigned long deadline = millis() + timeoutMs;
  while (sent < len) {
    if (millis() > deadline) {
      Serial.println("[ESP32] writeAll timeout");
      return false;
    }
    if (!client.connected()) {
      Serial.println("[ESP32] writeAll: client disconnected");
      return false;
    }
    int toWrite = min(len - sent, TCP_WRITE_SIZE);
    size_t written = client.write(buf + sent, toWrite);
    if (written == 0) {
      delay(1);
      continue;
    }
    sent += (int)written;
  }
  return true;
}

// Compute a write timeout that scales with payload size.
unsigned long writeTimeoutMs(long payloadSize) {
  unsigned long extra = ((unsigned long)payloadSize / 4096UL) * WRITE_TIMEOUT_PER_4K_MS;
  return WRITE_TIMEOUT_BASE_MS + extra;
}

void setup() {
  Serial.begin(115200);
  delay(2000);
  picoSerial.begin(115200, SERIAL_8N1, RX_PIN, TX_PIN, false, 32768);

  WiFi.onEvent(onWifiEvent);
  WiFi.mode(WIFI_AP);
  WiFi.softAP(AP_SSID, AP_PASS);
  WiFi.setTxPower(WIFI_POWER_8_5dBm);

  Serial.print("[ESP32] AP IP: ");
  Serial.println(WiFi.softAPIP());
  Serial.println("[ESP32] Waiting for Mac to connect to AP...");

  while (!apReady) delay(50);

  Serial.println("[ESP32] Mac connected. Signalling Pico to boot.");
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

  unsigned long txTimeout = writeTimeoutMs(payloadSize);
  Serial.print("[ESP32] Expecting ");
  Serial.print(payloadSize);
  Serial.print("B  heap=");
  Serial.print(ESP.getFreeHeap());
  Serial.print("  writeTimeout=");
  Serial.print(txTimeout);
  Serial.println("ms");

  if (!apReady) {
    Serial.println("[ESP32] Waiting for client IP...");
    unsigned long t = millis();
    while (!apReady && millis() - t < 5000) delay(50);
    if (!apReady) {
      Serial.println("[ESP32] No client IP — sending FAIL");
      picoSerial.println("FAIL");
      return;
    }
  }

  Serial.println("[ESP32] Connecting to " + clientIP + ":" + String(MAC_PORT));

  WiFiClient client;
  client.setNoDelay(true);
  if (!client.connect(clientIP.c_str(), MAC_PORT)) {
    Serial.println("[ESP32] ERROR: connect() FAILED");
    picoSerial.println("FAIL");
    return;
  }
  Serial.println("[ESP32] TCP connected.");

  client.print("SIZE:" + String(payloadSize) + "\n");

  long          forwarded  = 0;
  int           chunkCount = 0;
  unsigned long lastByte   = millis();
  bool          tcpFailed  = false;

  while (forwarded < payloadSize) {
    if (millis() - lastByte > UART_BYTE_TIMEOUT_MS) {
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

    if (chunkCount >= CHUNK_SIZE || forwarded == payloadSize) {
      if (!writeAll(client, chunkBuf, chunkCount, txTimeout)) {
        Serial.print("[ESP32] TCP write failed at ");
        Serial.print(forwarded);
        Serial.print("/");
        Serial.println(payloadSize);
        tcpFailed  = true;
        chunkCount = 0;
        break;
      }
      Serial.print("[ESP32] TCP wrote ");
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

  if (!tcpFailed && forwarded == payloadSize) {
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
