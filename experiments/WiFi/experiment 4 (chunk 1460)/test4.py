import pyvisa
import csv
import socket
import os
import serial
import serial.tools.list_ports
import shutil
import subprocess
import threading
import time
from datetime import datetime, timedelta

# ─── CONFIG ───────────────────────────────────────────────────────────────────
MODULE        = "esp32"
STRATEGY      = "chunked_1460"
TOTAL_RUNS    = 30
PAYLOAD_SIZES = [
    1, 2, 4, 8, 16, 32, 64, 128, 256, 512,
    1024, 2048, 4096, 8192, 16384, 32768, 65536,
    131072, 262144, 524288
]

TCP_CHUNK_BYTES = 1460   # TCP MSS: Ethernet MTU(1500) - IP(20) - TCP(20)

# A run is only accepted if it reaches at least this payload size successfully.
MIN_VALID_PAYLOAD = 131072

PICO_PORT      = "/dev/tty.usbmodem11301"
PICO_BAUD      = 115200
TCP_HOST       = "0.0.0.0"
TCP_PORT       = 8080
ESP32_SSID     = "esp32_test"
ESP32_FQBN     = "esp32:esp32:esp32c3"
ESP32_PORT     = "/dev/tty.usbmodem11101"
ESP32_SKETCH   = "/Users/foml/coding/MSP/year_3/BTR/experiments/WiFi/experiment 4 (chunk 1460)/wifi_4"
SAFE_BUILD_DIR = "/tmp/wifi_upload_tmp"

IDLE_S              = 1.0
BASELINE_S          = 5.0
METER_WARMUP_S      = 2.0
TCP_ACCEPT_TIMEOUT  = 30
TCP_RECEIVE_TIMEOUT = 300

SHUNT_OHMS = 1.13
V_SUPPLY   = 3.3

SCRIPT_DIR  = os.path.dirname(os.path.abspath(__file__))
SESSION_TAG = datetime.now().strftime("%Y%m%d_%H%M%S")
OUT_DIR     = os.path.join(SCRIPT_DIR, "data", MODULE, STRATEGY, SESSION_TAG)
os.makedirs(OUT_DIR, exist_ok=True)
# ──────────────────────────────────────────────────────────────────────────────

