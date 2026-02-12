import socket

UDP_PORT = 4210
BUFFER_SIZE = 1024

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

# Allow address reuse
sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

# Bind to all interfaces on port 4210
sock.bind(("", UDP_PORT))

print("Listening for UDP broadcasts on port", UDP_PORT)

while True:
    data, addr = sock.recvfrom(BUFFER_SIZE)
    print(f"From {addr}: {data.decode(errors='ignore')}")