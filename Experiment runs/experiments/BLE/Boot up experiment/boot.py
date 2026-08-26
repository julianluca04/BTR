import pyvisa
import csv
import os
import sys
import select
import time
import threading
import asyncio
from datetime import datetime
from bleak import BleakScanner

# ─── CONFIG ───────────────────────────────────────────────────────────────────
MODULE           = "ble_nrf52"
MEASUREMENT      = "boot"
TOTAL_BOOTS      = 30
SHUNT_OHMS       = 1.1
NRF_ADDRESS      = "1385E324-4660-24ED-9B2E-A55F8DF154AE"
BLE_SCAN_TIMEOUT = 30    # seconds to wait for BLE advertising before manual fallback
SETTLE_TAIL_S    = 1.5   # extra recording after BLE detected to capture settled current
SCRIPT_DIR       = os.path.dirname(os.path.abspath(__file__))
SESSION_TAG      = datetime.now().strftime("%Y%m%d_%H%M%S")
OUT_DIR          = os.path.join(SCRIPT_DIR, "data", MODULE, MEASUREMENT, SESSION_TAG)
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

def enter_pressed():
    return select.select([sys.stdin], [], [], 0)[0] != []

def drain_enter():
    while select.select([sys.stdin], [], [], 0)[0]:
        sys.stdin.readline()

def record_boot(meter, boot_number, unplug_time):
    filename = os.path.join(
        OUT_DIR, f"{MODULE}_{MEASUREMENT}_boot{boot_number:02d}.csv"
    )

    print(f"\n[Boot {boot_number:02d}/{TOTAL_BOOTS}]")
    print(f"  Output: {filename}")
    print(f"  [Unplug marked at {unplug_time}]")
    print(f"  Replug nRF52 now. Watching for BLE advertising ({NRF_ADDRESS})...")
    print(f"  (Press ENTER to mark settled manually if BLE detection fails)")

    csv_file = open(filename, "w", newline="")
    w = csv.writer(csv_file)

    w.writerow(["# META"])
    w.writerow(["module",      MODULE])
    w.writerow(["measurement", MEASUREMENT])
    w.writerow(["boot_number", boot_number])
    w.writerow(["session",     SESSION_TAG])
    w.writerow(["shunt_ohms",  f"{SHUNT_OHMS:.4f}"])
    w.writerow([])
    w.writerow(["# DATA"])
    w.writerow(["type", "timestamp_or_event", "value_or_time", "boot_number"])
    w.writerow([])

    w.writerow(["EVENT", "unplug", unplug_time, boot_number])
    csv_file.flush()

    drain_enter()

    # ── Shared events ────────────────────────────────────────────────────────
    stop_meter = threading.Event()
    settled    = threading.Event()   # set by BLE thread or manual ENTER
    ble_found  = threading.Event()   # set only when BLE advertising detected
    sample_count = [0]

    # ── Meter recording thread ───────────────────────────────────────────────
    def meter_loop():
        while not stop_meter.is_set():
            try:
                raw = meter.query("READ?").strip()
                ts  = datetime.now().isoformat(timespec="milliseconds")
                w.writerow(["METER", ts, raw, boot_number])
                csv_file.flush()
                sample_count[0] += 1
            except Exception as e:
                print(f"  [Meter] Read error: {e}")
                time.sleep(0.1)

    # ── BLE scan thread ──────────────────────────────────────────────────────
    def ble_scan():
        async def _find():
            return await BleakScanner.find_device_by_address(
                NRF_ADDRESS, timeout=BLE_SCAN_TIMEOUT
            )
        device = asyncio.run(_find())
        if device is not None:
            ble_found.set()
            settled.set()

    m_thread = threading.Thread(target=meter_loop, daemon=True)
    b_thread = threading.Thread(target=ble_scan,   daemon=True)
    m_thread.start()
    b_thread.start()

    # ── Wait for BLE detection or manual ENTER ───────────────────────────────
    while not settled.is_set():
        if enter_pressed():
            sys.stdin.readline()
            settled.set()
            break
        time.sleep(0.05)

    # Keep recording briefly to capture settled advertising current
    time.sleep(SETTLE_TAIL_S)
    stop_meter.set()
    m_thread.join(timeout=3)

    settled_time = datetime.now().isoformat(timespec="milliseconds")
    w.writerow(["EVENT", "settled", settled_time, boot_number])
    csv_file.flush()
    csv_file.close()

    if ble_found.is_set():
        print(f"  [BLE] Advertising detected — safe to unplug now!")
    else:
        print(f"  [Manual] Settled marked by ENTER.")
    print(f"  [✓] Boot settled at {settled_time} — {sample_count[0]} samples recorded.")
    print(f"  [✓] Saved to {filename}")

if __name__ == "__main__":
    meter = connect_meter()

    print(f"\nBoot measurement: {MODULE}")
    print(f"Boots           : {TOTAL_BOOTS}")
    print(f"Session         : {SESSION_TAG}")
    print(f"Output dir      : {OUT_DIR}")
    print(f"\nWorkflow per boot:")
    print(f"  1. Unplug nRF52, press ENTER to mark unplug")
    print(f"  2. Replug nRF52 — laptop auto-detects BLE advertising")
    print(f"  3. 'Safe to unplug' appears automatically when device is ready")
    print(f"  4. Unplug again when prompted, repeat")
    input("\nPress ENTER to begin → ")

    print(f"\n  Unplug the nRF52 now, then press ENTER.")
    drain_enter()
    input("  → ")
    unplug_time = datetime.now().isoformat(timespec="milliseconds")

    for boot in range(1, TOTAL_BOOTS + 1):
        record_boot(meter, boot, unplug_time)
        print(f"[✓] Boot {boot}/{TOTAL_BOOTS} complete.\n")
        if boot < TOTAL_BOOTS:
            print(f"  Unplug the nRF52 now for boot {boot + 1}, then press ENTER.")
            drain_enter()
            input("  → ")
            unplug_time = datetime.now().isoformat(timespec="milliseconds")

    print(f"\nAll {TOTAL_BOOTS} boots recorded → {OUT_DIR}")
