"""
test3.py — chunked BLE relay (244-byte UART chunks, per-chunk handshake)

What this script does:
  1. (Optionally) uploads ble_3.ino to the nRF52840 via arduino-cli.
  2. (Optionally) uploads Pico_3.ino to the Raspberry Pi Pico via arduino-cli.
  3. For each run:
     a. Records a baseline with the HMC8012 multimeter.
     b. Connects BLE, orchestrates the chunked test, ACKs the Pico via USB.
     c. Streams meter samples + events to a per-run CSV.

Strategy: Pico sends 244 bytes over UART → nRF buffers exactly 244 bytes →
sends as one BLE notification → writes "N" back to Pico → Pico sends
next 244 bytes. The nRF holds at most 244 bytes of payload in RAM at any
time. 244 bytes = ATT MTU 247 - 3 bytes overhead.

Sketch sources (read from disk and uploaded via arduino-cli):
  ble_3.ino  → nRF52840 (Seeeduino:nrf52:xiaonRF52840Sense)
  Pico_3.ino → Raspberry Pi Pico (rp2040:rp2040:rpipico)
"""

import asyncio
import csv
import os
import serial
import serial.tools.list_ports
import shutil
import subprocess
import threading
import time
from datetime import datetime
from bleak import BleakClient
import pyvisa

# ─── CONFIG ───────────────────────────────────────────────────────────────────
MODULE        = "ble_nrf52"
STRATEGY      = "chunked_244"
TOTAL_RUNS    = 30

PAYLOAD_SIZES = [
    1, 2, 4, 8, 16, 32, 64, 128, 256, 512,
    1024, 2048, 4096, 8192, 16384, 32768, 65536,
    131072, 262144, 524288
]

PICO_PORT       = '/dev/cu.usbmodem11301'
PICO_BAUD       = 115200
NRF_PORT        = '/dev/cu.usbmodem11101'

NRF_ADDRESS     = "1385E324-4660-24ED-9B2E-A55F8DF154AE"
NUS_TX_UUID     = "6e400003-b5a3-f393-e0a9-e50e24dcca9e"

EXPERIMENT_ROOT = '/Users/foml/coding/MSP/year_3/Thesis work/BTR/experiments/overnight/ble experiment 3 (chunk)'
NRF_SKETCH_DIR  = os.path.join(EXPERIMENT_ROOT, 'ble_3')
PICO_SKETCH_DIR = os.path.join(EXPERIMENT_ROOT, 'Pico_3')

NRF_FQBN  = 'Seeeduino:nrf52:xiaonRF52840Sense'
PICO_FQBN = 'rp2040:rp2040:rpipico'   # Earle Philhower core; change if using arduino:mbed_rp2040:pico

SAFE_BUILD_BASE = '/tmp/ble_upload_tmp'

UART_CHUNK_BYTES = 244
BLE_TIMEOUT_S    = 600
IDLE_S           = 1.0
BASELINE_S       = 5.0
METER_WARMUP_S   = 2.0

SHUNT_OHMS = 1.13
V_SUPPLY   = 3.3

SCRIPT_DIR  = os.path.dirname(os.path.abspath(__file__))
SESSION_TAG = datetime.now().strftime("%Y%m%d_%H%M%S")
OUT_DIR     = os.path.join(SCRIPT_DIR, "data", MODULE, STRATEGY, SESSION_TAG)
os.makedirs(OUT_DIR, exist_ok=True)
# ─────────────────────────────────────────────────────────────────────────────


# ─── Sketch upload helpers ────────────────────────────────────────────────────

def run_cmd(cmd, check=True):
    print(f"$ {' '.join(cmd)}")
    result = subprocess.run(cmd, text=True)
    if check and result.returncode != 0:
        raise RuntimeError(f"Command failed: {' '.join(cmd)}")
    return result.returncode


def _safe_sketch_path(src_dir):
    if not os.path.isdir(src_dir):
        raise RuntimeError(f"Sketch directory not found: {src_dir}")
    if " " in src_dir or "(" in src_dir or ")" in src_dir:
        name = os.path.basename(os.path.normpath(src_dir))
        safe = os.path.join(SAFE_BUILD_BASE, name)
        if os.path.exists(safe):
            shutil.rmtree(safe)
        os.makedirs(SAFE_BUILD_BASE, exist_ok=True)
        shutil.copytree(src_dir, safe)
        print(f"[→] Copied sketch to: {safe}")
        return safe
    return src_dir


