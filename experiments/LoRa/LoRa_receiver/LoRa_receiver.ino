void setup() {
  Serial.begin(57600); // RN2903 default
  delay(1000);

  Serial.println("sys reset");
  delay(1000);

  Serial.println("radio set mod lora");
  Serial.println("radio set freq 868100000");
  Serial.println("radio set sf sf7");
  Serial.println("radio set bw 125");
  Serial.println("radio set cr 4/5");
  Serial.println("radio set crc on");

  Serial.println("radio rx 0");
}

void loop() {
  if (Serial.available()) {
    String line = Serial.readStringUntil('\n');
    Serial.println(line);

    if (line.startsWith("radio_rx")) {
      Serial.println("radio rx 0"); // restart RX
    }
  }
}