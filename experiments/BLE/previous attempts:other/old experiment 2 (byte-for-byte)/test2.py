"""
test2.py — byte-for-byte BLE relay
1. Uploads nRF sketch (once)
2. Flashes Pico with MicroPython experiment code (once)
3. For each run:
   a. Records a baseline with the HMC8012 multimeter
   b. Connects BLE, orchestrates byte-for-byte test, ACKs Pico via USB serial
   c. Saves meter samples + events to a per-run CSV

Strategy: Pico sends one byte at a time over UART → nRF immediately forwards
each byte as its own BLE notification → Mac receives individual byte packets.
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
STRATEGY      = "byte_for_byte"
TOTAL_RUNS    = 30

PAYLOAD_SIZES = [
    1, 2, 4, 8, 16, 32, 64, 128, 256, 512,
    1024, 2048, 4096, 8192, 16384, 32768, 65536
]

PICO_PORT       = '/dev/cu.usbmodem11301'
PICO_BAUD       = 115200
NRF_ADDRESS     = "1385E324-4660-24ED-9B2E-A55F8DF154AE"
NUS_TX_UUID     = "6e400003-b5a3-f393-e0a9-e50e24dcca9e"
NRF_SKETCH_SRC  = '/Users/foml/coding/MSP/year_3/BTR/experiments/BLE/experiment 2 (byte-for-byte)/ble_2'
NRF_FQBN        = 'Seeeduino:nrf52:xiaonRF52840Sense'
NRF_PORT        = '/dev/cu.usbmodem11101'
SAFE_BUILD_BASE = '/tmp/ble_upload_tmp'

BLE_TIMEOUT_MIN = 90    # floor timeout (seconds) regardless of payload size
BLE_MS_PER_BYTE = 10    # 2× the 5 ms pacing delay — used to scale per-payload timeout
IDLE_S          = 1.0
BASELINE_S      = 5.0
METER_WARMUP_S  = 2.0

SHUNT_OHMS = 1.0
V_SUPPLY   = 3.3

SCRIPT_DIR  = os.path.dirname(os.path.abspath(__file__))
SESSION_TAG = datetime.now().strftime("%Y%m%d_%H%M%S")
OUT_DIR     = os.path.join(SCRIPT_DIR, "data", MODULE, STRATEGY, SESSION_TAG)
os.makedirs(OUT_DIR, exist_ok=True)
# ─────────────────────────────────────────────────────────────────────────────

PICO_CODE = '''\
import machine, time, sys, select

led  = machine.Pin(25, machine.Pin.OUT)
uart = machine.UART(0, baudrate=115200, tx=machine.Pin(0), rx=machine.Pin(1))

PAYLOAD_SIZES  = [1, 2, 4, 8, 16, 32, 64, 128, 256, 512,
                  1024, 2048, 4096, 8192, 16384, 32768, 65536]
SETTLE_MS      = 1000
START_DELAY_MS = 500

def flash(n):
    for _ in range(n):
        led.value(1); time.sleep_ms(80)
        led.value(0); time.sleep_ms(80)

def usb_readline(timeout_ms=300000):
    buf = b""
    deadline = time.ticks_add(time.ticks_ms(), timeout_ms)
    while time.ticks_diff(deadline, time.ticks_ms()) > 0:
        if select.select([sys.stdin], [], [], 0.01)[0]:
            c = sys.stdin.read(1)
            if c == "\\n":
                return buf.decode("utf-8", "replace").strip()
            buf += c.encode()
    return ""

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

                flash(1)
                sent = 0
                aborted = False
                while sent < size:
                    # Check for mid-send abort (SKIP sent by Mac on nRF FAIL)
                    if select.select([sys.stdin], [], [], 0)[0]:
                        sys.stdin.readline()
                        aborted = True
                        break
                    uart.write(digit)  # one byte at a time → nRF relays immediately
                    sent += 1
                    time.sleep_ms(5)   # pace to ~200 B/s ≈ BLE drain rate (3 notifs/7.5ms)
                flash(2)

                if aborted:
                    print("SKIPPED " + str(size) + "B")
                    # Wait for Mac to ACK (it will send ACK after nRF drains)
                    response = usb_readline(timeout_ms=300000)
                    if response != "ACK":
                        print("NO_ACK got=" + response)
                        break
                    time.sleep_ms(SETTLE_MS)
                    continue

                print("SENT " + str(size) + "B")

                response = usb_readline(timeout_ms=300000)
                if response == "ACK":
                    time.sleep_ms(SETTLE_MS)
                else:
                    print("NO_ACK got=" + response)
                    break

            flash(3)
            print("DONE")
            print("READY")
'''


# ─── nRF / Pico helpers ───────────────────────────────────────────────────────

def run_cmd(cmd, check=True):
    print(f"$ {' '.join(cmd)}")
    result = subprocess.run(cmd, text=True)
    if check and result.returncode != 0:
        raise RuntimeError(f"Command failed: {' '.join(cmd)}")
    return result.returncode


def upload_nrf():
    print("\n[→] Uploading nRF sketch...")
    sketch = NRF_SKETCH_SRC
    if " " in sketch or "(" in sketch or ")" in sketch:
        name = os.path.basename(os.path.normpath(sketch))
        safe = os.path.join(SAFE_BUILD_BASE, name)
        if os.path.exists(safe):
            shutil.rmtree(safe)
        shutil.copytree(sketch, safe)
        sketch = safe
        print(f"[→] Copied to: {sketch}")
    run_cmd(["arduino-cli", "compile", "--fqbn", NRF_FQBN, sketch])
    rc = run_cmd(["arduino-cli", "upload", "-p", NRF_PORT, "-b", NRF_FQBN, sketch], check=False)
    if rc != 0:
        print("[!] Upload failed — double-tap reset on nRF, wait for LED pulse, press ENTER")
        input("    → ")
        time.sleep(1)
        run_cmd(["arduino-cli", "upload", "-p", NRF_PORT, "-b", NRF_FQBN, sketch])
    print("[✓] nRF uploaded. Waiting 5s to boot...")
    time.sleep(5)


def flash_pico():
    """Flash main.py onto the Pico and return the open serial port.

    The port is kept open so that the 'READY' line printed by the new
    main.py during boot is not lost when the port is closed/reopened.
    The caller is responsible for closing the returned Serial object.
    """
    print("\n[→] Flashing Pico via raw REPL...")
    ser = None
    for attempt in range(10):
        try:
            ser = serial.Serial(PICO_PORT, PICO_BAUD, timeout=2)
            break
        except serial.SerialException:
            if attempt == 0:
                ports = [p.device for p in serial.tools.list_ports.comports()]
                print(f"[!] Pico not found at {PICO_PORT}.")
                print(f"    Available ports: {ports}")
                print(f"    Plug in the Pico — retrying every 2s...")
            time.sleep(2)
    if ser is None:
        raise RuntimeError(f"Could not open Pico port {PICO_PORT} after 10 attempts.")

    # Interrupt whatever is running
    for _ in range(20):
        ser.write(b'\x03')
        time.sleep(0.05)
    time.sleep(0.5)
    ser.reset_input_buffer()

    # Enter raw REPL
    ser.write(b'\x01')
    time.sleep(1.0)  # give it time to respond
    response = ser.read(ser.in_waiting)
    print(f"[REPL] {response}")

    if b'raw REPL' not in response:
        print("[!] Trying Ctrl+B → Ctrl+D → Ctrl+A...")
        ser.write(b'\x02')  # exit any REPL mode first
        time.sleep(0.5)
        ser.write(b'\x04')  # soft reboot
        time.sleep(3.0)     # wait for boot
        ser.reset_input_buffer()
        ser.write(b'\x01')  # enter raw REPL
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

    ser.write(b'\x02')  # exit raw REPL
    time.sleep(0.5)
    ser.write(b'\x04')  # soft reboot into main.py

    # Keep the port open and wait for READY so the line isn't lost.
    print("[→] Waiting for Pico READY (on flash connection)...")
    ser.timeout = 15
    deadline = time.time() + 30
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


def wait_for_line(pico, expected, timeout=30):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if pico.in_waiting:
            line = pico.readline().decode(errors='replace').strip()
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
        time.sleep(0.001)  # yield GIL so asyncio BLE callbacks get CPU time


# ─── BLE receiver ─────────────────────────────────────────────────────────────

class BLEReceiver:
    """Asyncio-native BLE packet collector.

    All public methods that wait for data are coroutines — they yield
    control back to the event loop so bleak's notification callbacks can
    run.  handler() is safe to call from any thread via call_soon_threadsafe.
    """

    def __init__(self):
        self._queue = None   # asyncio.Queue; created in start()
        self._loop  = None
        self._size  = None
        self._fail  = False

    def start(self):
        """Call once from within the running event loop before first use."""
        self._loop  = asyncio.get_running_loop()
        self._queue = asyncio.Queue()

    def reset(self):
        """Drain leftover packets and clear state for the next payload."""
        while not self._queue.empty():
            try:
                self._queue.get_nowait()
            except asyncio.QueueEmpty:
                break
        self._size = None
        self._fail = False

    def handler(self, sender, data: bytearray):
        """BLE notification callback — called on the event loop thread by bleak."""
        self._queue.put_nowait(bytes(data))

    async def wait_for_size(self, timeout=300) -> bool:
        """Consume packets until a SIZE:N or FAIL header is found."""
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
            # Non-text packet before SIZE header — discard and keep waiting

    async def read_exact(self, n: int, timeout=300):
        """Collect exactly n bytes from queued BLE notification chunks."""
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
    """Connect to nRF, run through all payload sizes, call write_event_row for each.

    Returns list of (payload_size, status, elapsed_s) tuples.
    """
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
        # Pico never received 'go' so it is still in its idle ready loop
        return [], True

    results = []

    try:
        receiver = BLEReceiver()
        receiver.start()
        await client.start_notify(NUS_TX_UUID, receiver.handler)
        print(f"[✓] Subscribed to BLE notifications. MTU: {client.mtu_size}B ({client.mtu_size - 3}B data)")

        # Wait for the notification subscription to be fully active on the nRF
        # side before sending 'go'. Without this the first SIZE notification
        # fires before the queue is ready and is silently dropped.
        await asyncio.sleep(1.0)

        pico.reset_input_buffer()
        pico.write(b"go\n")
        print("[BLE] Sent 'go' to Pico.")

        # Wait for Pico START_IN_ confirmation
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

            # Per-payload timeout: 2× the expected transfer time at 5 ms/byte, min 30 s.
            ble_timeout = max(BLE_TIMEOUT_MIN, payload_size * BLE_MS_PER_BYTE // 1000)

            if not await receiver.wait_for_size(timeout=ble_timeout):
                print(f"  [!] No SIZE header — stopping.")
                pico.write(b"SKIP\n")
                await asyncio.sleep(0.3)
                pico.write(b"ACK\n")   # release Pico from abort-wait so it can print READY
                write_event_row(payload_size, payload_size, 0, tx_start, "FAILED",
                                False, False, "no_size_header")
                skip_remaining = True
                break

            if receiver.is_fail:
                print(f"  [!] nRF sent FAIL (malloc) — recording and continuing.")
                pico.write(b"SKIP\n")
                write_event_row(payload_size, payload_size, 0, tx_start,
                                datetime.now().isoformat(timespec="milliseconds"),
                                False, False, "nrf_malloc_fail")
                results.append((payload_size, "FAIL", 0.0))
                # Wait for nRF to drain leftover UART bytes (500ms silence window)
                # then ACK Pico so it moves to the next size
                await asyncio.sleep(1.5)
                pico.write(b"ACK\n")
                set_phase("idle")
                await asyncio.sleep(IDLE_S)
                continue

            if receiver.declared_size != payload_size:
                print(f"  [!] SIZE mismatch: nRF says {receiver.declared_size}B, expected {payload_size}B")
                pico.write(b"SKIP\n")
                await asyncio.sleep(0.3)
                pico.write(b"ACK\n")   # release Pico from abort-wait so it can print READY
                write_event_row(payload_size, receiver.declared_size, 0, tx_start, "FAILED",
                                False, False, "size_mismatch")
                skip_remaining = True
                break

            payload = await receiver.read_exact(receiver.declared_size, timeout=ble_timeout)

            rx_end = datetime.now().isoformat(timespec="milliseconds")

            if payload is None:
                print(f"  [!] {payload_size}B timed out.")
                pico.write(b"SKIP\n")
                await asyncio.sleep(0.3)
                pico.write(b"ACK\n")   # release Pico so it advances and eventually prints READY
                write_event_row(payload_size, payload_size, 0, tx_start, "FAILED",
                                False, False, "ble_timeout")
                results.append((payload_size, "TIMEOUT", 0.0))
                set_phase("idle")
                await asyncio.sleep(IDLE_S)
                continue  # record failure and try next size — Pico is synced via ACK

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

        # Drain remaining Pico output; track whether READY arrived for the next run
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

    if pico_already_ready:
        print(f"\n[Run {run_number:02d}/{TOTAL_RUNS}] Pico ready.")
    else:
        print(f"\n[Run {run_number:02d}/{TOTAL_RUNS}] Waiting for Pico READY...")
        if not wait_for_line(pico, "READY", timeout=60):
            print("[!] Pico did not send READY — skipping run.")
            return False

    csv_file = open(filename, "w", newline="")
    w = csv.writer(csv_file)

    # ── META ──
    w.writerow(["# META"])
    w.writerow(["module",      MODULE])
    w.writerow(["strategy",    STRATEGY])
    w.writerow(["run",         run_number])
    w.writerow(["session",     SESSION_TAG])
    w.writerow(["baseline_s",  BASELINE_S])
    w.writerow(["shunt_ohms",  f"{SHUNT_OHMS:.6f}"])
    w.writerow(["v_supply",    f"{V_SUPPLY:.3f}"])
    w.writerow([])

    # ── EVENTS header ──
    w.writerow(["# EVENTS"])
    w.writerow(["run", "payload_size", "declared_size",
                "bytes_received", "tx_start", "rx_end",
                "complete", "verified", "skip_reason"])
    w.writerow([])

    # ── METER header ──
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

    # ── Baseline ──
    print(f"[Run {run_number:02d}] Recording {BASELINE_S}s baseline...")
    set_phase("baseline")
    m_thread = threading.Thread(
        target=meter_stream,
        args=(meter, meter_rows, stop_meter, flush_meter_row),
        daemon=True
    )
    m_thread.start()
    time.sleep(BASELINE_S)

    # ── BLE test ──
    results, pico_ready = loop.run_until_complete(run_ble_test_async(pico, write_event_row))

    # ── Wrap up ──
    set_phase("idle")
    stop_meter.set()
    m_thread.join(timeout=3)
    csv_file.close()

    # Print summary
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

    do_upload = input("\nUpload nRF + flash Pico? [y/n] → ").strip().lower()

    if do_upload in ("y", "yes"):
        upload_nrf()
        pico = flash_pico()   # returns open port, already confirmed READY
        pico_ready = True
    else:
        # Devices already programmed — just open the serial port and soft-reboot
        # the Pico so it re-runs the existing main.py cleanly.
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
        # Interrupt any running code, then soft-reboot to run main.py
        for _ in range(3):
            pico.write(b'\x03')
            time.sleep(0.1)
        time.sleep(0.5)
        pico.reset_input_buffer()
        pico.write(b'\x04')   # Ctrl+D soft reboot
        print("[→] Waiting for Pico READY...")
        pico_ready = wait_for_line(pico, "READY", timeout=15)
        if pico_ready:
            print("[✓] Pico ready.")
        else:
            print("[!] Pico did not send READY — will wait at run start.")

    # Persistent event loop reused across all runs
    loop = asyncio.new_event_loop()

    print(f"\nExperiment : {MODULE} | {STRATEGY}")
    print(f"Runs       : {TOTAL_RUNS}")
    print(f"Payloads   : {PAYLOAD_SIZES}")
    print(f"Session    : {SESSION_TAG}")
    print(f"Output     : {OUT_DIR}")
    input("\nPress ENTER to begin → ")

    try:
        for run in range(1, TOTAL_RUNS + 1):
            pico_ready = run_experiment(run, meter, pico, loop,
                                        pico_already_ready=pico_ready)
            if pico_ready is None:
                pico_ready = False  # run was skipped
            if run < TOTAL_RUNS:
                time.sleep(3)
    finally:
        loop.close()
        pico.close()

    print("\nAll runs complete.")
