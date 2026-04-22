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


def send_cmd_read(ser, cmd, timeout=2.0):
    ser.reset_input_buffer()
    ser.write((cmd + "\r\n").encode())
    deadline = time.time() + timeout
    while time.time() < deadline:
        if ser.in_waiting:
            return ser.readline().decode(errors="ignore").strip()
        time.sleep(0.01)
    return None


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
            return False
    return True


def force_idle(ser):
    send_cmd(ser, "radio rxstop", delay=0.15)


def send_lora_payload(tx, payload_size, index):
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

            elif line == "radio_tx_ok":
                tx_end_ts = datetime.now().isoformat(timespec="milliseconds")
                got_tx = True
                break

    if not tx_end_ts:
        tx_end_ts = datetime.now().isoformat(timespec="milliseconds")

    duration = (
        datetime.fromisoformat(tx_end_ts) -
        datetime.fromisoformat(tx_cmd_ts)
    ).total_seconds() * 1000

    return {
        "tx_cmd_ts": tx_cmd_ts,
        "tx_start_ts": tx_start_ts or tx_cmd_ts, # if it fails before "ok"
        "tx_end_ts": tx_end_ts,
        "duration_ms": duration,
        "success": got_tx,
    }


def run_experiment(run_number, meter, tx):
    filename = os.path.join(OUT_DIR, f"run{run_number:02d}.csv")
    stop_meter = threading.Event()

    csv_file = open(filename, "w", newline="")
    w = csv.writer(csv_file)

    # Phase control
    phase_lock = threading.Lock()
    current_phase = {"value": "baseline"}

    # Event buffer
    event_rows = []

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

    # BASELINE
    with phase_lock:
        current_phase["value"] = "baseline"
    time.sleep(BASELINE_S)

    # PAYLOAD LOOP
    for i, size in enumerate(PAYLOAD_SIZES):
        with phase_lock:
            current_phase["value"] = f"tx_{size}"

        result = send_lora_payload(tx, size, i)

        event_rows.append([
            size,
            result["tx_cmd_ts"],
            result["tx_start_ts"],
            result["tx_end_ts"],
            f"{result['duration_ms']:.3f}",
            result["success"],
        ])

        with phase_lock:
            current_phase["value"] = "idle"

        time.sleep(IDLE_S)

    # Stop meter
    stop_meter.set()
    t.join(timeout=2)

    # EVENTS (written AFTER meter stops)
    w.writerow([])
    w.writerow(["# EVENTS"])
    w.writerow([
        "payload_size", "tx_cmd_ts", "tx_start_ts",
        "tx_end_ts", "duration_ms", "success"
    ])

    for row in event_rows:
        w.writerow(row)

    csv_file.close()
    print(f"[Run {run_number}] Saved → {filename}")


# ─── MAIN ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    meter = connect_meter()

    tx = serial.Serial(TX_PORT, BAUD, timeout=2)
    time.sleep(1.5)
    send_cmd_read(tx, "sys reset", timeout=3.0)
    time.sleep(1.5)

    if not configure_radio(tx, "TX"):
        raise SystemExit("TX config failed")

    input("Press ENTER to start")

    for run in range(1, TOTAL_RUNS + 1):
        run_experiment(run, meter, tx)
        time.sleep(2)

    tx.close()