import socket
import struct
import os

ESP32_IP = "192.168.4.1"
PORT = 5000

# Save folder relative to this script's location
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SAVE_FOLDER = os.path.join(BASE_DIR, "received_files")
os.makedirs(SAVE_FOLDER, exist_ok=True)

def recv_exact(sock, num_bytes):
    data = b""
    while len(data) < num_bytes:
        packet = sock.recv(num_bytes - len(data))
        if not packet:
            raise ConnectionError("Connection closed too early")
        data += packet
    return data

sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
sock.connect((ESP32_IP, PORT))

print("Connected to ESP32")

# ESP32-C3 sends 4-byte size_t
raw_size = recv_exact(sock, 4)
file_size = struct.unpack("I", raw_size)[0]
print("File size:", file_size)

received = 0
data_chunks = []

while received < file_size:
    chunk = sock.recv(1024)
    if not chunk:
        break
    data_chunks.append(chunk)
    received += len(chunk)
    print(f"Received {received}/{file_size} bytes")

sock.close()

file_path = os.path.join(SAVE_FOLDER, "received_file.txt")

with open(file_path, "wb") as f:
    f.write(b"".join(data_chunks))

print("Saved to:", file_path)