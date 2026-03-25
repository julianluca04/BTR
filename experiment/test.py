import pyvisa
import csv
import socket
import os
import serial
import subprocess
import threading
import time
from datetime import datetime, timedelta

# ─── CONFIG ───────────────────────────────────────────────────────────────────
MODULE        = "esp32"
STRATEGY      = "full_payload"
TOTAL_RUNS    = 30
PAYLOAD_SIZES = [
    1, 2, 4, 8, 16, 32, 64, 128, 256, 512,
    1024, 2048, 4096, 8192, 16384, 32768, 65536,
    131072, 262144, 524288, 1048576
]

PICO_PORT      = "/dev/tty.usbmodem21101"
PICO_BAUD      = 115200
TCP_HOST       = "0.0.0.0"
TCP_PORT       = 8080
ESP32_SSID     = "esp32_test"
IDLE_S         = 1.0   # idle buffer between payloads
BASELINE_S     = 5.0   # pre-run baseline recording before Pico starts
METER_WARMUP_S = 2.0   # dummy reads to flush meter pipeline before baseline

SCRIPT_DIR  = os.path.dirname(os.path.abspath(__file__))
SESSION_TAG = datetime.now().strftime("%Y%m%d_%H%M%S")
OUT_DIR     = os.path.join(SCRIPT_DIR, "data", MODULE, STRATEGY, SESSION_TAG)
os.makedirs(OUT_DIR, exist_ok=True)
# ──────────────────────────────────────────────────────────────────────────────

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

def connect_meter():
    rm = pyvisa.ResourceManager('@py')
    resources = rm.list_resources()
    print(f"[Meter] Found: {resources}")
    hmc = next((r for r in resources if r.startswith("USB")), None)
    if not hmc:
        raise RuntimeError(f"HMC8012 not found. Available: {resources}")
    meter = rm.open_resource(hmc)
    meter.timeout = 10000
    print(f"[Meter] {meter.query('*IDN?').strip()}")
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
    print("[Meter] Configured for maximum sample rate.")
    return meter

def warmup_meter(meter):
    """Send dummy reads to flush meter pipeline so first real reads are fast."""
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

# Shared phase tracker
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

def recv_exact(conn, expected_size, timeout=60):
    buf = b""
    conn.settimeout(timeout)
    try:
        while len(buf) < expected_size:
            chunk = conn.recv(min(4096, expected_size - len(buf)))
            if not chunk:
                break
            buf += chunk
    except socket.timeout:
        pass
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

def wait_for_pico(pico, expected, timeout=20):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if pico.in_waiting:
            line = pico.readline().decode().strip()
            if line:
                print(f"[Pico] {line}")
            if line == expected:
                return True
        else:
            time.sleep(0.05)
    return False

