// =============================================================
// EXPERIMENT 1 — Byte-by-byte transmission
// Pico sends each byte of the message one at a time (1ms gap).
// The ESP32 relay forwards each byte immediately to the Mac.
//
// Note: UART is byte-oriented hardware; "bit-by-bit" is not
// practical here. Byte-by-byte is the finest granularity.
// =============================================================

const int LED_PIN = 25;
bool started = false;

void setup() {
  Serial.begin(115200);
  Serial1.begin(115200); // GP0 = TX, GP1 = RX  →  ESP32
  pinMode(LED_PIN, OUTPUT);
  delay(4000);
  Serial.println("[Pico EXP1] Ready. Send 'go' to start.");
}

void loop() {
  if (!started && Serial.available()) {
    String cmd = Serial.readStringUntil('\n');
    cmd.trim();
    if (cmd == "go") {
      started = true;
      Serial.println("[Pico EXP1] Starting byte-by-byte transmission...");
    }
  }

  if (started) {
    int payloads[] = {8, 32, 64, 128, 256, 512};

    for (int i = 0; i < 6; i++) {
      int size   = payloads[i];
      char digit = '1' + i;

      // Build message
      String msg = "";
      for (int j = 0; j < size; j++) msg += digit;

      Serial.print("[Pico EXP1] Sending size=");
      Serial.print(size);
      Serial.println(" byte-by-byte (1ms/byte)");

      // --- Send size header so ESP32 knows how many bytes to expect ---
      Serial1.println(size);
      delay(50); // short pause before data bytes

      // --- Send message one byte at a time ---
      for (int j = 0; j < (int)msg.length(); j++) {
        Serial1.write((uint8_t)msg[j]);
        delay(1); // 1ms between each byte  →  ~1 kB/s max
      }
      Serial1.write('\n'); // end-of-message marker

      digitalWrite(LED_PIN, HIGH);
      delay(200);
      digitalWrite(LED_PIN, LOW);

      delay(5000); // pause before next payload
    }

    Serial.println("[Pico EXP1] All payloads sent.");
    started = false;
  }
}