# MicroPython main.py flashed onto the Pico.
# Sends payload in 1460-byte UART chunks — no flow control needed at this
# chunk size since 1460 bytes at 115200 baud takes ~127ms to transmit,
# giving the ESP32 ample time to drain each chunk before the next arrives.
PICO_CODE = '''\
import machine, time, sys, select

led  = machine.Pin(25, machine.Pin.OUT)
uart = machine.UART(0, baudrate=115200, tx=machine.Pin(0), rx=machine.Pin(1))

PAYLOAD_SIZES  = [1, 2, 4, 8, 16, 32, 64, 128, 256, 512,
                  1024, 2048, 4096, 8192, 16384, 32768, 65536,
                  131072, 262144, 524288]
UART_CHUNK     = 1460
SETTLE_MS      = 1000
START_DELAY_MS = 500
ESP32_BOOT_MS  = 15000

def flash(n):
    for _ in range(n):
        led.value(1); time.sleep_ms(80)
        led.value(0); time.sleep_ms(80)

def usb_readline(timeout_ms=120000):
    buf = b""
    deadline = time.ticks_add(time.ticks_ms(), timeout_ms)
    while time.ticks_diff(deadline, time.ticks_ms()) > 0:
        if select.select([sys.stdin], [], [], 0.01)[0]:
            c = sys.stdin.read(1)
            if c == "\\n":
                return buf.decode("utf-8", "replace").strip()
            buf += c.encode()
    return ""

def wait_for_esp32_boot(timeout_ms=15000):
    deadline = time.ticks_add(time.ticks_ms(), timeout_ms)
    while time.ticks_diff(deadline, time.ticks_ms()) > 0:
        if uart.any():
            line = uart.readline()
            if line and b"BOOT" in line:
                return True
        time.sleep_ms(10)
    return False

print("[Pico] Waiting for ESP32 boot...")
if wait_for_esp32_boot():
    print("[Pico] ESP32 booted.")
else:
    print("[Pico] WARNING: ESP32 boot timeout.")

print("READY")

while True:
    led.value(1); time.sleep_ms(100)
    led.value(0); time.sleep_ms(900)

    if select.select([sys.stdin], [], [], 0)[0]:
        cmd = sys.stdin.readline().strip()
        if cmd == "go":
            print("START_IN_" + str(START_DELAY_MS))
            time.sleep_ms(START_DELAY_MS)

            for i, size in enumerate(PAYLOAD_SIZES):
                digit = bytes([ord("0") + (i % 10)])

                uart.write((str(size) + "\\n").encode())
                time.sleep_ms(50)
                while uart.any():
                    uart.read(uart.any())

                flash(1)
                sent = 0
                skip_run = False

                while sent < size:
                    if select.select([sys.stdin], [], [], 0)[0]:
                        msg = sys.stdin.readline().strip()
                        if msg == "SKIP":
                            skip_run = True
                            break

                    chunk = min(UART_CHUNK, size - sent)
                    uart.write(digit * chunk)
                    sent += chunk
                    # No explicit inter-chunk pause needed:
                    # 1460 bytes at 115200 baud takes ~127ms to transmit —
                    # ESP32 drains each chunk before the next byte arrives.

                flash(2)

                if skip_run:
                    print("SKIPPED " + str(size) + "B")
                    response = usb_readline()
                    if response != "ACK":
                        print("NO_ACK got=" + response)
                        break
                    time.sleep_ms(SETTLE_MS)
                    continue

                # Wait for ESP32 OK/FAIL over UART.
                # Compare bytes directly — avoids MicroPython UnicodeError on
                # stale/framing bytes if decode() error handling is not honoured.
                esp32_resp = ""
                deadline2 = time.ticks_add(time.ticks_ms(), 120000)
                while time.ticks_diff(deadline2, time.ticks_ms()) > 0:
                    if uart.any():
                        line = uart.readline()
                        if b"OK" in line:
                            esp32_resp = "OK"
                            break
                        elif b"FAIL" in line:
                            esp32_resp = "FAIL"
                            break
                    time.sleep_ms(10)

                if esp32_resp == "FAIL":
                    print("ESP32_FAIL " + str(size) + "B")
                    response = usb_readline()
                    if response != "ACK":
                        print("NO_ACK got=" + response)
                        break
                    time.sleep_ms(SETTLE_MS)
                    continue

                print("SENT " + str(size) + "B")
                response = usb_readline()
                if response == "ACK":
                    time.sleep_ms(SETTLE_MS)
                else:
                    print("NO_ACK got=" + response)
                    break

            # Signal ESP32 to restart for next run
            uart.write(b"DONE\\n")
            print("[Pico] Sent DONE to ESP32, waiting for reboot...")

            if wait_for_esp32_boot():
                print("[Pico] ESP32 rebooted cleanly.")
            else:
                print("[Pico] WARNING: ESP32 reboot timeout after run.")

            flash(3)
            print("DONE")
            print("READY")
'''


# ─── Upload helpers ───────────────────────────────────────────────────────────

def run_cmd(cmd, check=True):
    print(f"$ {' '.join(cmd)}")
    result = subprocess.run(cmd, text=True)
    if check and result.returncode != 0:
        raise RuntimeError(f"Command failed: {' '.join(cmd)}")
    return result.returncode


