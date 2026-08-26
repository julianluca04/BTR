 #include <bluefruit.h>

BLEService fileService("12345678-1234-1234-1234-1234567890ab");
BLECharacteristic fileChar("12345678-1234-1234-1234-1234567890ac");

#define CHUNK_SIZE 180

// Simulated file
const uint8_t fileData[] = "This is a test file transferred over BLE. "
                           "It can be longer than one packet. "
                           "Chunking handles large files automatically.";
const uint32_t fileSize = sizeof(fileData);

void setup() {
  Serial.begin(115200);
  Bluefruit.begin();
  Bluefruit.setName("XIAO-FILE-SENDER");

  fileService.begin();

  fileChar.setProperties(CHR_PROPS_NOTIFY);
  fileChar.setPermission(SECMODE_OPEN, SECMODE_NO_ACCESS);
  fileChar.setFixedLen(CHUNK_SIZE);
  fileChar.begin();

  Bluefruit.Advertising.addService(fileService);
  Bluefruit.Advertising.addName();
  Bluefruit.Advertising.start(0);

  Serial.println("Ready to send file");
}

void loop() {
  if (Bluefruit.connected()) {
    sendFile();
    delay(10000);
  }
}

void sendFile() {
  Serial.println("Sending file");

  uint8_t header[8];
  memcpy(header, &fileSize, 4);
  fileChar.notify(header, 4);

  uint32_t offset = 0;

  while (offset < fileSize) {
    uint16_t chunkLen = min(CHUNK_SIZE, fileSize - offset);
    fileChar.notify(fileData + offset, chunkLen);
    offset += chunkLen;
    delay(10);
  }

  uint8_t endMarker = 0xFF;
  fileChar.notify(&endMarker, 1);

  Serial.println("File sent");
} 