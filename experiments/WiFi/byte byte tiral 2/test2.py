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
STRATEGY      = "byte_by_byte"
TOTAL_RUNS    = 30
PAYLOAD_SIZES = [
    1, 2, 4, 8, 16, 32, 64, 128, 256, 512,
    1024, 2048 , 4096, 8192, 16384, 32768, 65536,131072
]

MIN_VALID_PAYLOAD = 131072

PICO_PORT      = "/dev/cu.usbmodem11301"
PICO_BAUD      = 115200
TCP_HOST       = "0.0.0.0"
TCP_PORT       = 8080
ESP32_SSID     = "esp32_test"
IDLE_S         = 1.0
BASELINE_S     = 5.0
METER_WARMUP_S = 2.0
TCP_ACCEPT_TIMEOUT  = 30
TCP_RECEIVE_TIMEOUT = 600

ESP32_FQBN     = "esp32:esp32:esp32c3"
ESP32_PORT     = "/dev/tty.usbmodem11101"
ESP32_SKETCH   = "/Users/foml/coding/MSP/year_3/BTR/experiments/WiFi/byte byte tiral 2/wifi_2"
PICO_FQBN      = "rp2040:rp2040:rpipico"
PICO_SKETCH    = "/Users/foml/coding/MSP/year_3/BTR/experiments/WiFi/byte byte tiral 2/Pico_2"
SAFE_BUILD_DIR = "/tmp/wifi_upload_tmp"

SHUNT_OHMS = 1.13
V_SUPPLY   = 3.3

SCRIPT_DIR  = os.path.dirname(os.path.abspath(__file__))
SESSION_TAG = datetime.now().strftime("%Y%m%d_%H%M%S")
OUT_DIR     = os.path.join(SCRIPT_DIR, "data", MODULE, STRATEGY, SESSION_TAG)
os.makedirs(OUT_DIR, exist_ok=True)
# ──────────────────────────────────────────────────────────────────────────────


# ─── Upload helpers ───────────────────────────────────────────────────────────

def run_cmd(cmd, check=True):
    print(f"$ {' '.join(cmd)}")
    result = subprocess.run(cmd, text=True)
    if check and result.returncode != 0:
        raise RuntimeError(f"Command failed: {' '.join(cmd)}")
    return result.returncode


def _safe_copy(sketch_path):
    if " " in sketch_path or "(" in sketch_path or ")" in sketch_path:
        name = os.path.basename(os.path.normpath(sketch_path))
        safe = os.path.join(SAFE_BUILD_DIR, name)
        if os.path.exists(safe):
            shutil.rmtree(safe)
        shutil.copytree(sketch_path, safe)
        print(f"[→] Copied sketch to: {safe}")
        return safe
    return sketch_path


def upload_esp32():
    print("\n[→] Compiling & uploading ESP32 sketch...")
    sketch = _safe_copy(ESP32_SKETCH)
    run_cmd(["arduino-cli", "compile", "--fqbn", ESP32_FQBN, sketch])
    rc = run_cmd(["arduino-cli", "upload", "-p", ESP32_PORT, "-b", ESP32_FQBN, sketch], check=False)
    if rc != 0:
        print("[!] Upload failed — press reset on ESP32, press ENTER")
        input("    → ")
        time.sleep(1)
        run_cmd(["arduino-cli", "upload", "-p", ESP32_PORT, "-b", ESP32_FQBN, sketch])
    print("[✓] ESP32 uploaded. Waiting 5s to boot...")
    time.sleep(5)


def upload_pico():
    print("\n[→] Compiling & uploading Pico sketch...")
    sketch = _safe_copy(PICO_SKETCH)
    run_cmd(["arduino-cli", "compile", "--fqbn", PICO_FQBN, sketch])
    rc = run_cmd(["arduino-cli", "upload", "-p", PICO_PORT, "-b", PICO_FQBN, sketch], check=False)
    if rc != 0:
        print("[!] Upload failed — hold BOOTSEL on Pico, press ENTER")
        input("    → ")
        time.sleep(1)
        run_cmd(["arduino-cli", "upload", "-p", PICO_PORT, "-b", PICO_FQBN, sketch])
    print("[✓] Pico uploaded. Waiting 3s to boot...")
    time.sleep(3)


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


# ─── ESP32 serial monitor ─────────────────────────────────────────────────────

