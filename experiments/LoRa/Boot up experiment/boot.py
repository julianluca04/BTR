import serial
import pyvisa
import csv
import os
import time
from datetime import datetime

# ─── CONFIG ───────────────────────────────────────────────────────────────────
MODULE        = "LoRa"
MEASUREMENT   = "boot"
TOTAL_BOOTS   = 30
SHUNT_OHMS    = 1.1

RECORD_TIME_S = 4.0   # automatic capture window, spikes basically immediately settles super quick so 4s is more than enough

LORA_PORT = "/dev/cu.usbmodem141301"
BAUD      = 57600

SCRIPT_DIR  = os.path.dirname(os.path.abspath(__file__))
SESSION_TAG = datetime.now().strftime("%Y%m%d_%H%M%S")
OUT_DIR     = os.path.join(SCRIPT_DIR, "data", MODULE, MEASUREMENT, SESSION_TAG)
os.makedirs(OUT_DIR, exist_ok=True)
# ──────────────────────────────────────────────────────────────────────────────


def connect_meter():
    rm = pyvisa.ResourceManager('@py')
    resources = rm.list_resources()
    print(f"[Meter] Found: {resources}")

    hmc = next((r for r in resources if r.startswith("USB")), None)
    if not hmc:
        raise RuntimeError("HMC8012 not found")

    m = rm.open_resource(hmc)
    m.timeout = 10000

    print(f"[Meter] {m.query('*IDN?').strip()}")

    # IMPORTANT: voltage mode (you fixed this earlier)
    m.write("CONF:VOLT:DC")
    m.write("SENS:VOLT:DC:RANG:AUTO ON")
    m.write("SENS:VOLT:DC:NPLC 0.02")
    m.write("TRIG:SOUR IMM")
    m.write("TRIG:COUN INF")

    print("[Meter] Warming up...")
    t_end = time.time() + 2
    while time.time() < t_end:
        try:
            m.query("READ?")
        except:
            pass

    print("[Meter] Ready.")
    return m


def record_boot(meter, lora, boot_number):
    filename = os.path.join(
        OUT_DIR, f"{MODULE}_{MEASUREMENT}_boot{boot_number:02d}.csv"
    )

    print(f"\n[Boot {boot_number:02d}/{TOTAL_BOOTS}]")
    print(f"[→] Press ENTER to reset LoRa")

    input()

    csv_file = open(filename, "w", newline="")
    w = csv.writer(csv_file)

    # META
    w.writerow(["# META"])
    w.writerow(["module", MODULE])
    w.writerow(["measurement", MEASUREMENT])
    w.writerow(["boot_number", boot_number])
    w.writerow(["session", SESSION_TAG])
    w.writerow(["shunt_ohms", SHUNT_OHMS])
    w.writerow([])

    # DATA
    w.writerow(["# DATA"])
    w.writerow(["type", "timestamp", "value", "boot"])
    w.writerow([])

    # Trigger reset
    boot_time = datetime.now().isoformat(timespec="milliseconds")
    w.writerow(["EVENT", "reset", boot_time, boot_number])

    lora.reset_input_buffer()
    lora.write(b"sys reset\r\n")

    print("[→] Boot triggered, recording...")

    start = time.time()
    samples = 0

    while True:
        # meter sample
        try:
            raw = meter.query("READ?").strip()
            ts  = datetime.now().isoformat(timespec="milliseconds")
            w.writerow(["METER", ts, raw, boot_number])
            samples += 1
        except:
            time.sleep(0.05)

        # optional: read LoRa boot messages (useful debug)
        if lora.in_waiting:
            line = lora.readline().decode(errors="ignore").strip()
            if line:
                print(f"[LoRa] {line}")

        # stop condition (automatic)
        if time.time() - start > RECORD_TIME_S:
            break

    settled_time = datetime.now().isoformat(timespec="milliseconds")
    w.writerow(["EVENT", "settled", settled_time, boot_number])

    csv_file.close()

    print(f"[✓] Boot recorded ({samples} samples)")
    print(f"    Saved → {filename}")


# ─── MAIN ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    meter = connect_meter()

    lora = serial.Serial(LORA_PORT, BAUD, timeout=1)
    time.sleep(2)

    print(f"\nLoRa boot experiment")
    print(f"Boots: {TOTAL_BOOTS}")
    print(f"Record window: {RECORD_TIME_S}s")
    print(f"Output: {OUT_DIR}")

    input("\nPress ENTER to begin → ")

    for boot in range(1, TOTAL_BOOTS + 1):
        record_boot(meter, lora, boot)
        time.sleep(1)

    lora.close()
    print("\nAll boots complete.")