def run_experiment(run_number, meter, pico):
    filename = os.path.join(
        OUT_DIR, f"{MODULE}_{STRATEGY}_run{run_number:02d}.csv"
    )
    meter_rows = []
    event_rows = []
    stop_meter = threading.Event()
    set_phase("idle")

    # TCP server — fresh socket each run
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((TCP_HOST, TCP_PORT))
    server.listen(1)
    server.settimeout(30)

    # Wait for Pico READY — do NOT send go yet
    print(f"\n[Run {run_number:02d}/{TOTAL_RUNS}] Waiting for Pico READY...")
    if not wait_for_pico(pico, "READY", timeout=20):
        print("[!] Pico did not send READY — skipping run.")
        server.close()
        return

    # Open CSV and write headers before anything starts
    csv_file = open(filename, "w", newline="")
    w = csv.writer(csv_file)

    def flush_meter_row(entry):
        w.writerow([entry["timestamp"], entry["value"], entry["phase"]])
        csv_file.flush()

    # Warmup meter pipeline so it's ready to read fast
    warmup_meter(meter)

    # Start meter thread and record baseline BEFORE sending go to Pico
    print(f"[Run {run_number:02d}] Recording {BASELINE_S}s baseline before start...")
    set_phase("baseline")
    m_thread = threading.Thread(
        target=meter_stream,
        args=(meter, meter_rows, stop_meter, flush_meter_row),
        daemon=True
    )
    m_thread.start()
    time.sleep(BASELINE_S)

    # NOW send go to Pico
    pico.write(b"go\n")
    print(f"[Run {run_number:02d}] Sent 'go' to Pico.")

    # Wait for START_IN_x
    estimated_start = None
    deadline = time.time() + 5
    while time.time() < deadline:
        if pico.in_waiting:
            line = pico.readline().decode().strip()
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
        server.close()
        csv_file.close()
        return

    # Write full META block now that estimated_start is known
    # Note: meter is already writing rows to csv_file via flush_meter_row,
    # so we write META as comment rows that the meter rows will follow
    # We use a separate events buffer and write it after meter stops
    # to keep the file structure clean — events are flushed inline below

    # Write META
    w.writerow(["# META"])
    w.writerow(["module",          MODULE])
    w.writerow(["strategy",        STRATEGY])
    w.writerow(["run",             run_number])
    w.writerow(["session",         SESSION_TAG])
    w.writerow(["estimated_start", estimated_start.isoformat()])
    w.writerow(["start_delay_ms",  500])
    w.writerow(["baseline_s",      BASELINE_S])
    w.writerow(["shunt_ohms",      "FILL_IN"])
    w.writerow(["v_supply",        3.3])
    w.writerow([])

    # Write EVENTS header
    w.writerow(["# EVENTS"])
    w.writerow(["run", "payload_size", "declared_size",
                "bytes_received", "tx_start", "rx_end",
                "complete", "verified", "skip_reason"])
    w.writerow([])

    # Write METER header — rows are being flushed live by meter thread
    w.writerow(["# METER"])
    w.writerow(["timestamp", "v_shunt", "phase"])
    csv_file.flush()

    # Idle between baseline end and first payload
    set_phase("idle")
    time.sleep(IDLE_S)

    skip_remaining = False

    for i, payload_size in enumerate(PAYLOAD_SIZES):
        if skip_remaining:
            break

        tx_start = datetime.now().isoformat(timespec="milliseconds")
        print(f"  [→] {i+1}/{len(PAYLOAD_SIZES)} Waiting for {payload_size}B...")
        set_phase(f"tx_{payload_size}")

        skip_reason = ""

        try:
            conn, addr = server.accept()
            with conn:
                header = b""
                while b"\n" not in header:
                    header += conn.recv(1)
                declared = int(header.decode().strip().replace("SIZE:", ""))
                payload  = recv_exact(conn, declared)
                rx_end   = datetime.now().isoformat(timespec="milliseconds")

            verified = verify_payload(payload, payload_size, i)
            complete = len(payload) == declared

            if verified:
                print(f"  [✓] {len(payload)}B verified at {rx_end}")
            else:
                print(f"  [✗] {len(payload)}B FAILED at {rx_end}")

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
            # Check if Pico reported ESP32 malloc failure
            esp32_fail = False
            deadline2  = time.time() + 2
            while time.time() < deadline2:
                if pico.in_waiting:
                    line = pico.readline().decode().strip()
                    if line:
                        print(f"[Pico] {line}")
                    if line.startswith("ESP32_FAIL"):
                        esp32_fail  = True
                        skip_reason = "esp32_malloc_fail"
                        break
                time.sleep(0.05)

            if not esp32_fail:
                skip_reason = "tcp_timeout"

            print(f"  [!] {payload_size}B failed ({skip_reason}) — skipping remaining.")
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

        # Idle phase between payloads
        set_phase("idle")
        if not skip_remaining:
            time.sleep(IDLE_S)

    # Drain remaining Pico output
    time.sleep(0.5)
    while pico.in_waiting:
        line = pico.readline().decode().strip()
        if line:
            print(f"[Pico] {line}")

    stop_meter.set()
    m_thread.join(timeout=3)
    server.close()
    csv_file.close()

    print(f"[Run {run_number:02d}] → {filename}  "
          f"({len(meter_rows)} meter samples, {len(event_rows)} events)")


if __name__ == "__main__":
    meter = connect_meter()

    print("\n[Setup] Connecting to Pico...")
    print("        Close Arduino IDE completely before continuing.")
    print("        Connect Mac to esp32_test WiFi before continuing.")
    try:
        pico = serial.Serial(PICO_PORT, PICO_BAUD, timeout=15)
    except serial.SerialException as e:
        if "Resource busy" in str(e):
            print("\n[!] Port busy — close Arduino IDE and retry.")
        else:
            print(f"\n[!] Could not open Pico port: {e}")
        exit(1)

    time.sleep(2)
    pico.reset_input_buffer()

    check_wifi()

    print(f"\nExperiment : {MODULE} | {STRATEGY}")
    print(f"Runs       : {TOTAL_RUNS}")
    print(f"Payloads   : {PAYLOAD_SIZES}")
    print(f"Session    : {SESSION_TAG}")
    print(f"Output     : {OUT_DIR}")
    input("\nPress ENTER to begin → ")

    for run in range(1, TOTAL_RUNS + 1):
        run_experiment(run, meter, pico)
        print(f"[✓] Run {run}/{TOTAL_RUNS} complete.\n")
        if run < TOTAL_RUNS:
            time.sleep(3)

    pico.close()
    print("All runs complete.")