def upload_esp32():
    print("\n[→] Compiling & uploading ESP32 sketch...")
    sketch = ESP32_SKETCH
    if " " in sketch or "(" in sketch or ")" in sketch:
        name = os.path.basename(os.path.normpath(sketch))
        safe = os.path.join(SAFE_BUILD_DIR, name)
        if os.path.exists(safe):
            shutil.rmtree(safe)
        shutil.copytree(sketch, safe)
        sketch = safe
        print(f"[→] Copied sketch to: {sketch}")
    run_cmd(["arduino-cli", "compile", "--fqbn", ESP32_FQBN, sketch])
    rc = run_cmd(["arduino-cli", "upload", "-p", ESP32_PORT, "-b", ESP32_FQBN, sketch], check=False)
    if rc != 0:
        print("[!] Upload failed — press reset on ESP32, press ENTER")
        input("    → ")
        time.sleep(1)
        run_cmd(["arduino-cli", "upload", "-p", ESP32_PORT, "-b", ESP32_FQBN, sketch])
    print("[✓] ESP32 uploaded. Waiting 5s to boot...")
    time.sleep(5)


def flash_pico():
    print("\n[→] Flashing Pico via raw REPL...")
    ser = None
    for attempt in range(10):
        try:
            ser = serial.Serial(PICO_PORT, PICO_BAUD, timeout=2)
            break
        except serial.SerialException:
            if attempt == 0:
                ports = [p.device for p in serial.tools.list_ports.comports()]
                print(f"[!] Pico not found at {PICO_PORT}. Available: {ports}")
                print(f"    Plug in the Pico — retrying every 2s...")
            time.sleep(2)
    if ser is None:
        raise RuntimeError(f"Could not open Pico port {PICO_PORT} after 10 attempts.")

    for _ in range(20):
        ser.write(b'\x03')
        time.sleep(0.05)
    time.sleep(0.5)
    ser.reset_input_buffer()

    ser.write(b'\x01')
    time.sleep(1.0)
    response = ser.read(ser.in_waiting)
    print(f"[REPL] {response}")

    if b'raw REPL' not in response:
        print("[!] Trying Ctrl+B → Ctrl+D → Ctrl+A...")
        ser.write(b'\x02')
        time.sleep(0.5)
        ser.write(b'\x04')
        time.sleep(3.0)
        ser.reset_input_buffer()
        ser.write(b'\x01')
        time.sleep(1.0)
        response = ser.read(ser.in_waiting)
        print(f"[REPL2] {response}")

    if b'raw REPL' not in response:
        ser.close()
        raise RuntimeError("Could not enter raw REPL")

    escaped = PICO_CODE.replace('\\', '\\\\').replace("'", "\\'").replace('\n', '\\n')
    cmd = f"f=open('main.py','w');f.write('{escaped}');f.close()\x04"
    ser.write(cmd.encode())
    time.sleep(3)
    response = ser.read(ser.in_waiting)
    print(f"[Write] {response}")

    ser.write(b'\x02')
    time.sleep(0.5)
    ser.write(b'\x04')

    print("[→] Waiting for Pico READY (on flash connection)...")
    ser.timeout = 15
    deadline = time.time() + 40
    while time.time() < deadline:
        if ser.in_waiting:
            line = ser.readline().decode(errors='replace').strip()
            if line:
                print(f"[Pico] {line}")
            if line == "READY":
                print("[✓] Pico flashed and ready.")
                return ser
        time.sleep(0.05)

    ser.close()
    raise RuntimeError("Pico did not print READY after flashing")


# ─── WiFi check ───────────────────────────────────────────────────────────────

def check_wifi():
    airport = "/System/Library/PrivateFrameworks/Apple80211.framework/Versions/Current/Resources/airport"
    while True:
        try:
            result = subprocess.run([airport, "-I"], capture_output=True, text=True)
            ssid = next(
                (l.strip().replace("SSID: ", "") for l in result.stdout.splitlines() if " SSID:" in l),
                "unknown"
            )
            if ssid == ESP32_SSID:
                print(f"[WiFi] ✓ Connected to '{ESP32_SSID}'")
                return
            else:
                print(f"\n[!] Wrong WiFi — currently on '{ssid}'")
                print(f"    Connect your Mac to '{ESP32_SSID}' then press ENTER.")
                input("    → ")
        except Exception:
            print("[WiFi] Could not check — ensure you're on esp32_test manually.")
            return


