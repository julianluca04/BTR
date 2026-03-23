const int LED_PIN = 25;
bool started = false;

void setup() {
  Serial.begin(115200);
  Serial1.begin(115200); // GP0=TX, GP1=RX
  pinMode(LED_PIN, OUTPUT);
  delay(4000);
  Serial.println("[Pico] Ready. Send 'go' to start.");
}

void loop() {
  if (!started && Serial.available()) {
    String cmd = Serial.readStringUntil('\n');
    cmd.trim();
    if (cmd == "go") {
      started = true;
      Serial.println("[Pico] Starting transmission...");
    }
  }

  if (started) {
    int payloads[] = {8, 32, 64, 128, 256, 512};

    for (int i = 0; i < 6; i++) {
      int size = payloads[i];
      char digit = '1' + i;

      String msg = "";
      for (int j = 0; j < size; j++) msg += digit;

      Serial.print("[Pico] Sending size=");
      Serial.print(size);
      Serial.print(": ");
      Serial.println(msg);

      Serial1.println(size);
      delay(100);
      Serial1.println(msg);

      digitalWrite(LED_PIN, HIGH);
      delay(200);
      digitalWrite(LED_PIN, LOW);

      delay(5000);
    }

    Serial.println("[Pico] All payloads sent.");
    started = false;
  }
}