def upload_sketch(label, sketch_dir, port, fqbn, post_boot_s=4):
    print(f"\n[→] Uploading {label} sketch ({sketch_dir}) → {port}")
    sketch = _safe_sketch_path(sketch_dir)
    run_cmd(["arduino-cli", "compile", "--fqbn", fqbn, sketch])
    rc = run_cmd(["arduino-cli", "upload", "-p", port, "-b", fqbn, sketch], check=False)
    if rc != 0:
        print(f"[!] {label} upload failed.")
        print( "    nRF: double-tap reset, wait for the LED pulse.")
        print( "    Pico: hold BOOTSEL while replugging, then release.")
        input("    Press ENTER to retry → ")
        time.sleep(1)
        run_cmd(["arduino-cli", "upload", "-p", port, "-b", fqbn, sketch])
    print(f"[✓] {label} uploaded. Waiting {post_boot_s}s for boot...")
    time.sleep(post_boot_s)


def upload_nrf():
    upload_sketch("nRF52840", NRF_SKETCH_DIR, NRF_PORT, NRF_FQBN, post_boot_s=5)


def upload_pico():
    # Pico re-enumerates its USB-CDC after upload; give it extra time before we open the port.
    upload_sketch("Pico", PICO_SKETCH_DIR, PICO_PORT, PICO_FQBN, post_boot_s=6)


def open_pico_serial(retries=20, delay_s=1.0):
    """Open Pico USB-CDC port, retrying while it re-enumerates after upload."""
    last_err = None
    for attempt in range(retries):
        try:
            return serial.Serial(PICO_PORT, PICO_BAUD, timeout=2)
        except (serial.SerialException, OSError) as e:
            last_err = e
            if attempt == 0:
                ports = [p.device for p in serial.tools.list_ports.comports()]
                print(f"[!] Pico not found at {PICO_PORT}. Available: {ports}")
                print(f"    Retrying every {delay_s:.1f}s ({retries} attempts)...")
            time.sleep(delay_s)
    raise RuntimeError(f"Could not open Pico port {PICO_PORT}: {last_err}")


def wait_for_ready(pico, timeout=15):
    """Read lines until we see READY, ignoring stale junk in the buffer."""
    pico.reset_input_buffer()
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            line = pico.readline().decode(errors='replace').strip()
        except (OSError, serial.SerialException) as e:
            print(f"[Pico] read error: {e}")
            time.sleep(0.5)
            continue
        if line:
            print(f"[Pico] {line}")
            if line == "READY":
                return True
    return False


