import pyvisa
import csv
import os
import serial
import threading
import time
from datetime import datetime, timedelta

# ─── CONFIG ───────────────────────────────────────────────────────────────────
MODULE        = "LoRa"
STRATEGY      = "full_payload"
TOTAL_RUNS    = 30
PAYLOAD_SIZES = [
    1, 2, 4, 8, 16, 32, 64, 128, 220
] #gotta edit the data sizes 
# 256, 512, 1024, 2048, 4096, 8192, 16384, 32768, 65536, 131072, 262144, 524288, 1048576

PICO_PORT      = "/dev/cu.usbmodem143301"
PICO_BAUD      = 115200

RX_PORT = "/dev/cu.usbmodem141201"  # <-- receiver RN2903
RX_BAUD = 57600

IDLE_S         = 1.0
BASELINE_S     = 5.0
METER_WARMUP_S = 2.0

SHUNT_OHMS = 1.1
V_SUPPLY   = 3.3

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
        nplc = meter.query("SENS:RES:NPLC?").strip()
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


def send_cmd(pico, cmd):
    pico.write((cmd + "\r\n").encode())
    time.sleep(0.05)

def wait_for(pico, expected, timeout=5):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if pico.in_waiting:
            line = pico.readline().decode().strip()
            print(f"[RN2903] {line}")
            if expected in line:
                return True
    return False


def send_lora_payload(pico, payload_size, index):
    # Create payload
    byte = ord('0') + (index % 10)
    payload = bytes([byte] * payload_size)
    hex_payload = payload.hex().upper()

    # Ensure TX mode
    send_cmd(pico, "radio rxstop")

    # Send TX command
    send_cmd(pico, f"radio tx {hex_payload}")

    start = datetime.now()

    got_ok = False
    got_tx = False

    deadline = time.time() + 10

    while time.time() < deadline:
        if pico.in_waiting:
            line = pico.readline().decode().strip()
            print(f"[RN2903] {line}")

            if line == "ok":
                got_ok = True
            elif line == "radio_tx_ok":
                got_tx = True
                break
            elif "invalid_param" in line:
                raise RuntimeError("Payload too large")

    end = datetime.now()

    return {
        "duration_ms": (end - start).total_seconds() * 1000,
        "success": got_tx
    }




def run_experiment(run_number, meter, pico):
    filename = os.path.join(OUT_DIR, f"run{run_number:02d}.csv")

    meter_rows = []
    stop_meter = threading.Event()

    csv_file = open(filename, "w", newline="")
    w = csv.writer(csv_file)

    # META
    w.writerow(["# META"])
    w.writerow(["run", run_number])
    w.writerow(["session", SESSION_TAG])
    w.writerow([])

    # EVENTS
    w.writerow(["# EVENTS"])
    w.writerow(["payload_size", "duration_ms", "success"])
    w.writerow([])

    # METER
    w.writerow(["# METER"])
    w.writerow(["timestamp", "value", "phase"])

    def flush(entry):
        w.writerow([entry["timestamp"], entry["value"], entry["phase"]])
        csv_file.flush()

    # Start meter thread
    set_phase("baseline")
    t = threading.Thread(
        target=meter_stream,
        args=(meter, meter_rows, stop_meter, flush),
        daemon=True
    )
    t.start()


    print(f"[Run {run_number}] Baseline...")
    time.sleep(BASELINE_S)

    for i, size in enumerate(PAYLOAD_SIZES):
        print(f"  [→] {size} bytes")
        set_phase(f"tx_{size}")

        try:
            result = send_lora_payload(pico, size, i)

            print(f"  [✓] {size}B in {result['duration_ms']:.1f} ms")

            w.writerow([size, result["duration_ms"], result["success"]])
            csv_file.flush()

        except Exception as e:
            print(f"  [!] Failed: {e}")
            break

        set_phase("idle")
        time.sleep(IDLE_S)

    stop_meter.set()
    t.join(timeout=2)
    csv_file.close()

    print(f"[Run {run_number}] saved → {filename}")


def send_cmd_dev(dev, cmd):
    dev.write((cmd + "\r\n").encode())
    time.sleep(0.05)


def receiver_loop(rx, stop_event):
    print("[RX] Receiver thread started")

    # Initial RX mode
    send_cmd_dev(rx, "sys reset")
    time.sleep(1)

    send_cmd_dev(rx, "mac pause")
    send_cmd_dev(rx, "radio set mod lora")
    send_cmd_dev(rx, "radio set freq 868100000")
    send_cmd_dev(rx, "radio set sf sf7")
    send_cmd_dev(rx, "radio set bw 125")
    send_cmd_dev(rx, "radio set cr 4/5")
    send_cmd_dev(rx, "radio set crc on")

    send_cmd_dev(rx, "radio rx 0")

    while not stop_event.is_set():
        if rx.in_waiting:
            line = rx.readline().decode(errors="ignore").strip()
            if line:
                print(f"[RX] {line}")

                # If packet received → restart RX
                if line.startswith("radio_rx"):
                    send_cmd_dev(rx, "radio rx 0")

        else:
            time.sleep(0.01)

    print("[RX] Receiver thread stopped")




if __name__ == "__main__":
    meter = connect_meter()

    pico = serial.Serial(PICO_PORT, PICO_BAUD, timeout=1)
    time.sleep(2)
    pico.reset_input_buffer()

    rx = serial.Serial(RX_PORT, RX_BAUD, timeout=1)
    time.sleep(2)
    rx.reset_input_buffer()

    # Start RX thread
    rx_stop = threading.Event()
    rx_thread = threading.Thread(
        target=receiver_loop,
        args=(rx, rx_stop),
        daemon=True
    )
    rx_thread.start()

    # TX config
    print("[Setup] Configuring TX RN2903...")

    send_cmd(pico, "sys reset")
    time.sleep(1)

    send_cmd(pico, "mac pause")
    send_cmd(pico, "radio set mod lora")
    send_cmd(pico, "radio set freq 868100000")
    send_cmd(pico, "radio set sf sf7")
    send_cmd(pico, "radio set bw 125")
    send_cmd(pico, "radio set cr 4/5")
    send_cmd(pico, "radio set pwr 14")
    send_cmd(pico, "radio set crc on")

    input("\nPress ENTER to start experiment → ")

    for run in range(1, TOTAL_RUNS + 1):
        run_experiment(run, meter, pico)
        time.sleep(2)

    # Cleanup
    rx_stop.set()
    rx_thread.join(timeout=2)

    pico.close()
    rx.close()

    print("All runs complete.")