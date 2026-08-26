"""
shortcircuit.py — Noise Floor Calibration Run
===============================================
Records meter samples for 10 minutes with probes shorted (no module connected).
Output: analyze_data/shortcircuit.csv

WHAT TO DO:
  1. Disconnect everything from the shunt resistor.
  2. Short the two probes together directly (clip them to each other).
  3. Run this script. It will sample for 10 minutes continuously.
  4. Place the output CSV in your analyze_data/ folder alongside your experiment CSVs.

The analyze_experiments.py script will automatically find and use it.
"""

import csv
import sys
import time
import threading
from datetime import datetime
from pathlib import Path

import numpy as np
import pyvisa

# ── Config ────────────────────────────────────────────────────────────────────
DURATION_S      = 600          # 10 minutes
KEEPALIVE_EVERY = 2.0          # seconds between keepalive READ? pings
OUTPUT_PATH     = Path(__file__).parent / "analyze_data" / "shortcircuit.csv"

# HMC8012 identity string fragment for auto-detection
METER_ID_FRAGMENT = "HMC8012"


# ── Meter connection ──────────────────────────────────────────────────────────
def find_meter(rm: pyvisa.ResourceManager) -> pyvisa.Resource:
    resources = rm.list_resources()
    print(f"[Meter] Scanning: {resources}")
    for addr in resources:
        try:
            inst = rm.open_resource(addr)
            inst.timeout = 3000
            idn = inst.query("*IDN?").strip()
            if METER_ID_FRAGMENT in idn:
                print(f"[Meter] Found: {addr}  ->  {idn}")
                return inst
            inst.close()
        except Exception:
            pass
    print("[ERROR] HMC8012 not found. Check USB connection.")
    sys.exit(1)


def configure_meter(inst):
    """Set up DC voltage measurement on the 600 mV range."""
    # Do NOT send *RST — it disconnects the USB interface on the HMC8012
    inst.write("CONF:VOLT:DC")
    inst.write("VOLT:DC:RANG 0.6")   # 600 mV range (appropriate for shunt voltages)
    inst.write("VOLT:DC:NPLC 1")     # 1 PLC integration (50 ms @ 50 Hz mains) — balances speed vs noise
    time.sleep(0.2)


# ── Sampling thread ───────────────────────────────────────────────────────────
class SamplerThread(threading.Thread):
    """
    Reads meter samples as fast as the instrument allows and appends them
    to a shared list. Runs until stop_event is set.
    """
    def __init__(self, inst, samples: list, stop_event: threading.Event):
        super().__init__(daemon=True)
        self.inst       = inst
        self.samples    = samples
        self.stop_event = stop_event
        self.last_read  = time.monotonic()
        self.last_v_mV  = 0.0   # most recent reading in mV for live display

    def run(self):
        while not self.stop_event.is_set():
            try:
                ts  = datetime.now().isoformat(timespec='milliseconds')
                raw = self.inst.query("READ?").strip()
                v   = float(raw)            # volts (stored in CSV as-is)
                self.samples.append((ts, v))
                self.last_v_mV = v * 1e3   # mV for live display only
                self.last_read = time.monotonic()
            except Exception as e:
                # Non-fatal: log and continue — occasional timeouts are fine
                print(f"  [Sampler] Read error (skipped): {e}")
                time.sleep(0.05)


# ── Keepalive thread ──────────────────────────────────────────────────────────
def keepalive_loop(inst, stop_event: threading.Event, sampler: SamplerThread):
    """
    Sends a READ? every KEEPALIVE_EVERY seconds if the sampler hasn't read
    recently. Prevents USB timeout on the HMC8012 during slow periods.
    The sampler thread handles most reads; this is just a safety net.
    """
    while not stop_event.is_set():
        time.sleep(KEEPALIVE_EVERY)
        if time.monotonic() - sampler.last_read > KEEPALIVE_EVERY:
            try:
                inst.query("READ?")
            except Exception:
                pass


