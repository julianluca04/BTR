#include <bluefruit.h>

BLEUart bleuart;
volatile bool g_connected = false;
String rxBuffer = "";

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
  digitalWrite(LED_RED, HIGH);
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

void loop() {
  while (Serial1.available()) {
    char c = Serial1.read();
    if (c == '\n') {
      rxBuffer.trim();
      if (rxBuffer.startsWith("PING_")) {
        digitalWrite(LED_RED, LOW); delay(30); digitalWrite(LED_RED, HIGH);
        if (g_connected) {
          String reply = "GOT:" + rxBuffer + "\n";
          bleuart.write(reply.c_str(), reply.length());
        }
      }
      rxBuffer = "";
    } else {
      rxBuffer += c;
    }
  }
}