def esp32_monitor(stop_event, esp32_port, baud=115200):
    try:
        with serial.Serial(esp32_port, baud, timeout=1) as esp:
            esp.reset_input_buffer()
            while not stop_event.is_set():
                if esp.in_waiting:
                    line = esp.readline().decode(errors='replace').strip()
                    if line:
                        print(f"[ESP32] {line}", flush=True)
                else:
                    time.sleep(0.05)
    except serial.SerialException:
        pass
    except Exception:
        pass


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
        time.sleep(0.001)


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
    meter_rows      = []
    event_rows      = []
    stop_meter      = threading.Event()
    highest_payload = 0
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
            if not wait_for_pico(pico, "READY", timeout=120):
                print("[!] Pico did not send READY — skipping run.")
                return False, False

        csv_file = open(filename, "w", newline="")
        w = csv.writer(csv_file)

        w.writerow(["# META"])
        w.writerow(["module",      MODULE])
        w.writerow(["strategy",    STRATEGY])
        w.writerow(["run",         run_number])
        w.writerow(["attempt",     attempt_number])
        w.writerow(["session",     SESSION_TAG])
        w.writerow(["baseline_s",  BASELINE_S])
        w.writerow(["shunt_ohms",  f"{SHUNT_OHMS:.6f}"])
        w.writerow(["v_supply",    f"{V_SUPPLY:.3f}"])
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

        def write_event_row(payload_size, declared_size, bytes_received,
                            tx_start, rx_end, complete, verified, skip_reason):
            row = [run_number, payload_size, declared_size,
                   bytes_received, tx_start, rx_end,
                   complete, verified, skip_reason]
            event_rows.append(row)
            w.writerow(row)
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

        skip_remaining  = False
        pico_ready_seen = False
        results         = []

        for i, payload_size in enumerate(PAYLOAD_SIZES):
            if skip_remaining:
                break

            tx_start    = datetime.now().isoformat(timespec="milliseconds")
            t_start     = time.monotonic()
            skip_reason = ""
            print(f"  [→] {i+1}/{len(PAYLOAD_SIZES)} Waiting for {payload_size}B...")
            set_phase(f"tx_{payload_size}")

            dynamic_timeout = max(TCP_RECEIVE_TIMEOUT, payload_size * 3 // 1000 + 60)

            try:
                conn, addr = server.accept()
                with conn:
                    header   = recv_line(conn)
                    declared = int(header.decode().strip().replace("SIZE:", ""))
                    payload  = recv_exact(conn, declared, total_timeout=dynamic_timeout)
                    rx_end   = datetime.now().isoformat(timespec="milliseconds")

                t_elapsed  = time.monotonic() - t_start
                throughput = payload_size / t_elapsed if t_elapsed > 0 else 0
                verified   = verify_payload(payload, payload_size, i)
                complete   = len(payload) == declared
                status     = "PASS" if verified else "FAIL"

                print(f"  [{status}] {payload_size}B  {t_elapsed:.2f}s  {throughput/1024:.1f} KB/s")
                results.append((payload_size, status, t_elapsed))

                if verified:
                    highest_payload = payload_size

                write_event_row(payload_size, declared, len(payload),
                                tx_start, rx_end, complete, verified, "")
                pico.write(b"ACK\n")

            except socket.timeout:
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
                write_event_row(payload_size, payload_size, 0,
                                tx_start, "FAILED", False, False, skip_reason)
                pico.write(b"SKIP\n")
                skip_remaining = True

            set_phase("idle")
            if not skip_remaining:
                time.sleep(IDLE_S)

        # Drain remaining Pico output — wait for DONE then READY
        deadline = time.time() + 60
        done_seen = False
        while time.time() < deadline:
            if pico.in_waiting:
                line = pico.readline().decode(errors='replace').strip()
                if line:
                    print(f"[Pico] {line}")
                if line == "DONE":
                    done_seen = True
                if line == "READY":
                    pico_ready_seen = True
                    break
            else:
                time.sleep(0.05)

        if not done_seen:
            print("[!] WARNING: Pico DONE not seen — ESP32 reboot may not have completed.")

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
        print(f"    ({len(meter_rows)} meter samples, {len(event_rows)} events)")
        print(f"    Highest completed: {highest_payload}B (threshold: {MIN_VALID_PAYLOAD}B)")

        valid = highest_payload >= MIN_VALID_PAYLOAD
        return valid, pico_ready_seen

    finally:
        server.close()


# ─── Entry point ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    meter = connect_meter()

    do_upload = input("\nUpload ESP32 + Pico? [y/n] → ").strip().lower()
    if do_upload in ("y", "yes"):
        upload_esp32()
        upload_pico()
        print("\n[!] Unplug the ESP32 USB cable now, then press ENTER to continue.")
        print("    (The ESP32 will run on Pico 3.3V power for the experiment.)")
        input("    → ")

    print(f"\n[→] Opening Pico serial...")
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

    esp32_stop  = threading.Event()
    esp32_mon   = None
    esp32_ports = [p.device for p in serial.tools.list_ports.comports()]
    if ESP32_PORT in esp32_ports:
        esp32_mon = threading.Thread(
            target=esp32_monitor,
            args=(esp32_stop, ESP32_PORT),
            daemon=True,
        )
        esp32_mon.start()
        print(f"[→] ESP32 serial monitor started on {ESP32_PORT}.")
    else:
        print(f"[→] ESP32 USB not detected — running on Pico power (expected).")

    time.sleep(1)
    pico.reset_input_buffer()
    print("[→] Waiting for Pico READY...")
    pico_ready = False
    deadline   = time.time() + 60
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
    print(f"Min valid  : {MIN_VALID_PAYLOAD}B — runs failing before this are retried")
    print(f"Session    : {SESSION_TAG}")
    print(f"Output     : {OUT_DIR}")
    input("\nPress ENTER to begin → ")

    completed_runs = 0
    run_number     = 1

    try:
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
    finally:
        pico.close()
        esp32_stop.set()
        if esp32_mon:
            esp32_mon.join(timeout=2)

    print(f"\nAll {TOTAL_RUNS} valid runs complete.")