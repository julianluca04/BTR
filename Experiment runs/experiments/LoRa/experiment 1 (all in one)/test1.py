import pyvisa
import csv
import os
import serial
import threading
import time
from datetime import datetime

# ─── CONFIG ───────────────────────────────────────────────────────────────────
MODULE        = "LoRa"
STRATEGY      = "full_payload"
TOTAL_RUNS    = 30
PAYLOAD_SIZES = [1, 2, 4, 8, 16, 32, 64, 128, 220]

TX_PORT = "/dev/cu.usbmodem141301"
RX_PORT = "/dev/cu.usbmodem143201"
BAUD    = 57600

IDLE_S         = 1.0
BASELINE_S     = 5.0
METER_WARMUP_S = 2.0
RX_SETTLE_S    = 30.0  # RX module needs 30s to settle after radio rx 0
RX_WDT_S       = 1.1   # RX watchdog interval before next rx 0 can be sent

# Shunt on USB cable red wire (5V side, before onboard regulator)
SHUNT_OHMS = 1.1
V_SUPPLY   = 5.0  

LORA_FREQ = "915000000"
LORA_SF   = "sf7"
LORA_BW   = "125"
LORA_CR   = "4/5"
LORA_PWR  = "14"

SCRIPT_DIR  = os.path.dirname(os.path.abspath(__file__))
SESSION_TAG = datetime.now().strftime("%Y%m%d_%H%M%S")
OUT_DIR     = os.path.join(SCRIPT_DIR, "data", MODULE, STRATEGY, SESSION_TAG)
os.makedirs(OUT_DIR, exist_ok=True)
# ──────────────────────────────────────────────────────────────────────────────


def connect_meter():
    rm = pyvisa.ResourceManager('@py')

    def reopen_meter(retries=5, delay=1.0):
        for attempt in range(retries):
            try:
                resources = rm.list_resources()
                hmc = next((r for r in resources if r.startswith("USB")), None)
                if not hmc:
                    raise RuntimeError(f"HMC8012 not found. Available: {resources}")
                m = rm.open_resource(hmc)
                m.timeout = 10000
                print(f"[Meter] {m.query('*IDN?').strip()}")
                return m
            except Exception as e:
                print(f"[Meter] Retry {attempt+1}: {e}")
                time.sleep(delay)
        raise RuntimeError("Meter not found.")

    meter = reopen_meter()
    meter.write("CONF:VOLT:DC")
    meter.write("SENS:VOLT:DC:RANG:AUTO ON")
    meter.write("SENS:VOLT:DC:NPLC 0.02")
    meter.write("TRIG:SOUR IMM")
    meter.write("TRIG:COUN INF")

    print("[Meter] Warming up...")
    t_end = time.time() + METER_WARMUP_S
    while time.time() < t_end:
        try:
            meter.query("READ?")
        except:
            pass

    return meter


def meter_stream(meter, stop_event, callback):
    while not stop_event.is_set():
        try:
            raw = meter.query("READ?").strip()
            ts = datetime.now().isoformat(timespec="milliseconds")
            callback(ts, raw)
        except Exception:
            time.sleep(0.2)


def send_cmd(ser, cmd, delay=0.1):
    ser.reset_input_buffer()
    ser.write((cmd + "\r\n").encode())
    time.sleep(delay)


def send_cmd_read(ser, cmd, timeout=2.0, pause_event=None):
    if pause_event is not None:
        pause_event.set()
        time.sleep(0.05)

    try:
        ser.reset_input_buffer()
        ser.write((cmd + "\r\n").encode())
        deadline = time.time() + timeout
        while time.time() < deadline:
            if ser.in_waiting:
                return ser.readline().decode(errors="ignore").strip()
            time.sleep(0.01)
        return None
    finally:
        if pause_event is not None:
            pause_event.clear()


def configure_radio(ser, label="module"):
    steps = [
        ("mac pause", None),
        ("radio set mod lora", "ok"),
        (f"radio set freq {LORA_FREQ}", "ok"),
        (f"radio set sf {LORA_SF}", "ok"),
        (f"radio set bw {LORA_BW}", "ok"),
        (f"radio set cr {LORA_CR}", "ok"),
        (f"radio set pwr {LORA_PWR}", "ok"),
        ("radio set crc on", "ok"),
    ]
    for cmd, expected in steps:
        resp = send_cmd_read(ser, cmd)
        if expected and (not resp or expected not in resp):
            print(f"[{label}] Config failed on '{cmd}': got '{resp}'")
            return False
    return True


