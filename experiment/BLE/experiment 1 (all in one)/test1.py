"""
test_ble_full.py  —  Mac-side orchestration for nRF52840 BLE full_payload strategy
Adapted from test3.py (WiFi TCP) — TCP server replaced with BLE NUS central via bleak.

Dependencies:
    pip install bleak pyvisa pyvisa-py pyserial

Nordic UART Service (NUS) UUIDs:
    Service : 6E400001-B5A3-F393-E0A9-E50E24DCCA9E
    TX char : 6E400003-B5A3-F393-E0A9-E50E24DCCA9E  (nRF notifies -> Mac reads)
    RX char : 6E400002-B5A3-F393-E0A9-E50E24DCCA9E  (Mac writes  -> nRF)
"""

import asyncio
import pyvisa
import csv
import os
import serial
import threading
import time
from datetime import datetime, timedelta
from bleak import BleakClient

# --- CONFIG -------------------------------------------------------------------
MODULE        = "nrf52840"
STRATEGY      = "full_payload"
TOTAL_RUNS    = 30
PAYLOAD_SIZES = [
    1, 2, 4, 8, 16, 32, 64, 128, 256, 512,
    1024, 2048, 4096, 8192, 16384, 32768, 65536,
    131072
]

MIN_VALID_PAYLOAD = 131072

PICO_PORT  = "/dev/tty.usbmodem21101"   # update to match your Pico port
PICO_BAUD  = 115200

# Address found via plug/unplug scan test — connect directly, skip scanning
BLE_DEVICE_ADDRESS  = "1385E324-4660-24ED-9B2E-A55F8DF154AE"
BLE_RECV_TIMEOUT    = 300              # seconds to receive one full payload over BLE
BLE_RECONNECT_DELAY = 3.0              # seconds to wait before reconnecting

NUS_TX_CHAR_UUID = "6e400003-b5a3-f393-e0a9-e50e24dcca9e"   # nRF -> Mac (notify)
NUS_RX_CHAR_UUID = "6e400002-b5a3-f393-e0a9-e50e24dcca9e"   # Mac -> nRF (write)

IDLE_S         = 1.0
BASELINE_S     = 5.0
METER_WARMUP_S = 2.0

SHUNT_OHMS = 1.1
V_SUPPLY   = 3.3

SCRIPT_DIR  = os.path.dirname(os.path.abspath(__file__))
SESSION_TAG = datetime.now().strftime("%Y%m%d_%H%M%S")
OUT_DIR     = os.path.join(SCRIPT_DIR, "data", MODULE, STRATEGY, SESSION_TAG)
os.makedirs(OUT_DIR, exist_ok=True)
# ------------------------------------------------------------------------------


# --- METER --------------------------------------------------------------------
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


# --- PICO HELPERS -------------------------------------------------------------
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


