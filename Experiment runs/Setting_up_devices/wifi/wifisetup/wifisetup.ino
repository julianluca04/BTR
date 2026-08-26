#include <WiFi.h>
#include <WiFiUdp.h>

/* ========= Wi-Fi Access Point Settings ========= */
const char* ap_ssid = "esp32_test";
const char* ap_password = "esp32test";  // must be ≥ 8 chars

/* ========= UDP Settings ========= */
WiFiUDP udp;
const unsigned int udpPort = 4210;
IPAddress broadcastIP(192, 168, 4, 255);

unsigned long counter = 0;

void setup() {
  Serial.begin(115200);
  delay(3000);

  Serial.println("Starting ESP32 Wi-Fi Access Point...");

  WiFi.mode(WIFI_AP);
  WiFi.softAP(ap_ssid, ap_password);

  IPAddress apIP = WiFi.softAPIP();
  Serial.print("ESP32 AP IP address: ");
  Serial.println(apIP);

  udp.begin(udpPort);
  Serial.println("UDP broadcast ready");
}

void loop() {
  char msg[64];
  sprintf(msg, "Broadcast message #%lu", counter++);

  udp.beginPacket(broadcastIP, udpPort);
  udp.write((uint8_t*)msg, strlen(msg));
  udp.endPacket();

  Serial.println(msg);
  delay(1000);
}

/*
python3 - << 'EOF'  
import socket  
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)  
sock.bind(("", 4210))  
print("Listening for UDP packets...")  
while True:  
data, addr = sock.recvfrom(1024)  
print(f"From {addr}: {data.decode()}")  
EOF
*/