# ─── Meter ────────────────────────────────────────────────────────────────────

def connect_meter():
    rm = pyvisa.ResourceManager('@py')

    def reopen_meter(retries=5, delay=1.0):
        for attempt in range(retries):
            try:
                resources = rm.list_resources()
                print(f"[Meter] Found: {resources}")
                hmc = next((r for r in resources if r.startswith("USB")), None)
                if not hmc:
                    raise RuntimeError(f"HMC8012 not found. Available: {resources}")
                m = rm.open_resource(hmc)
                m.timeout = 10000
                idn = m.query('*IDN?').strip()
                print(f"[Meter] {idn}")
                return m
            except Exception as e:
                print(f"[Meter] Connect attempt {attempt+1}/{retries} failed: {e}")
                time.sleep(delay)
        raise RuntimeError("[Meter] Could not connect after retries.")

    meter = reopen_meter()
    meter.write("CONF:VOLT:DC")
    meter.write("SENS:VOLT:DC:RANG:AUTO ON")
    meter.write("SENS:VOLT:DC:NPLC 0.02")
    meter.write("TRIG:SOUR IMM")
    meter.write("TRIG:COUN INF")

    try:
        nplc = meter.query("SENS:VOLT:DC:NPLC?").strip()
        print(f"[Meter] NPLC confirmed: {nplc} (0.02 = fastest)")
    except Exception:
        pass

    print("[Meter] Configured for maximum sample rate (DC voltage).")
    print("[Meter] Warming up...")
    deadline = time.time() + METER_WARMUP_S
    count = 0
    while time.time() < deadline:
        try:
            meter.query("READ?")
            count += 1
        except Exception:
            pass
    print(f"[Meter] Warmup complete ({count} dummy reads in {METER_WARMUP_S}s).")
    return meter


# ─── Phase tracking ───────────────────────────────────────────────────────────

current_phase = "idle"
phase_lock    = threading.Lock()

def set_phase(phase):
    global current_phase
    with phase_lock:
        current_phase = phase

def get_phase():
    with phase_lock:
        return current_phase

def meter_stream(meter, rows, stop_event, flush_callback):
    while not stop_event.is_set():
        try:
            raw   = meter.query("READ?").strip()
            ts    = datetime.now().isoformat(timespec="milliseconds")
            phase = get_phase()
            entry = {"timestamp": ts, "value": raw, "phase": phase}
            rows.append(entry)
            flush_callback(entry)
        except Exception as e:
            print(f"[Meter] Read error: {e}")
            time.sleep(0.2)


# ─── TCP helpers ──────────────────────────────────────────────────────────────

