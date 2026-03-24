"""
Experiment 3 Receiver — Full buffer
Mac-side TCP server. Expects one complete message per connection.
Records time from TCP accept() to last byte received.
"""

import socket
import os
import time
from datetime import datetime

HOST    = "0.0.0.0"
PORT    = 8080
LOG_DIR = "logs_exp3"
os.makedirs(LOG_DIR, exist_ok=True)

session_time = datetime.now().strftime("%Y%m%d_%H%M%S")
msg_count    = 0

print(f"[Receiver EXP3] Listening on {HOST}:{PORT}")
print(f"[Receiver EXP3] Logs → {LOG_DIR}/")

with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((HOST, PORT))
    server.listen()

    while True:
        # t_accept: moment the TCP connection was established
        # (in exp3, this is AFTER the ESP32 has buffered everything)
        t_accept  = time.perf_counter()
        conn, addr = server.accept()

        with conn:
            t_first  = None
            t_last   = None
            all_data = b""

            while True:
                chunk = conn.recv(4096)
                if not chunk:
                    break
                now = time.perf_counter()
                if t_first is None:
                    t_first = now
                all_data += chunk
                t_last    = now

        if not all_data:
            continue

        raw = all_data.decode("utf-8", errors="replace").strip()
        parts = raw.split("\n", 1)
        try:
            declared_size = int(parts[0].strip())
            message       = parts[1].strip() if len(parts) > 1 else ""
        except (ValueError, IndexError):
            declared_size = 0
            message       = raw

        # Two timing metrics:
        # transfer_ms : first byte → last byte (network transit time)
        # total_ms    : TCP accept → last byte (includes ESP32 buffering time)
        transfer_ms   = (t_last - t_first) * 1000 if t_first else 0
        total_ms      = (t_last - t_accept) * 1000
        throughput_bs = len(message) / (transfer_ms / 1000) if transfer_ms > 0 else 0

        msg_count += 1
        timestamp  = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        print(f"\n{'='*55}")
        print(f"[EXP3] Message #{msg_count}  |  {len(message)} bytes")
        print(f"  Declared size  : {declared_size} bytes")
        print(f"  Transfer time  : {transfer_ms:.2f} ms  (first→last byte)")
        print(f"  Total time     : {total_ms:.2f} ms  (incl. ESP32 buffering)")
        print(f"  Throughput     : {throughput_bs:.0f} B/s")
        print(f"  Content peek   : {message[:50]}{'...' if len(message) > 50 else ''}")
        print(f"{'='*55}")

        log_file = os.path.join(LOG_DIR, f"msg_{session_time}_{msg_count:03}.txt")
        with open(log_file, "w") as f:
            f.write(f"Experiment     : 3 - Full buffer\n")
            f.write(f"Timestamp      : {timestamp}\n")
            f.write(f"Declared size  : {declared_size} bytes\n")
            f.write(f"Actual size    : {len(message)} bytes\n")
            f.write(f"Transfer time  : {transfer_ms:.2f} ms  (first->last byte)\n")
            f.write(f"Total time     : {total_ms:.2f} ms  (incl. ESP32 buffering)\n")
            f.write(f"Throughput     : {throughput_bs:.0f} B/s\n")
            f.write(f"Message        : {message}\n")
        print(f"  Saved → {log_file}")
