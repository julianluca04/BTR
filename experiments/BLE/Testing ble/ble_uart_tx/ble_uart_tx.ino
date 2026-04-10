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

void loop() {
  digitalWrite(LED_RED, LOW);
  delay(500);
  digitalWrite(LED_RED, HIGH);
  delay(500);

  if (Serial1.available()) {
    String msg = Serial1.readStringUntil('\n');
    msg.trim();

    // Only process if it looks like a real PING message
    if (msg.startsWith("PING_")) {
      // Fast blink to confirm valid UART received
      for (int i = 0; i < 5; i++) {
        digitalWrite(LED_RED, LOW);  delay(30);
        digitalWrite(LED_RED, HIGH); delay(30);
      }

      // Forward over BLE if connected
      if (g_connected) {
        String reply = "GOT:" + msg + "\n";
        bleuart.write(reply.c_str(), reply.length());
      }
    }
  }
}