def wait_for_line(pico, expected, timeout=30):
    """Same as above but for arbitrary expected lines (used between runs)."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if pico.in_waiting:
            try:
                line = pico.readline().decode(errors='replace').strip()
            except (OSError, serial.SerialException) as e:
                print(f"[Pico] read error: {e}")
                time.sleep(0.2)
                continue
            if line:
                print(f"[Pico] {line}")
            if line == expected:
                return True
        time.sleep(0.05)
    return False


def verify_payload(payload: bytes, payload_size: int, index: int) -> bool:
    expected_byte = ord('0') + (index % 10)
    if len(payload) != payload_size:
        print(f"  [!] Size mismatch: expected {payload_size}B got {len(payload)}B")
        return False
    wrong = sum(1 for b in payload if b != expected_byte)
    if wrong > 0:
        print(f"  [!] Content mismatch: {wrong}/{len(payload)} bytes wrong")
        return False
    return True


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

_current_phase = "idle"
_phase_lock    = threading.Lock()

def set_phase(phase):
    global _current_phase
    with _phase_lock:
        _current_phase = phase

def get_phase():
    with _phase_lock:
        return _current_phase


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


# ─── BLE receiver ─────────────────────────────────────────────────────────────

class BLEReceiver:
    def __init__(self):
        self._queue = None
        self._loop  = None
        self._size  = None
        self._fail  = False

    def start(self):
        self._loop  = asyncio.get_running_loop()
        self._queue = asyncio.Queue()

    def reset(self):
        while not self._queue.empty():
            try:
                self._queue.get_nowait()
            except asyncio.QueueEmpty:
                break
        self._size = None
        self._fail = False

    def handler(self, sender, data: bytearray):
        self._queue.put_nowait(bytes(data))

    async def wait_for_size(self, timeout=300) -> bool:
        deadline = self._loop.time() + timeout
        while True:
            rem = deadline - self._loop.time()
            if rem <= 0:
                return False
            try:
                data = await asyncio.wait_for(self._queue.get(), timeout=rem)
            except asyncio.TimeoutError:
                return False
            try:
                text = data.decode('utf-8').strip()
                if text.startswith("SIZE:"):
                    self._size = int(text.split(":")[1])
                    print(f"  [BLE] SIZE header: {self._size}B")
                    return True
                if text == "FAIL":
                    self._fail = True
                    return True
            except Exception:
                pass

    async def read_exact(self, n: int, timeout=BLE_TIMEOUT_S):
        buf      = bytearray()
        deadline = self._loop.time() + timeout
        while len(buf) < n:
            rem = deadline - self._loop.time()
            if rem <= 0:
                print(f"  [!] Timeout: have {len(buf)}B, need {n}B")
                return None
            try:
                chunk = await asyncio.wait_for(self._queue.get(), timeout=rem)
                buf.extend(chunk)
            except asyncio.TimeoutError:
                print(f"  [!] Timeout: have {len(buf)}B, need {n}B")
                return None
        return bytes(buf[:n])

    @property
    def declared_size(self): return self._size

    @property
    def is_fail(self): return self._fail


# ─── BLE test (async) ─────────────────────────────────────────────────────────

async def run_ble_test_async(pico, write_event_row):
    print(f"\n[BLE] Connecting to nRF...")

    client = BleakClient(NRF_ADDRESS)
    for attempt in range(10):
        try:
            await client.connect(timeout=10.0)
            if client.is_connected:
                print(f"[✓] BLE connected.")
                break
        except Exception as e:
            print(f"[!] BLE attempt {attempt+1}/10 failed: {e}")
            await asyncio.sleep(3)

    if not client.is_connected:
        print("[!] Could not connect to nRF.")
        return [], True

    results = []

    try:
        receiver = BLEReceiver()
        receiver.start()
        await client.start_notify(NUS_TX_UUID, receiver.handler)
        mtu = client.mtu_size
        print(f"[✓] Subscribed to BLE notifications. MTU: {mtu}B ({mtu - 3}B effective chunk)")

        pico.reset_input_buffer()
        pico.write(b"go\n")
        print("[BLE] Sent 'go' to Pico.")

        deadline = time.time() + 10
        while time.time() < deadline:
            if pico.in_waiting:
                line = pico.readline().decode(errors='replace').strip()
                if line:
                    print(f"[Pico] {line}")
                if line.startswith("START_IN_"):
                    break
            await asyncio.sleep(0.01)

        skip_remaining = False

        for i, payload_size in enumerate(PAYLOAD_SIZES):
            if skip_remaining:
                break

            receiver.reset()
            set_phase(f"tx_{payload_size}")
            tx_start = datetime.now().isoformat(timespec="milliseconds")
            print(f"\n  [{i+1}/{len(PAYLOAD_SIZES)}] Expecting {payload_size}B...")
            t_start = time.monotonic()

            if not await receiver.wait_for_size(timeout=BLE_TIMEOUT_S):
                print(f"  [!] No SIZE header — stopping.")
                pico.write(b"SKIP\n")
                write_event_row(payload_size, payload_size, 0, tx_start, "FAILED",
                                False, False, "no_size_header")
                skip_remaining = True
                break

            if receiver.is_fail:
                print(f"  [!] nRF sent FAIL — recording and continuing.")
                pico.write(b"SKIP\n")
                write_event_row(payload_size, payload_size, 0, tx_start,
                                datetime.now().isoformat(timespec="milliseconds"),
                                False, False, "nrf_fail")
                results.append((payload_size, "FAIL", 0.0))
                await asyncio.sleep(1.5)
                pico.write(b"ACK\n")
                set_phase("idle")
                await asyncio.sleep(IDLE_S)
                continue

            if receiver.declared_size != payload_size:
                print(f"  [!] SIZE mismatch: nRF says {receiver.declared_size}B, expected {payload_size}B")
                pico.write(b"SKIP\n")
                write_event_row(payload_size, receiver.declared_size, 0, tx_start, "FAILED",
                                False, False, "size_mismatch")
                skip_remaining = True
                break

            payload = await receiver.read_exact(receiver.declared_size, timeout=BLE_TIMEOUT_S)
            rx_end  = datetime.now().isoformat(timespec="milliseconds")

            if payload is None:
                print(f"  [!] {payload_size}B timed out.")
                pico.write(b"SKIP\n")
                write_event_row(payload_size, payload_size, 0, tx_start, "FAILED",
                                False, False, "ble_timeout")
                skip_remaining = True
                break

            t_elapsed  = time.monotonic() - t_start
            verified   = verify_payload(payload, payload_size, i)
            complete   = len(payload) == receiver.declared_size
            status     = "PASS" if verified else "FAIL"
            throughput = payload_size / t_elapsed if t_elapsed > 0 else 0
            print(f"  [{status}] {payload_size}B  {t_elapsed:.2f}s  {throughput/1024:.1f} KB/s")

            write_event_row(payload_size, receiver.declared_size, len(payload),
                            tx_start, rx_end, complete, verified, "")
            results.append((payload_size, status, t_elapsed))

            pico.write(b"ACK\n")
            set_phase("idle")
            await asyncio.sleep(IDLE_S)

        pico_ready_seen = False
        await asyncio.sleep(1)
        while pico.in_waiting:
            line = pico.readline().decode(errors='replace').strip()
            if line:
                print(f"[Pico] {line}")
            if line == "READY":
                pico_ready_seen = True

    finally:
        await client.stop_notify(NUS_TX_UUID)
        await client.disconnect()

    return results, pico_ready_seen


# ─── Per-run orchestration ────────────────────────────────────────────────────

def run_experiment(run_number, meter, pico, loop, pico_already_ready=False):
    filename = os.path.join(
        OUT_DIR, f"{MODULE}_{STRATEGY}_run{run_number:02d}.csv"
    )
    meter_rows = []
    stop_meter = threading.Event()
    set_phase("idle")

    os.makedirs(OUT_DIR, exist_ok=True)

    if pico_already_ready:
        print(f"\n[Run {run_number:02d}/{TOTAL_RUNS}] Pico ready.")
    else:
        print(f"\n[Run {run_number:02d}/{TOTAL_RUNS}] Waiting for Pico READY...")
        if not wait_for_line(pico, "READY", timeout=60):
            print("[!] Pico did not send READY — skipping run.")
            return False

    csv_file = open(filename, "w", newline="")
    w = csv.writer(csv_file)

    w.writerow(["# META"])
    w.writerow(["module",            MODULE])
    w.writerow(["strategy",          STRATEGY])
    w.writerow(["uart_chunk_bytes",  UART_CHUNK_BYTES])
    w.writerow(["ble_mtu",           247])
    w.writerow(["ble_chunk_bytes",   244])
    w.writerow(["per_chunk_handshake", "nrf_to_pico"])
    w.writerow(["run",               run_number])
    w.writerow(["session",           SESSION_TAG])
    w.writerow(["baseline_s",        BASELINE_S])
    w.writerow(["shunt_ohms",        f"{SHUNT_OHMS:.6f}"])
    w.writerow(["v_supply",          f"{V_SUPPLY:.3f}"])
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

    event_buf = []

    def write_event_row(payload_size, declared_size, bytes_received,
                        tx_start, rx_end, complete, verified, skip_reason):
        row = [run_number, payload_size, declared_size,
               bytes_received, tx_start, rx_end,
               complete, verified, skip_reason]
        event_buf.append(row)
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

    results, pico_ready = loop.run_until_complete(run_ble_test_async(pico, write_event_row))

    set_phase("idle")
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
    passed = sum(1 for _, s, _ in results if s == 'PASS')
    print(f"[✓] Run {run_number:02d} complete. {passed}/{len(results)} passed.")
    print(f"    Saved → {filename}  ({len(meter_rows)} meter samples, {len(event_buf)} events)")
    return pico_ready


# ─── Entry point ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    meter = connect_meter()

    do_upload = input("\nUpload nRF + Pico sketches? [y/n] → ").strip().lower()

    if do_upload in ("y", "yes"):
        upload_nrf()
        upload_pico()
        print(f"\n[→] Opening Pico serial after upload...")
        pico = open_pico_serial()
        print("[→] Waiting for Pico READY (heartbeat-based, up to 30s)...")
        pico_ready = wait_for_ready(pico, timeout=30)
        if pico_ready:
            print("[✓] Pico ready.")
        else:
            print("[!] Pico did not send READY in 30s — will wait at run start.")
    else:
        print(f"\n[→] Opening Pico serial (skip flash)...")
        pico = open_pico_serial()
        print("[→] Waiting for Pico READY (press reset on Pico if needed)...")
        pico_ready = wait_for_ready(pico, timeout=15)
        if pico_ready:
            print("[✓] Pico ready.")
        else:
            print("[!] Pico did not send READY — will wait at run start.")

    loop = asyncio.new_event_loop()

    print(f"\nExperiment : {MODULE} | {STRATEGY}")
    print(f"Runs       : {TOTAL_RUNS}")
    print(f"Payloads   : {PAYLOAD_SIZES}")
    print(f"UART chunk : {UART_CHUNK_BYTES}B = one BLE packet, per-chunk handshake nRF→Pico")
    print(f"Session    : {SESSION_TAG}")
    print(f"Output     : {OUT_DIR}")
    input("\nPress ENTER to begin → ")

    try:
        for run in range(1, TOTAL_RUNS + 1):
            pico_ready = run_experiment(run, meter, pico, loop,
                                        pico_already_ready=pico_ready)
            if pico_ready is None:
                pico_ready = False
            if run < TOTAL_RUNS:
                time.sleep(3)
    finally:
        loop.close()
        pico.close()

    print("\nAll runs complete.")