def configure_receiver(ser, label="module"):
    steps = [
        ("mac pause", None),
        ("radio set mod lora", "ok"),
        (f"radio set freq {LORA_FREQ}", "ok"),
        (f"radio set sf {LORA_SF}", "ok"),
        (f"radio set bw {LORA_BW}", "ok"),
        (f"radio set cr {LORA_CR}", "ok"),
        (f"radio set pwr {LORA_PWR}", "ok"),
        ("radio set crc on", "ok"),
        ("radio set wdt 1", "ok"),
    ]
    for cmd, expected in steps:
        resp = send_cmd_read(ser, cmd)
        if expected and (not resp or expected not in resp):
            print(f"[{label}] Config failed on '{cmd}': got '{resp}'")
            return False
    return True


def force_idle(ser):
    send_cmd(ser, "radio rxstop", delay=0.15)


def send_lora_payload(tx, payload_size, index, phase_lock=None, current_phase=None):
    payload = bytes([ord('0') + (index % 10)] * payload_size)
    hex_payload = payload.hex().upper()

    force_idle(tx)

    tx_cmd_ts = datetime.now().isoformat(timespec="milliseconds")
    tx.write((f"radio tx {hex_payload}\r\n").encode())

    tx_start_ts = None
    tx_end_ts = None
    got_tx = False
    deadline = time.time() + 15

    while time.time() < deadline:
        if tx.in_waiting:
            line = tx.readline().decode(errors="ignore").strip()

            if line == "ok":
                tx_start_ts = datetime.now().isoformat(timespec="milliseconds")
                # Update phase when we receive "ok" for accurate timing
                if phase_lock and current_phase:
                    with phase_lock:
                        current_phase["value"] = f"tx_{payload_size}"

            elif line == "radio_tx_ok": 
                tx_end_ts = datetime.now().isoformat(timespec="milliseconds")
                got_tx = True
                break

    if not tx_end_ts:
        tx_end_ts = datetime.now().isoformat(timespec="milliseconds")

    duration = (
        datetime.fromisoformat(tx_end_ts) -
        datetime.fromisoformat(tx_start_ts)
    ).total_seconds() * 1000

    return {
        "tx_cmd_ts": tx_cmd_ts,
        "tx_start_ts": tx_start_ts or tx_cmd_ts,
        "tx_end_ts": tx_end_ts,
        "duration_ms": duration,
        "success": got_tx,
    }


def verify_payload(payload: bytes, expected_size: int, index: int):
    expected_byte = ord('0') + (index % 10)

    if len(payload) != expected_size:
        return False, "size_mismatch"

    wrong = sum(1 for b in payload if b != expected_byte)
    if wrong > 0:
        return False, f"{wrong}_bytes_wrong"

    return True, "ok"


def receiver_loop(rx, stop_event, rx_results, rx_lock, pause_event):
    """Read RX port continuously. No blocking - returns when stop_event is set."""
    print("[RX] Receiver started")

    while not stop_event.is_set():
        if pause_event.is_set():
            time.sleep(0.01)
            continue

        try:
            if rx.in_waiting:
                line = rx.readline().decode(errors="ignore").strip()

                if not line:
                    time.sleep(0.01)
                    continue

                # Skip command responses
                if line in ["ok", "radio_err", "radio_rx_timeout", "invalid_param"]:
                    continue

                print(f"[RX] {line}")

                if line.startswith("radio_rx"):
                    try:
                        hex_data = line.split(" ", 1)[1]
                        payload = bytes.fromhex(hex_data)

                        with rx_lock:
                            rx_results.append({
                                "timestamp": datetime.now().isoformat(timespec="milliseconds"),
                                "payload": payload
                            })
                    except Exception as e:
                        print(f"[RX] Decode error: {e}")

            else:
                time.sleep(0.01)
        except Exception as e:
            print(f"[RX] Error: {e}")
            time.sleep(0.1)

    print("[RX] Receiver stopped")