def recv_exact(conn, expected_size, total_timeout=TCP_RECEIVE_TIMEOUT):
    buf = b""
    deadline = time.time() + total_timeout
    recv_buf = min(65536, max(4096, expected_size // 16))
    conn.settimeout(1.0)
    try:
        while len(buf) < expected_size:
            if time.time() > deadline:
                print(f"  [!] recv_exact timeout after {len(buf)}/{expected_size}B")
                break
            try:
                chunk = conn.recv(min(recv_buf, expected_size - len(buf)))
                if not chunk:
                    if len(buf) < expected_size:
                        print(f"  [!] Connection closed early: {len(buf)}/{expected_size}B")
                    break
                buf += chunk
            except socket.timeout:
                continue
    except Exception as e:
        print(f"  [!] recv_exact error: {e}")
    return buf

def recv_line(conn, max_bytes=64, total_timeout=10):
    buf = b""
    deadline = time.time() + total_timeout
    conn.settimeout(1.0)
    while b"\n" not in buf:
        if time.time() > deadline:
            break
        try:
            b = conn.recv(1)
            if not b:
                break
            buf += b
        except socket.timeout:
            continue
    return buf

def verify_payload(payload: bytes, payload_size: int, index: int) -> bool:
    expected_byte = ord('0') + (index % 10)
    if len(payload) != payload_size:
        print(f"  [!] Size mismatch: expected {payload_size}B got {len(payload)}B")
        return False
    wrong = sum(1 for b in payload if b != expected_byte)
    if wrong > 0:
        print(f"  [!] Content mismatch: {wrong}/{len(payload)} bytes wrong "
              f"(expected 0x{expected_byte:02x} = '{chr(expected_byte)}')")
        return False
    return True

def wait_for_pico(pico, expected, timeout=60):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if pico.in_waiting:
            line = pico.readline().decode(errors='replace').strip()
            if line:
                print(f"[Pico] {line}")
            if line == expected:
                return True
        else:
            time.sleep(0.05)
    return False


# ─── Per-run orchestration ────────────────────────────────────────────────────

def run_experiment(run_number, attempt_number, meter, pico, pico_already_ready=False):
    filename = os.path.join(
        OUT_DIR, f"{MODULE}_{STRATEGY}_run{run_number:02d}.csv"
    )
    meter_rows     = []
    event_rows     = []
    stop_meter     = threading.Event()
    highest_completed = 0
    set_phase("idle")

    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((TCP_HOST, TCP_PORT))
    server.listen(1)
    server.settimeout(TCP_ACCEPT_TIMEOUT)

    try:
        attempt_tag = f" (attempt {attempt_number})" if attempt_number > 1 else ""
        if pico_already_ready:
            print(f"\n[Run {run_number:02d}/{TOTAL_RUNS}]{attempt_tag} Pico already READY.")
        else:
            print(f"\n[Run {run_number:02d}/{TOTAL_RUNS}]{attempt_tag} Waiting for Pico READY...")
            if not wait_for_pico(pico, "READY", timeout=60):
                print("[!] Pico did not send READY — skipping run.")
                return False, False

        csv_file = open(filename, "w", newline="")
        w = csv.writer(csv_file)

        w.writerow(["# META"])
        w.writerow(["module",          MODULE])
        w.writerow(["strategy",        STRATEGY])
        w.writerow(["tcp_chunk_bytes", TCP_CHUNK_BYTES])
        w.writerow(["run",             run_number])
        w.writerow(["attempt",         attempt_number])
        w.writerow(["session",         SESSION_TAG])
        w.writerow(["baseline_s",      BASELINE_S])
        w.writerow(["shunt_ohms",      f"{SHUNT_OHMS:.6f}"])
        w.writerow(["v_supply",        f"{V_SUPPLY:.3f}"])
        w.writerow([])
        w.writerow(["# EVENTS"])
        w.writerow(["run", "payload_size", "declared_size",
                    "bytes_received", "tx_start", "rx_end",
                    "complete", "verified", "skip_reason"])
        w.writerow([])
        w.writerow(["# METER"])
        w.writerow(["timestamp", "v_shunt", "phase"])
        csv_file.flush()

        def flush_meter_row(entry):
            w.writerow([entry["timestamp"], entry["value"], entry["phase"]])
            csv_file.flush()

        print(f"[Run {run_number:02d}] Recording {BASELINE_S}s baseline...")
        set_phase("baseline")
        m_thread = threading.Thread(
            target=meter_stream,
            args=(meter, meter_rows, stop_meter, flush_meter_row),
            daemon=True
        )
        m_thread.start()
        time.sleep(BASELINE_S)

        pico.write(b"go\n")
        print(f"[Run {run_number:02d}] Sent 'go' to Pico.")

        estimated_start = None
        delay_ms        = None
        deadline = time.time() + 10
        while time.time() < deadline:
            if pico.in_waiting:
                line = pico.readline().decode(errors='replace').strip()
                if line:
                    print(f"[Pico] {line}")
                if line.startswith("START_IN_"):
                    serial_rx_time  = datetime.now()
                    delay_ms        = int(line.split("_")[2])
                    estimated_start = serial_rx_time + timedelta(milliseconds=delay_ms)
                    print(f"[Run {run_number:02d}] Start anchored: {estimated_start.isoformat()}")
                    break
            else:
                time.sleep(0.05)

        if estimated_start is None:
            print("[!] No START_IN — aborting run.")
            pico.write(b"SKIP\n")
            stop_meter.set()
            m_thread.join(timeout=3)
            csv_file.close()
            return False, False

        w.writerow(["estimated_start", estimated_start.isoformat()])
        w.writerow(["start_delay_ms",  delay_ms])
        csv_file.flush()

        set_phase("idle")
        time.sleep(IDLE_S)

        skip_remaining = False
        results = []

        for i, payload_size in enumerate(PAYLOAD_SIZES):
            if skip_remaining:
                break

            tx_start    = datetime.now().isoformat(timespec="milliseconds")
            t_start     = time.monotonic()
            skip_reason = ""
            print(f"  [→] {i+1}/{len(PAYLOAD_SIZES)} Waiting for {payload_size}B...")
            set_phase(f"tx_{payload_size}")

            try:
                conn, addr = server.accept()
                with conn:
                    header   = recv_line(conn)
                    declared = int(header.decode().strip().replace("SIZE:", ""))
                    payload  = recv_exact(conn, declared)
                    rx_end   = datetime.now().isoformat(timespec="milliseconds")

                t_elapsed  = time.monotonic() - t_start
                throughput = payload_size / t_elapsed if t_elapsed > 0 else 0
                verified = verify_payload(payload, payload_size, i)
                complete = len(payload) == declared
                status   = "PASS" if verified else "FAIL"

                print(f"  [{status}] {payload_size}B  {t_elapsed:.2f}s  {throughput/1024:.1f} KB/s")
                results.append((payload_size, status, t_elapsed))

                if verified:
                    highest_completed = payload_size

                event_rows.append({
                    "payload_size":   payload_size,
                    "declared_size":  declared,
                    "bytes_received": len(payload),
                    "tx_start":       tx_start,
                    "rx_end":         rx_end,
                    "complete":       complete,
                    "verified":       verified,
                    "skip_reason":    "",
                })
                w.writerow([run_number, payload_size, declared,
                            len(payload), tx_start, rx_end,
                            complete, verified, ""])
                csv_file.flush()
                pico.write(b"ACK\n")

            except socket.timeout:
                # Check if ESP32 sent FAIL over UART (Pico forwards it to Mac)
                esp32_fail = False
                deadline2  = time.time() + 2
                while time.time() < deadline2:
                    if pico.in_waiting:
                        line = pico.readline().decode(errors='replace').strip()
                        if line:
                            print(f"[Pico] {line}")
                        if line.startswith("ESP32_FAIL"):
                            esp32_fail  = True
                            skip_reason = "esp32_fail"
                            break
                    time.sleep(0.05)

                if not esp32_fail:
                    skip_reason = "tcp_timeout"

                t_elapsed = time.monotonic() - t_start
                print(f"  [!] {payload_size}B failed ({skip_reason}) after {t_elapsed:.2f}s — skipping remaining.")
                results.append((payload_size, "FAIL", t_elapsed))
                event_rows.append({
                    "payload_size":   payload_size,
                    "declared_size":  payload_size,
                    "bytes_received": 0,
                    "tx_start":       tx_start,
                    "rx_end":         "FAILED",
                    "complete":       False,
                    "verified":       False,
                    "skip_reason":    skip_reason,
                })
                w.writerow([run_number, payload_size, payload_size,
                            0, tx_start, "FAILED", False, False, skip_reason])
                csv_file.flush()
                pico.write(b"SKIP\n")
                skip_remaining = True

            set_phase("idle")
            if not skip_remaining:
                time.sleep(IDLE_S)

        pico_ready_seen = False
        deadline = time.time() + 10
        while time.time() < deadline:
            if pico.in_waiting:
                line = pico.readline().decode(errors='replace').strip()
                if line:
                    print(f"[Pico] {line}")
                if line == "READY":
                    pico_ready_seen = True
                    break
            else:
                time.sleep(0.05)

        stop_meter.set()
        m_thread.join(timeout=3)
        csv_file.close()

        print(f"\n─── Run {run_number:02d} Results ──────────────────────────────────────")
        print(f"  {'Size':>10}   {'Status':<6}  {'Time':>8}  {'KB/s':>8}")
        print(f"  {'─'*10}   {'─'*6}  {'─'*8}  {'─'*8}")
        for size, status, elapsed in results:
            kbps = (size / elapsed / 1024) if elapsed > 0 else 0
            print(f"  {size:>9}B   {status:<6}  {elapsed:>7.2f}s  {kbps:>7.1f}")
        print("──────────────────────────────────────────────────────")
        passed = sum(1 for _, s, _ in results if s == "PASS")
        print(f"[✓] Run {run_number:02d} complete. {passed}/{len(results)} passed.")
        print(f"    → {filename}")
        print(f"    Highest completed: {highest_completed}B (threshold: {MIN_VALID_PAYLOAD}B)")

        return highest_completed >= MIN_VALID_PAYLOAD, pico_ready_seen

    finally:
        server.close()


# ─── Entry point ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    meter = connect_meter()

    do_upload = input("\nUpload ESP32 + flash Pico? [y/n] → ").strip().lower()

    if do_upload in ("y", "yes"):
        upload_esp32()
        pico = flash_pico()
        pico_ready = True
    else:
        print(f"\n[→] Opening Pico serial (skip flash)...")
        pico = None
        for attempt in range(10):
            try:
                pico = serial.Serial(PICO_PORT, PICO_BAUD, timeout=15)
                break
            except serial.SerialException:
                if attempt == 0:
                    ports = [p.device for p in serial.tools.list_ports.comports()]
                    print(f"[!] Pico not found at {PICO_PORT}. Available: {ports}")
                    print(f"    Plug in the Pico — retrying every 2s...")
                time.sleep(2)
        if pico is None:
            raise RuntimeError(f"Could not open Pico port {PICO_PORT}.")
        for _ in range(3):
            pico.write(b'\x03')
            time.sleep(0.1)
        time.sleep(0.5)
        pico.reset_input_buffer()
        pico.write(b'\x04')
        print("[→] Waiting for Pico READY...")
        deadline = time.time() + 40
        pico_ready = False
        while time.time() < deadline:
            if pico.in_waiting:
                line = pico.readline().decode(errors='replace').strip()
                if line:
                    print(f"[Pico] {line}")
                if line == "READY":
                    pico_ready = True
                    break
            time.sleep(0.05)
        if pico_ready:
            print("[✓] Pico ready.")
        else:
            print("[!] Pico did not send READY — will wait at run start.")

    check_wifi()

    print(f"\nExperiment : {MODULE} | {STRATEGY}")
    print(f"Runs       : {TOTAL_RUNS}")
    print(f"Payloads   : {PAYLOAD_SIZES}")
    print(f"TCP chunk  : {TCP_CHUNK_BYTES}B (TCP MSS)")
    print(f"Min valid  : {MIN_VALID_PAYLOAD}B — runs failing before this are retried")
    print(f"Session    : {SESSION_TAG}")
    print(f"Output     : {OUT_DIR}")
    input("\nPress ENTER to begin → ")

    completed_runs = 0
    run_number     = 1

    while completed_runs < TOTAL_RUNS:
        attempt = 1
        while True:
            valid, pico_ready = run_experiment(run_number, attempt, meter, pico,
                                               pico_already_ready=pico_ready)
            if valid:
                print(f"[✓] Run {run_number} accepted ({completed_runs + 1}/{TOTAL_RUNS}).\n")
                completed_runs += 1
                run_number += 1
                break
            else:
                print(f"[✗] Run {run_number} failed before {MIN_VALID_PAYLOAD}B "
                      f"— retrying (attempt {attempt + 1})...")
                attempt += 1
                time.sleep(5)

        if completed_runs < TOTAL_RUNS:
            time.sleep(3)

    pico.close()
    print(f"\nAll {TOTAL_RUNS} valid runs complete.")