#include <bluefruit.h>

BLEUart bleuart;
volatile bool g_connected = false;
#define UART_CHUNK 244  // Matching maximum BLE notification payload

void connect_callback(uint16_t conn_handle) { g_connected = true; }
void disconnect_callback(uint16_t conn_handle, uint8_t reason) { g_connected = false; }

void setup() {
  // Maximize bandwidth for high-throughput experiment
  Bluefruit.configPrphBandwidth(BANDWIDTH_MAX);
  Bluefruit.begin();
  Bluefruit.setTxPower(4);
  Bluefruit.Periph.setConnectCallback(connect_callback);
  Bluefruit.Periph.setDisconnectCallback(disconnect_callback);
  
  bleuart.begin();
  Serial1.begin(115200); // Connection to Pico
}

void loop() {
  // Only process if a Mac is connected via BLE
  if (!g_connected) return;

  // 1. Wait for Pico to send the payload size metadata
  if (!Serial1.available()) return;
  String line = Serial1.readStringUntil('\n');
  line.trim();
  if (line.length() == 0) return;
  long size = line.toInt();
  if (size <= 0) return;

  // 2. Send SIZE header via BLE so the Mac script knows what to expect
  char hdr[32];
  snprintf(hdr, sizeof(hdr), "SIZE:%ld\n", size);
  bleuart.write(hdr, strlen(hdr));

  // 3. Signal Pico: Metadata processed, ready for the FIRST data chunk
  Serial1.println("READY_TO_RECV");

  uint32_t total_sent = 0;
  uint8_t buf[UART_CHUNK];

  while (total_sent < (uint32_t)size) {
    int to_read = min((int)UART_CHUNK, (int)(size - total_sent));
    int got = 0;
    
    // Blocking read for exactly 'to_read' bytes
    uint32_t timeout = millis() + 5000;
    while (got < to_read && millis() < timeout) {
      if (Serial1.available()) {
        buf[got++] = Serial1.read();
      }
      if (!g_connected) return; 
    }

    if (got > 0) {
      // Send the chunk over BLE
      bleuart.write(buf, got);
      total_sent += got;
      
      // 4. Pace the Pico: Wait for BLE stack buffer to clear
      while(bleuart.availableForWrite() < UART_CHUNK) {
        yield();
      }
      // Signal Pico for "N"ext chunk
      Serial1.println("N");
    } else {
      break; // UART timeout
    }
  }
}