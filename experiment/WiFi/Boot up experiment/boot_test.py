import pyvisa
import csv
import os
import time
from datetime import datetime

# ─── CONFIG ───────────────────────────────────────────────────────────────────
MODULE        = "esp32"
MEASUREMENT   = "boot"
TOTAL_BOOTS   = 30
SHUNT_OHMS    = 1.1
SCRIPT_DIR    = os.path.dirname(os.path.abspath(__file__))
SESSION_TAG   = datetime.now().strftime("%Y%m%d_%H%M%S")
OUT_DIR       = os.path.join(SCRIPT_DIR, "data", MODULE, MEASUREMENT, SESSION_TAG)
os.makedirs(OUT_DIR, exist_ok=True)
# ──────────────────────────────────────────────────────────────────────────────

def connect_meter():
    rm = pyvisa.ResourceManager('@py')
    resources = rm.list_resources()
    print(f"[Meter] Found: {resources}")
    hmc = next((r for r in resources if r.startswith("USB")), None)
    if not hmc:
        raise RuntimeError(f"HMC8012 not found. Available: {resources}")
    m = rm.open_resource(hmc)
    m.timeout = 10000
    idn = m.query('*IDN?').strip()
    print(f"[Meter] {idn}")

    m.write("CONF:VOLT:DC")
    m.write("SENS:VOLT:DC:RANG:AUTO ON")
    m.write("SENS:VOLT:DC:NPLC 0.02")
    m.write("TRIG:SOUR IMM")
    m.write("TRIG:COUN INF")

    print("[Meter] Warming up...")
    deadline = time.time() + 2.0
    while time.time() < deadline:
        try:
            m.query("READ?")
        except Exception:
            pass
    print("[Meter] Ready.")
    return m

def meter_readline(meter):
    try:
        raw = meter.query("READ?").strip()
        ts  = datetime.now().isoformat(timespec="milliseconds")
        return ts, raw
    except Exception as e:
        return None, None

def record_boot(meter, boot_number, csv_writer, csv_file):
    print(f"\n[Boot {boot_number:02d}/{TOTAL_BOOTS}]")
    print(f"  Meter is recording.")
    print(f"  Unplug Pico now, then press ENTER.")
    input("  → ")

    unplug_time = datetime.now().isoformat(timespec="milliseconds")
    csv_writer.writerow(["EVENT", "unplug", unplug_time, boot_number])
    csv_file.flush()
    print(f"  [Unplug marked at {unplug_time}]")
    print(f"  Replug Pico now. Watch for esp32_test WiFi or serial output.")
    print(f"  When fully settled, press ENTER to mark end of boot.")

    # Record continuously until user confirms boot is complete
    samples = 0
    stop = False

    import threading
    def wait_for_enter():
        nonlocal stop
        input("  → ")
        stop = True

    t = threading.Thread(target=wait_for_enter, daemon=True)
    t.start()

    # Record from unplug through replug through full boot settle
    while not stop:
        ts, raw = meter_readline(meter)
        if ts and raw:
            csv_writer.writerow(["METER", ts, raw, boot_number])
            samples += 1

    settled_time = datetime.now().isoformat(timespec="milliseconds")
    csv_writer.writerow(["EVENT", "settled", settled_time, boot_number])
    csv_file.flush()

    print(f"  [✓] Boot settled at {settled_time} — {samples} samples recorded.")

if __name__ == "__main__":
    meter = connect_meter()

    filename = os.path.join(OUT_DIR, f"{MODULE}_{MEASUREMENT}_{SESSION_TAG}.csv")
    csv_file = open(filename, "w", newline="")
    w = csv.writer(csv_file)

    # Header
    w.writerow(["# META"])
    w.writerow(["module",      MODULE])
    w.writerow(["measurement", MEASUREMENT])
    w.writerow(["boots",       TOTAL_BOOTS])
    w.writerow(["session",     SESSION_TAG])
    w.writerow(["shunt_ohms",  f"{SHUNT_OHMS:.4f}"])
    w.writerow([])
    w.writerow(["# DATA"])
    w.writerow(["type", "timestamp_or_event", "value_or_time", "boot_number"])
    w.writerow([])
    csv_file.flush()

    print(f"\nBoot measurement: {MODULE}")
    print(f"Boots           : {TOTAL_BOOTS}")
    print(f"Session         : {SESSION_TAG}")
    print(f"Output          : {filename}")
    print(f"\nWorkflow per boot:")
    print(f"  1. Meter records continuously the whole time")
    print(f"  2. Unplug Pico, press ENTER to mark unplug")
    print(f"  3. Replug Pico immediately after")
    print(f"  4. Watch current settle — wait until esp32_test appears or current flatlines")
    print(f"  5. Press ENTER to mark settled, then repeat")
    input("\nPress ENTER to begin → ")

    for boot in range(1, TOTAL_BOOTS + 1):
        record_boot(meter, boot, w, csv_file)
        print(f"[✓] Boot {boot}/{TOTAL_BOOTS} complete.\n")
        if boot < TOTAL_BOOTS:
            time.sleep(1)

    csv_file.close()
    print(f"\nAll {TOTAL_BOOTS} boots recorded → {filename}")