# --- BLE RECEIVER -------------------------------------------------------------
class BLEReceiver:
    """
    Connects directly to the nRF52840 by address — no scan needed.
    Automatically reconnects if the connection drops between runs.

    Protocol from nRF:
        "SIZE:<n>\n"   -- header
        <n bytes>      -- raw payload data in MTU-sized notifications
    """

    def __init__(self):
        self._client = None
        self._buf = bytearray()
        self._lock = threading.Lock()
        self._loop = None
        self._thread = None
        self._connected = False

    # -- async internals -------------------------------------------------------

    async def _connect_async(self):
        print(f"[BLE] Connecting to {BLE_DEVICE_ADDRESS}...")
        self._client = BleakClient(
            BLE_DEVICE_ADDRESS,
            disconnected_callback=self._on_disconnected
        )
        await self._client.connect()
        self._connected = True
        print("[BLE] Connected.")
        await self._client.start_notify(NUS_TX_CHAR_UUID, self._on_notify)
        print("[BLE] Notifications enabled.")

    async def _disconnect_async(self):
        if self._client and self._client.is_connected:
            await self._client.disconnect()
        self._connected = False
        print("[BLE] Disconnected.")

    def _on_notify(self, sender, data: bytearray):
        with self._lock:
            self._buf.extend(data)

    def _on_disconnected(self, client):
        self._connected = False
        print("[BLE] Connection dropped by device.")

    # -- public sync API -------------------------------------------------------

    def connect(self):
        """Connect to nRF by address. Blocks until done."""
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._loop.run_forever, daemon=True)
        self._thread.start()
        future = asyncio.run_coroutine_threadsafe(self._connect_async(), self._loop)
        future.result(timeout=30)

    def reconnect(self, retries=5):
        """
        Disconnect cleanly then reconnect.
        Called between runs to reset BLE stack state on both sides.
        """
        if self._client:
            try:
                future = asyncio.run_coroutine_threadsafe(
                    self._disconnect_async(), self._loop
                )
                future.result(timeout=10)
            except Exception:
                pass

        time.sleep(BLE_RECONNECT_DELAY)

        for attempt in range(1, retries + 1):
            try:
                future = asyncio.run_coroutine_threadsafe(
                    self._connect_async(), self._loop
                )
                future.result(timeout=30)
                print(f"[BLE] Reconnect successful (attempt {attempt}).")
                return
            except Exception as e:
                print(f"[BLE] Reconnect attempt {attempt}/{retries} failed: {e}")
                time.sleep(BLE_RECONNECT_DELAY)

        raise RuntimeError("[BLE] Could not reconnect after retries.")

    def disconnect(self):
        if self._loop:
            future = asyncio.run_coroutine_threadsafe(
                self._disconnect_async(), self._loop
            )
            try:
                future.result(timeout=10)
            except Exception:
                pass
            self._loop.call_soon_threadsafe(self._loop.stop)

    def is_connected(self):
        return self._connected and self._client is not None and self._client.is_connected

    def clear_buffer(self):
        with self._lock:
            self._buf.clear()

    def receive_payload(self, expected_size, timeout=BLE_RECV_TIMEOUT):
        """
        Waits for the nRF to deliver:
            "SIZE:<n>\n" header  +  <n> data bytes
        Returns (declared_size, received_bytes, rx_end_timestamp) or
                (0, b'', 'FAILED') on timeout/mismatch.
        """
        self.clear_buffer()
        deadline = time.time() + timeout

        # Phase 1: read header "SIZE:<n>\n"
        declared_size = None
        while time.time() < deadline:
            with self._lock:
                data = bytes(self._buf)
            nl = data.find(b'\n')
            if nl != -1:
                header = data[:nl].decode(errors='replace').strip()
                with self._lock:
                    del self._buf[:nl + 1]
                if header.startswith("SIZE:"):
                    try:
                        declared_size = int(header[5:])
                    except ValueError:
                        pass
                break
            time.sleep(0.005)

        if declared_size is None:
            print(f"  [!] BLE: header timeout for {expected_size}B")
            return 0, b'', 'FAILED'

        # Phase 2: accumulate exactly declared_size bytes
        while time.time() < deadline:
            with self._lock:
                got = len(self._buf)
            if got >= declared_size:
                break
            time.sleep(0.005)

        rx_end = datetime.now().isoformat(timespec="milliseconds")

        with self._lock:
            payload = bytes(self._buf[:declared_size])
            del self._buf[:declared_size]

        return declared_size, payload, rx_end


# --- PAYLOAD VERIFICATION -----------------------------------------------------
def verify_payload(payload, payload_size, index):
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


