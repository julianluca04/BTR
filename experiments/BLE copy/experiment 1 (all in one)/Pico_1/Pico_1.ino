#include <Arduino.h>

void setup() {
  pinMode(25, OUTPUT);
  Serial1.begin(115200);
  delay(2000);
}

void loop() {
  Serial1.println("PING");
  digitalWrite(25, HIGH); delay(100);
  digitalWrite(25, LOW);  delay(100);
}
