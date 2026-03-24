// =============================================================
// EXPERIMENT 2 — Chunked transmission
// Pico sends message as a continuous stream (no per-byte delay).
// The ESP32 relay buffers incoming bytes and forwards them in
// 20-byte chunks.
//
// Why 20 bytes?  Classic BLE ATT MTU payload = 23 - 3 = 20 bytes.
// This mirrors the packet size used in BLE, making the comparison
// between WiFi-chunked and BLE transfer meaningful.
// =============================================================

const int LED_PIN = 25;
bool started = false;

void setup() {
  Serial.begin(115200);
  Serial1.begin(115200); // GP0 = TX, GP1 = RX  →  ESP32
  pinMode(LED_PIN, OUTPUT);
  delay(4000);
  Serial.println("[Pico EXP2] Ready. Send 'go' to start.");
}

void loop() {
  if (!started && Serial.available()) {
    String cmd = Serial.readStringUntil('\n');
    cmd.trim();
    if (cmd == "go") {
      started = true;
      Serial.println("[Pico EXP2] Starting chunked transmission...");
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

      Serial.print("[Pico EXP2] Sending size=");
      Serial.print(size);
      Serial.println(" (stream, ESP32 will chunk at 20 bytes)");

      // --- Send size header ---
      Serial1.println(size);
      delay(50);

      // --- Send full message as a stream (no per-byte delay) ---
      Serial1.print(msg);
      Serial1.write('\n'); // end-of-message marker

      digitalWrite(LED_PIN, HIGH);
      delay(200);
      digitalWrite(LED_PIN, LOW);

      delay(5000);
    }

    Serial.println("[Pico EXP2] All payloads sent.");
    started = false;
  }
}
