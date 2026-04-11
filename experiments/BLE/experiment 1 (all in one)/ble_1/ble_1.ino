#include <bluefruit.h>

BLEUart bleuart;
volatile bool g_connected = false;

void connect_callback(uint16_t conn_handle) {
  (void) conn_handle;
  g_connected = true;
}

void disconnect_callback(uint16_t conn_handle, uint8_t reason) {
  (void) conn_handle;
  (void) reason;
  g_connected = false;
}

void setup() {
  pinMode(LED_RED, OUTPUT);
  Serial1.begin(115200);
  delay(100);

  Bluefruit.begin();
  Bluefruit.setTxPower(4);
  Bluefruit.Periph.setConnectCallback(connect_callback);
  Bluefruit.Periph.setDisconnectCallback(disconnect_callback);

  bleuart.begin();

  Bluefruit.Advertising.addFlags(BLE_GAP_ADV_FLAGS_LE_ONLY_GENERAL_DISC_MODE);
  Bluefruit.Advertising.addTxPower();
  Bluefruit.Advertising.addService(bleuart);
  Bluefruit.ScanResponse.addName();
  Bluefruit.Advertising.restartOnDisconnect(true);
  Bluefruit.Advertising.start(0);
}

// Read exact number of bytes from UART into buf
int readExact(uint8_t* buf, int len, int timeoutMs) {
  int got = 0;
  unsigned long start = millis();
  while (got < len && millis() - start < timeoutMs) {
    if (Serial1.available()) buf[got++] = Serial1.read();
  }
  return got;
}

void loop() {
  // Slow blink = waiting for connection
  if (!g_connected || !bleuart.notifyEnabled()) {
    digitalWrite(LED_RED, LOW);  delay(100);
    digitalWrite(LED_RED, HIGH); delay(900);
    return;
  }

  // Wait for size header line from Pico e.g. "1024\n"
  if (!Serial1.available()) return;

  String line = Serial1.readStringUntil('\n');
  line.trim();
  int size = line.toInt();
  if (size <= 0) return;

  // Fast blink = receiving payload
  digitalWrite(LED_RED, LOW);  delay(30);
  digitalWrite(LED_RED, HIGH); delay(30);

  // Allocate buffer and read exact bytes
  uint8_t* buf = (uint8_t*) malloc(size);
  if (!buf) {
    bleuart.println("FAIL");
    return;
  }

  int got = readExact(buf, size, 10000 + size);
  if (got != size) {
    bleuart.println("FAIL");
    free(buf);
    return;
  }

  // Send SIZE header then full payload over BLE
  bleuart.print("SIZE:");
  bleuart.println(size);

  // Send in 180-byte BLE chunks
  int remaining = size;
  int offset    = 0;
  while (remaining > 0) {
    int chunk = remaining > 180 ? 180 : remaining;
    bleuart.write(buf + offset, chunk);
    offset    += chunk;
    remaining -= chunk;
  }

  free(buf);

  // Fast blink = done sending
  for (int i = 0; i < 3; i++) {
    digitalWrite(LED_RED, LOW);  delay(30);
    digitalWrite(LED_RED, HIGH); delay(30);
  }
}
