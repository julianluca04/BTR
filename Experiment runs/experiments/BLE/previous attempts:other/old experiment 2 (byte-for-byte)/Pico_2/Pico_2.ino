#include <Arduino.h>

// Payload sizes must match test2.py and ble_2.ino expectations.
const uint32_t PAYLOAD_SIZES[] = {
  1, 2, 4, 8, 16, 32, 64, 128, 256, 512,
  1024, 2048, 4096, 8192, 16384, 32768, 65536
};
const int NUM_SIZES = 17;
const uint32_t SETTLE_MS     = 1000;
const uint32_t START_DELAY_MS = 500;

void flash(int n) {
  for (int i = 0; i < n; i++) {
    digitalWrite(25, HIGH); delay(80);
    digitalWrite(25, LOW);  delay(80);
  }
}

// Read a '\n'-terminated line from USB serial (Serial), up to timeout_ms.
String readLineUSB(uint32_t timeout_ms = 300000) {
  String buf = "";
  uint32_t deadline = millis() + timeout_ms;
  while (millis() < deadline) {
    if (Serial.available()) {
      char c = Serial.read();
      if (c == '\n') return buf;
      if (c != '\r') buf += c;
    }
  }
  return "";
}

void setup() {
  pinMode(25, OUTPUT);
  Serial.begin(115200);   // USB serial → Mac orchestrator
  Serial1.begin(115200);  // UART → nRF52 BLE module (TX=GP0, RX=GP1)
  delay(2000);
  Serial.println("READY");
}

void loop() {
  // Idle: slow blink while waiting for 'go'
  digitalWrite(25, HIGH); delay(100);
  digitalWrite(25, LOW);  delay(900);

  if (!Serial.available()) return;

  String cmd = readLineUSB(1000);
  if (cmd != "go") return;

  Serial.println("START_IN_" + String(START_DELAY_MS));
  delay(START_DELAY_MS);

  for (int i = 0; i < NUM_SIZES; i++) {
    uint32_t size  = PAYLOAD_SIZES[i];
    uint8_t  digit = (uint8_t)('0' + (i % 10));

    // Tell nRF the payload size via UART.
    Serial1.println((unsigned long)size);
    delay(50);

    flash(1);

    // Check for a pre-send skip command from Mac.
    if (Serial.available()) {
      readLineUSB(1000);  // consume the SKIP line
      Serial.println("SKIPPED " + String((unsigned long)size) + "B");
      String ack = readLineUSB(300000);
      if (ack != "ACK") { Serial.println("NO_ACK got=" + ack); break; }
      delay(SETTLE_MS);
      continue;
    }

    // ── Send payload one byte at a time over UART to nRF ──
    // Each byte arrives at the nRF and is immediately forwarded as its own
    // BLE notification (byte-for-byte relay, no buffering on the nRF side).
    bool aborted = false;
    for (uint32_t sent = 0; sent < size; sent++) {
      // Check for mid-send abort from Mac.
      if (Serial.available()) {
        readLineUSB(100);
        aborted = true;
        break;
      }
      Serial1.write(digit);
      delay(5);   // pace to ~200 B/s ≈ BLE drain rate (3 notifs/7.5ms)
    }

    flash(2);

    if (aborted) {
      Serial.println("SKIPPED " + String((unsigned long)size) + "B");
      String ack = readLineUSB(300000);
      if (ack != "ACK") { Serial.println("NO_ACK got=" + ack); break; }
      delay(SETTLE_MS);
      continue;
    }

    Serial.println("SENT " + String((unsigned long)size) + "B");

    String response = readLineUSB(300000);
    if (response == "ACK") {
      delay(SETTLE_MS);
    } else {
      Serial.println("NO_ACK got=" + response);
      break;
    }
  }

  flash(3);
  Serial.println("DONE");
  Serial.println("READY");
}
