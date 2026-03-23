import socket
import os
from datetime import datetime

HOST = "0.0.0.0"
PORT = 8080
LOG_DIR = "wifi_logs"
SUMMARY_FILE = os.path.join(LOG_DIR, "summary.txt")

os.makedirs(LOG_DIR, exist_ok=True)

session_time = datetime.now().strftime("%Y%m%d_%H%M%S")
msg_count = 0

print(f"[Receiver] Listening on port {PORT}...")
print(f"[Receiver] Logs will be saved to: {LOG_DIR}/")

with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((HOST, PORT))
    server.listen()

    with open(SUMMARY_FILE, "a") as summary:
        summary.write(f"\n=== Session {session_time} ===\n")
        summary.flush()

        while True:
            conn, addr = server.accept()
            with conn:
                data = conn.recv(4096)
                if data:
                    msg = data.decode("utf-8").strip()
                    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    msg_count += 1

                    msg_filename = os.path.join(LOG_DIR, f"msg_{session_time}_{msg_count:03}.txt")
                    with open(msg_filename, "w") as f:
                        f.write(f"Timestamp : {timestamp}\n")
                        f.write(f"From      : {addr[0]}\n")
                        f.write(f"Size      : {len(msg)} bytes\n")
                        f.write(f"Message   : {msg}\n")

                    summary_line = f"[{timestamp}] msg #{msg_count:03} | {len(msg)} bytes | {msg[:40]}{'...' if len(msg) > 40 else ''}"
                    summary.write(summary_line + "\n")
                    summary.flush()

                    print(f"\n[{timestamp}] Message #{msg_count} received!")
                    print(f"  From    : {addr[0]}")
                    print(f"  Size    : {len(msg)} bytes")
                    print(f"  Content : {msg[:60]}{'...' if len(msg) > 60 else ''}")
                    print(f"  Saved   : {msg_filename}")