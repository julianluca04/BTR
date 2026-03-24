"""
Experiment 2 Receiver — 20-byte chunks
Mac-side TCP server. Records timing and chunk arrival pattern.
"""

import socket
import os
import time
from datetime import datetime

HOST    = "0.0.0.0"
PORT    = 8080
LOG_DIR = "logs_exp2"
os.makedirs(LOG_DIR, exist_ok=True)

CHUNK_SIZE = 20  # must match CHUNK_SIZE in wifi_relay_exp2.ino

session_time = datetime.now().strftime("%Y%m%d_%H%M%S")
msg_count    = 0

print(f"[Receiver EXP2] Listening on {HOST}:{PORT}")
print(f"[Receiver EXP2] Expecting {CHUNK_SIZE}-byte chunks")
print(f"[Receiver EXP2] Logs → {LOG_DIR}/")

with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((HOST, PORT))
    server.listen()

    while True:
        conn, addr = server.accept()
        with conn:
            t_first    = None
            t_last     = None
            all_data   = b""
            chunk_log  = []  # (arrival_time_ms, chunk_size)
            t_connect  = time.perf_counter()

            while True:
                chunk = conn.recv(4096)
                if not chunk:
                    break
                now = time.perf_counter()
                if t_first is None:
                    t_first = now
                all_data  += chunk
                t_last     = now
                chunk_log.append((
                    round((now - t_connect) * 1000, 2),
                    len(chunk)
                ))

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

        duration_ms   = (t_last - t_first) * 1000 if t_first else 0
        throughput_bs = len(message) / (duration_ms / 1000) if duration_ms > 0 else 0
        num_chunks    = len(chunk_log)

        msg_count += 1
        timestamp  = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        print(f"\n{'='*55}")
        print(f"[EXP2] Message #{msg_count}  |  {len(message)} bytes")
        print(f"  Declared size  : {declared_size} bytes")
        print(f"  Transfer time  : {duration_ms:.2f} ms")
        print(f"  Throughput     : {throughput_bs:.0f} B/s")
        print(f"  TCP recv calls : {num_chunks}")
        print(f"  Content peek   : {message[:50]}{'...' if len(message) > 50 else ''}")
        print(f"{'='*55}")

        log_file = os.path.join(LOG_DIR, f"msg_{session_time}_{msg_count:03}.txt")
        with open(log_file, "w") as f:
            f.write(f"Experiment     : 2 - Chunked ({CHUNK_SIZE} bytes/chunk)\n")
            f.write(f"Timestamp      : {timestamp}\n")
            f.write(f"Declared size  : {declared_size} bytes\n")
            f.write(f"Actual size    : {len(message)} bytes\n")
            f.write(f"Transfer time  : {duration_ms:.2f} ms\n")
            f.write(f"Throughput     : {throughput_bs:.0f} B/s\n")
            f.write(f"TCP recv calls : {num_chunks}\n")
            f.write(f"Chunk arrivals : {chunk_log}\n")
            f.write(f"Message        : {message}\n")
        print(f"  Saved → {log_file}")