# ── CSV writer ────────────────────────────────────────────────────────────────
def write_csv(samples: list, duration_s: float, n_samples: int):
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    voltages = [v for _, v in samples]
    mu    = float(np.mean(voltages))
    sigma = float(np.std(voltages, ddof=1))

    with open(OUTPUT_PATH, 'w', newline='', encoding='utf-8') as fh:
        w = csv.writer(fh)

        # ── META block ──
        w.writerow(['# META'])
        w.writerow(['type',            'shortcircuit_calibration'])
        w.writerow(['recorded_at',     datetime.now().isoformat()])
        w.writerow(['duration_s',      round(duration_s, 2)])
        w.writerow(['n_samples',       n_samples])
        w.writerow(['mu_offset_V',     f'{mu:.8f}'])
        w.writerow(['sigma_noise_V',   f'{sigma:.8f}'])
        w.writerow(['mu_offset_mV',    f'{mu*1e3:.6f}'])
        w.writerow(['sigma_noise_mV',  f'{sigma*1e3:.6f}'])
        w.writerow([])

        # ── METER block ──
        # Same format as experiment CSVs: timestamp, v_shunt, phase
        # Phase is fixed to 'short' so the parser can identify all rows as zero-input
        w.writerow(['# METER'])
        w.writerow(['timestamp', 'v_shunt', 'phase'])
        for ts, v in samples:
            w.writerow([ts, f'{v:.8f}', 'short'])

    print(f"\n[Output] Written to: {OUTPUT_PATH}")
    print(f"  Samples:       {n_samples}")
    print(f"  Offset  mu  = {mu*1e3:+.4f} mV")
    print(f"  Noise  sigma= {sigma*1e3:.4f} mV  (ddof=1)")
    print(f"\n  Copy {OUTPUT_PATH.name} into your analyze_data/ folder.")
    print(f"  analyze_experiments.py will apply the correction automatically.")


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    print("=" * 60)
    print("  BTR Short-Circuit Noise Floor Calibration")
    print("=" * 60)
    print()
    print("  Instructions:")
    print("  1. Disconnect module and Pico from the circuit.")
    print("  2. Short the two meter probes directly together.")
    print("  3. Press ENTER to begin 10-minute recording.")
    print()
    input("  Press ENTER when probes are shorted and ready...")
    print()

    rm   = pyvisa.ResourceManager()
    inst = find_meter(rm)
    configure_meter(inst)

    samples     = []
    stop_event  = threading.Event()

    sampler  = SamplerThread(inst, samples, stop_event)
    sampler.start()

    ka_thread = threading.Thread(
        target=keepalive_loop,
        args=(inst, stop_event, sampler),
        daemon=True
    )
    ka_thread.start()

    print(f"[Record] Sampling for {DURATION_S}s ({DURATION_S//60} minutes)...")
    start = time.monotonic()

    try:
        while True:
            elapsed = time.monotonic() - start
            if elapsed >= DURATION_S:
                break
            remaining = DURATION_S - elapsed
            n = len(samples)
            rate    = n / elapsed if elapsed > 0 else 0
            live_mV = sampler.last_v_mV
            if n >= 2:
                vs       = [v for _, v in samples]
                run_mu   = float(np.mean(vs)) * 1e3
                run_sig  = float(np.std(vs, ddof=1)) * 1e3
                stats_str = f"mu={run_mu:+.4f} mV  sigma={run_sig:.4f} mV"
            else:
                stats_str = "accumulating..."
            print(f"\r  {int(remaining):3d}s left  |  {n} samples  |  "
                  f"{rate:.1f} Sa/s  |  live: {live_mV:+.4f} mV  |  {stats_str}   ",
                  end='', flush=True)
            time.sleep(1.0)
    except KeyboardInterrupt:
        print("\n[INFO] Interrupted by user. Saving partial data...")

    stop_event.set()
    sampler.join(timeout=3)

    elapsed = time.monotonic() - start
    n = len(samples)
    print(f"\n[Record] Done. {n} samples in {elapsed:.1f}s ({n/elapsed:.1f} Sa/s)")

    if n < 10:
        print("[ERROR] Too few samples to characterise noise. Check meter connection.")
        sys.exit(1)

    write_csv(samples, elapsed, n)
    inst.close()
    rm.close()


if __name__ == '__main__':
    main()