def run_experiment(run_number, meter, tx, rx):
    filename = os.path.join(OUT_DIR, f"run{run_number:02d}.csv")
    stop_meter = threading.Event()

    csv_file = open(filename, "w", newline="")
    w = csv.writer(csv_file)

    # Phase control
    phase_lock = threading.Lock()
    current_phase = {"value": "baseline"}

    # Event buffer
    event_rows = []

    # RX buffer
    rx_results = []
    rx_lock = threading.Lock()

    # META
    w.writerow(["# META"])
    w.writerow(["run", run_number])
    w.writerow(["session", SESSION_TAG])
    w.writerow([])

    # METER HEADER
    w.writerow(["# METER"])
    w.writerow(["timestamp", "voltage_v", "phase"])
    csv_file.flush()

    def on_sample(ts, raw):
        with phase_lock:
            phase = current_phase["value"]
        w.writerow([ts, raw, phase])

    # Start meter thread
    t = threading.Thread(
        target=meter_stream,
        args=(meter, stop_meter, on_sample),
        daemon=True
    )
    t.start()

    # Start RX thread
    rx_stop = threading.Event()
    rx_pause_event = threading.Event()
    rx_thread = threading.Thread(
        target=receiver_loop,
        args=(rx, rx_stop, rx_results, rx_lock, rx_pause_event),
        daemon=True
    )
    rx_thread.start()

    # Setup RX: put it into receive mode and wait for settlement
    print("[Setup] Configuring RX for initial reception...")
    send_cmd_read(rx, "radio rx 0", timeout=1.0, pause_event=rx_pause_event)
    
    print(f"[Setup] Waiting {RX_SETTLE_S}s for RX module to settle...")
    with phase_lock:
        current_phase["value"] = "rx_settling"
    time.sleep(RX_SETTLE_S)

    # BASELINE
    with phase_lock:
        current_phase["value"] = "baseline"
    time.sleep(BASELINE_S)

    # PAYLOAD LOOP
    for i, size in enumerate(PAYLOAD_SIZES):
        # Prepare RX for this payload
        print(f"[Payload {i+1}] Starting RX settle before transmission...")
        send_cmd_read(rx, "radio rx 0", timeout=1.0, pause_event=rx_pause_event)
        
        print(f"[Payload {i+1}] Waiting {RX_SETTLE_S}s for RX to settle...")
        with phase_lock:
            current_phase["value"] = f"rx_settling_{size}"
        time.sleep(RX_SETTLE_S)

        with rx_lock:
            rx_results.clear()

        result = send_lora_payload(tx, size, i, phase_lock, current_phase)

        # Wait for RX to capture the packet
        rx_timeout = time.time() + 3.0
        payload = None
        verified = False
        reason = "no_rx"

        while time.time() < rx_timeout:
            with rx_lock:
                if rx_results:
                    entry = rx_results.pop(0)
                    payload = entry["payload"]
                    break
            time.sleep(0.01)

        if payload:
            verified, reason = verify_payload(payload, size, i)

        event_rows.append([
            size,
            result["tx_cmd_ts"],
            result["tx_start_ts"],
            result["tx_end_ts"],
            f"{result['duration_ms']:.3f}",
            result["success"],
            verified,
            reason
        ])

        print(f"[Payload {i+1}] size={size}, tx_ok={result['success']}, rx_ok={verified} ({reason})")

        with phase_lock:
            current_phase["value"] = "idle"

        time.sleep(max(IDLE_S, RX_WDT_S))

    # Stop RX thread
    rx_stop.set()
    rx_thread.join(timeout=2)

    # Stop meter
    stop_meter.set()
    t.join(timeout=2)

    # EVENTS (written AFTER threads stop)
    w.writerow([])
    w.writerow(["# EVENTS"])
    w.writerow([
        "payload_size", "tx_cmd_ts", "tx_start_ts",
        "tx_end_ts", "duration_ms", "tx_success",
        "rx_verified", "rx_status"
    ])

    for row in event_rows:
        w.writerow(row)

    csv_file.close()
    print(f"[Run {run_number}] Saved → {filename}")


# ─── MAIN ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    meter = connect_meter()

    # Setup TX
    tx = serial.Serial(TX_PORT, BAUD, timeout=2)
    time.sleep(1.5)
    send_cmd_read(tx, "sys reset", timeout=3.0)
    time.sleep(1.5)

    if not configure_radio(tx, "TX"):
        raise SystemExit("TX config failed")

    # Setup RX
    rx = serial.Serial(RX_PORT, BAUD, timeout=2)
    time.sleep(1.5)
    send_cmd_read(rx, "sys reset", timeout=3.0)
    time.sleep(1.5)

    if not configure_receiver(rx, "RX"):
        raise SystemExit("RX config failed")

    input("Press ENTER to start")

    for run in range(1, TOTAL_RUNS + 1):
        run_experiment(run, meter, tx, rx)
        time.sleep(2)

    tx.close()
    rx.close()
