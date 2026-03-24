// =============================================================
// EXPERIMENT 3 — Full-buffer transmission
// Pico sends the complete message as a stream.
// The ESP32 relay buffers the ENTIRE message before sending
// anything to the Mac — one single TCP write per message.
// =============================================================

const int LED_PIN = 25;
bool started = false;

void setup() {
  Serial.begin(115200);
  Serial1.begin(115200); // GP0 = TX, GP1 = RX  →  ESP32
  pinMode(LED_PIN, OUTPUT);
  delay(4000);
  Serial.println("[Pico EXP3] Ready. Send 'go' to start.");
}

void loop() {
  if (!started && Serial.available()) {
    String cmd = Serial.readStringUntil('\n');
    cmd.trim();
    if (cmd == "go") {
      started = true;
      Serial.println("[Pico EXP3] Starting full-buffer transmission...");
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

      Serial.print("[Pico EXP3] Sending size=");
      Serial.print(size);
      Serial.println(" (ESP32 will buffer all before forwarding)");

      // --- Send size header ---
      Serial1.println(size);
      delay(50);

      // --- Send full message as a stream ---
      Serial1.print(msg);
      Serial1.write('\n'); // end-of-message marker

      digitalWrite(LED_PIN, HIGH);
      delay(200);
      digitalWrite(LED_PIN, LOW);

      delay(5000);
    }

    Serial.println("[Pico EXP3] All payloads sent.");
    started = false;
  }
}
