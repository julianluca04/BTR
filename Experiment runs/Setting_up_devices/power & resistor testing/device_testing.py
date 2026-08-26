"""
HMC8012 Component Characterisation Logger
==========================================
Logs voltage or resistance (or both) for 10 minutes each,
computing statistics and saving to separate CSV files.

Instrument: Rohde & Schwarz HMC8012
Backend:    pyvisa-py (pure Python, no NI-VISA needed)

Usage:
    python hmc8012_characterise.py
"""

import pyvisa
import time
import csv
import statistics
from datetime import datetime
from pathlib import Path

# ── Config ────────────────────────────────────────────────────────────────────
VISA_ADDRESS   = "USB0::2733::309::020633987::0::INSTR"
DURATION_S     = 600          # 10 minutes
SAMPLE_INTERVAL_S = 0.5       # seconds between readings (~1200 samples)
VOLTAGE_CSV    = "voltage_characterisation.csv"
RESISTANCE_CSV = "resistance_characterisation.csv"
# ─────────────────────────────────────────────────────────────────────────────


def connect(rm: pyvisa.ResourceManager, retries: int = 3) -> pyvisa.Resource:
    """Open instrument with retry logic."""
    for attempt in range(1, retries + 1):
        try:
            meter = rm.open_resource(VISA_ADDRESS)
            meter.timeout = 5000
            idn = meter.query("*IDN?").strip()
            print(f"  Connected: {idn}")
            return meter
        except Exception as exc:
            print(f"  Attempt {attempt}/{retries} failed: {exc}")
            time.sleep(2)
    raise RuntimeError("Could not connect to HMC8012. Check USB cable and TMC mode.")


def safe_query(meter, cmd: str) -> str | None:
    """Query with basic error handling; returns None on failure."""
    try:
        return meter.query(cmd).strip()
    except Exception as exc:
        print(f"  Query error ({cmd}): {exc}")
        return None


def run_measurement(
    meter,
    mode: str,          # "VOLTAGE" or "RESISTANCE"
    csv_path: str,
) -> dict:
    """
    Run a 10-minute logging session.

    Returns a summary dict with mean, std_dev, variance, min, max.
    """
    label   = "Voltage (V)" if mode == "VOLTAGE" else "Resistance (Ω)"
    scpi_conf = "CONF:VOLT:DC" if mode == "VOLTAGE" else "CONF:RES"
    unit    = "V" if mode == "VOLTAGE" else "Ohm"

    print(f"\n  Configuring meter for {label} …")
    meter.write(scpi_conf)
    time.sleep(0.5)

    samples   = []
    timestamps = []
    start_time = time.monotonic()
    end_time   = start_time + DURATION_S
    sample_n   = 0

    print(f"  Recording for {DURATION_S // 60} minutes → {csv_path}")
    print(f"  {'Sample':>8}  {'Elapsed (s)':>12}  {label:>20}")
    print(f"  {'-'*8}  {'-'*12}  {'-'*20}")

    with open(csv_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            "sample_n", "timestamp_iso", "elapsed_s", label
        ])

        try:
            while time.monotonic() < end_time:
                raw = safe_query(meter, "READ?")
                if raw is None:
                    time.sleep(SAMPLE_INTERVAL_S)
                    continue

                try:
                    value = float(raw)
                except ValueError:
                    print(f"  Non-numeric reading skipped: {raw!r}")
                    time.sleep(SAMPLE_INTERVAL_S)
                    continue

                sample_n  += 1
                elapsed    = round(time.monotonic() - start_time, 3)
                ts         = datetime.now().isoformat(timespec="milliseconds")

                samples.append(value)
                timestamps.append(elapsed)
                writer.writerow([sample_n, ts, elapsed, value])
                f.flush()

                print(f"  {sample_n:>8}  {elapsed:>12.1f}  {value:>20.6f} {unit}")
                time.sleep(SAMPLE_INTERVAL_S)

        except KeyboardInterrupt:
            print("\n  Interrupted by user — saving partial data.")

    if not samples:
        print("  No valid samples collected.")
        return {}

    mean     = statistics.mean(samples)
    std_dev  = statistics.stdev(samples) if len(samples) > 1 else 0.0
    variance = std_dev ** 2
    mn       = min(samples)
    mx       = max(samples)
    spread   = mx - mn

    summary = {
        "mode":      mode,
        "unit":      unit,
        "n_samples": len(samples),
        "duration_s": round(timestamps[-1], 1),
        "mean":      mean,
        "std_dev":   std_dev,
        "variance":  variance,
        "min":       mn,
        "max":       mx,
        "spread":    spread,
    }

    # Append summary block to the same CSV for easy reference
    with open(csv_path, "a", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([])
        writer.writerow(["# SUMMARY"])
        for k, v in summary.items():
            writer.writerow([f"# {k}", v])

    return summary


def print_summary(summary: dict) -> None:
    unit = summary.get("unit", "")
    print(f"\n  ┌─ Summary ({summary['mode']}) ──────────────────────────")
    print(f"  │  Samples   : {summary['n_samples']}  ({summary['duration_s']} s)")
    print(f"  │  Mean      : {summary['mean']:.6f} {unit}")
    print(f"  │  Std Dev   : {summary['std_dev']:.6f} {unit}")
    print(f"  │  Variance  : {summary['variance']:.2e} {unit}²")
    print(f"  │  Min       : {summary['min']:.6f} {unit}")
    print(f"  │  Max       : {summary['max']:.6f} {unit}")
    print(f"  │  Spread    : {summary['spread']:.6f} {unit}")
    print(f"  └───────────────────────────────────────────────────────")


def pick_mode() -> str:
    """Interactive menu. Returns 'V', 'R', or 'BOTH'."""
    print("\n╔══════════════════════════════════════════╗")
    print("║   HMC8012 Component Characterisation     ║")
    print("╠══════════════════════════════════════════╣")
    print("║  1  Voltage only   (10 min)              ║")
    print("║  2  Resistance only (10 min)             ║")
    print("║  3  Both            (20 min total)       ║")
    print("╚══════════════════════════════════════════╝")
    while True:
        choice = input("  Select [1/2/3]: ").strip()
        if choice in ("1", "2", "3"):
            return {"1": "V", "2": "R", "3": "BOTH"}[choice]
        print("  Please enter 1, 2, or 3.")


def main() -> None:
    mode_choice = pick_mode()

    rm = pyvisa.ResourceManager("@py")
    print("\n  Connecting to HMC8012 …")
    meter = connect(rm)

    summaries = []

    if mode_choice in ("V", "BOTH"):
        if mode_choice == "BOTH":
            input("\n  [Voltage phase] Connect probes for VOLTAGE measurement, then press ENTER …")
        s = run_measurement(meter, "VOLTAGE", VOLTAGE_CSV)
        if s:
            print_summary(s)
            summaries.append(s)

    if mode_choice in ("R", "BOTH"):
        if mode_choice == "BOTH":
            input("\n  [Resistance phase] Connect probes for RESISTANCE measurement, then press ENTER …")
        s = run_measurement(meter, "RESISTANCE", RESISTANCE_CSV)
        if s:
            print_summary(s)
            summaries.append(s)

    meter.write("*RST")
    meter.close()
    rm.close()

    print("\n  Done.")
    for s in summaries:
        csv_name = VOLTAGE_CSV if s["mode"] == "VOLTAGE" else RESISTANCE_CSV
        print(f"  → {csv_name}  ({s['n_samples']} samples)")


if __name__ == "__main__":
    main()