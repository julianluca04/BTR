// ble_uart_tx.ino
// nRF52840: sends PING over hardware UART (D6=TX) every second.
// No BLE stack. Pure UART TX test.

void setup() {
  Serial.begin(115200);   // USB debug
  Serial1.begin(115200);  // Hardware UART — D6=TX → Pico GP1
  delay(500);
  Serial.println("[nRF] UART TX test started");
}

void loop() {
  Serial1.println("PING");
  Serial.println("[nRF] Sent: PING");
  delay(1000);
}