# --- EXPERIMENT ---------------------------------------------------------------
def run_experiment(run_number, attempt_number, meter, pico, ble):
    filename = os.path.join(
        OUT_DIR, f"{MODULE}_{STRATEGY}_run{run_number:02d}.csv"
    )
    meter_rows  = []
    event_rows  = []
    stop_meter  = threading.Event()
    set_phase("idle")

    highest_completed = 0

    try:
        attempt_tag = f" (attempt {attempt_number})" if attempt_number > 1 else ""
        print(f"\n[Run {run_number:02d}/{TOTAL_RUNS}]{attempt_tag} Waiting for Pico READY...")
        if not wait_for_pico(pico, "READY", timeout=60):
            print("[!] Pico did not send READY -- skipping run.")
            return False

        # Ensure BLE is connected before starting
        if not ble.is_connected():
            print("[BLE] Not connected -- reconnecting before run...")
            ble.reconnect()

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

        # Baseline
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
            print("[!] No START_IN -- aborting run.")
            pico.write(b"SKIP\n")
            stop_meter.set()
            m_thread.join(timeout=3)
            csv_file.close()
            return False

        w.writerow(["estimated_start", estimated_start.isoformat()])
        w.writerow(["start_delay_ms",  delay_ms])
        csv_file.flush()

        set_phase("idle")
        time.sleep(IDLE_S)

        skip_remaining = False

        for i, payload_size in enumerate(PAYLOAD_SIZES):
            if skip_remaining:
                break

            tx_start    = datetime.now().isoformat(timespec="milliseconds")
            skip_reason = ""
            print(f"  [->] {i+1}/{len(PAYLOAD_SIZES)} Waiting for {payload_size}B over BLE...")
            set_phase(f"tx_{payload_size}")

            declared, payload, rx_end = ble.receive_payload(
                payload_size,
                timeout=BLE_RECV_TIMEOUT
            )

            if rx_end == 'FAILED' or declared == 0:
                nrf_fail = False
                dl2 = time.time() + 2
                while time.time() < dl2:
                    if pico.in_waiting:
                        line = pico.readline().decode().strip()
                        if line:
                            print(f"[Pico] {line}")
                        if line.startswith("NRF_FAIL"):
                            nrf_fail    = True
                            skip_reason = "nrf_fail"
                            break
                    time.sleep(0.05)

                if not nrf_fail:
                    skip_reason = "ble_timeout"

                print(f"  [!] {payload_size}B failed ({skip_reason}) -- skipping remaining.")
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
            else:
                verified = verify_payload(payload, payload_size, i)
                complete = len(payload) == declared

                if verified:
                    print(f"  [+] {len(payload)}B verified at {rx_end}")
                    highest_completed = payload_size
                else:
                    print(f"  [x] {len(payload)}B FAILED at {rx_end}")

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

            set_phase("idle")
            if not skip_remaining:
                time.sleep(IDLE_S)

        # Drain any remaining Pico output (DONE, etc.)
        time.sleep(0.5)
        while pico.in_waiting:
            line = pico.readline().decode().strip()
            if line:
                print(f"[Pico] {line}")

        stop_meter.set()
        m_thread.join(timeout=3)
        csv_file.close()

        print(f"[Run {run_number:02d}] -> {filename}  "
              f"({len(meter_rows)} meter samples, {len(event_rows)} events)")
        print(f"[Run {run_number:02d}] Highest completed: {highest_completed}B "
              f"(threshold: {MIN_VALID_PAYLOAD}B)")

        return highest_completed >= MIN_VALID_PAYLOAD

    except Exception as e:
        print(f"[Run {run_number:02d}] Unexpected error: {e}")
        stop_meter.set()
        return False


# --- MAIN ---------------------------------------------------------------------
if __name__ == "__main__":
    meter = connect_meter()

    print("\n[Setup] Connecting to Pico...")
    print("        Close Arduino IDE completely before continuing.")
    try:
        pico = serial.Serial(PICO_PORT, PICO_BAUD, timeout=15)
    except serial.SerialException as e:
        if "Resource busy" in str(e):
            print("\n[!] Port busy -- close Arduino IDE and retry.")
        else:
            print(f"\n[!] Could not open Pico port: {e}")
        exit(1)

    time.sleep(2)
    pico.reset_input_buffer()

    # Connect BLE directly by address -- reconnects automatically between runs
    ble = BLEReceiver()
    print(f"\n[BLE] Connecting to nRF52840 @ {BLE_DEVICE_ADDRESS}...")
    print("      Ensure nRF is powered and advertising.")
    ble.connect()

    print(f"\nExperiment : {MODULE} | {STRATEGY}")
    print(f"Runs       : {TOTAL_RUNS}")
    print(f"Payloads   : {PAYLOAD_SIZES}")
    print(f"Min valid  : {MIN_VALID_PAYLOAD}B -- runs failing before this are retried")
    print(f"Session    : {SESSION_TAG}")
    print(f"Output     : {OUT_DIR}")
    input("\nPress ENTER to begin -> ")

    completed_runs = 0
    run_number     = 1

    try:
        while completed_runs < TOTAL_RUNS:
            attempt = 1
            while True:
                valid = run_experiment(run_number, attempt, meter, pico, ble)
                if valid:
                    print(f"[+] Run {run_number} accepted ({completed_runs + 1}/{TOTAL_RUNS}).\n")
                    completed_runs += 1
                    run_number += 1
                    break
                else:
                    print(f"[x] Run {run_number} failed before {MIN_VALID_PAYLOAD}B "
                          f"-- retrying (attempt {attempt + 1})...")
                    attempt += 1
                    time.sleep(5)

            if completed_runs < TOTAL_RUNS:
                # Cycle BLE connection between runs to reset stack state on both sides
                print("[BLE] Cycling connection between runs...")
                ble.reconnect()
                time.sleep(3)

    finally:
        ble.disconnect()
        pico.close()

    print(f"All {TOTAL_RUNS} valid runs complete.")