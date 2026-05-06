import os
import pandas as pd
import numpy as np

# ---------------- CONFIG ----------------
R_MEAN = 1.134584
V_OFFSET = -0.002182e-3

INPUT_DIR = "/Users/jude/Documents/GitHub/BTR/experiments/BLE/experiment 1 (all in one)/data/ble_nrf52/full_payload/20260413_153849"
OUTPUT_DIR = "/Users/jude/Documents/GitHub/BTR/data analysis/BLE (all in one)/tx/first processing/clean data"

os.makedirs(OUTPUT_DIR, exist_ok=True)

RESULTS_HEADER = "Index, Phase, Mean_V, Std_V, Count\n"
METER_HEADER = "timestamp,v_shunt,phase,current\n"

# ---------------- HELPERS ----------------

def is_event_row(row):
    return len(row) >= 7 and ("True" in row or "False" in row)

# ---------------- CORE ----------------

def process_file(filepath):
    name = os.path.basename(filepath)

    with open(filepath, "r") as f:
        lines = f.readlines()

    # --- Locate METER section ---
    try:
        meter_idx = next(i for i, l in enumerate(lines) if "# METER" in l)
    except StopIteration:
        return f"Skipped {name} (No METER section)"

    # --- Extract META ---
    meta = []
    in_meta = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("# META"):
            in_meta = True
            continue
        if stripped.startswith("# EVENTS"):
            break
        if in_meta:
            meta.append(line)

    # --- Extract EVENTS ---
    events = []
    data_lines = lines[meter_idx + 1:]
    
    # We find the events from the whole file to find the Kill Switch
    all_event_rows = [l.strip().split(",") for l in lines if is_event_row(l.strip().split(","))]
    
    # --- FIND KILL SWITCH ---
    first_failure_ts = None
    successful_events = []
    
    for ev in all_event_rows:
        success = ev[6].strip() == "True"
        if success:
            successful_events.append(ev)
        else:
            # First failure found! This is our cutoff.
            try:
                first_failure_ts = pd.to_datetime(ev[4])
                break # Stop looking at events
            except:
                continue

    # --- Extract METER rows ---
    meter_rows = []
    for line in data_lines:
        row = line.strip().split(",")
        if not row or len(row) < 3 or is_event_row(row):
            continue
        meter_rows.append(row)

    if not meter_rows:
        return f"Skipped {name} (no valid meter data)"

    # --- Build DataFrame ---
    df = pd.DataFrame(meter_rows, columns=["timestamp", "v_shunt", "phase"])
    df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
    df = df.dropna(subset=["timestamp"])

    # --- APPLY KILL SWITCH ---
    if first_failure_ts is not None:
        df = df[df["timestamp"] < first_failure_ts]

    if df.empty:
        return f"Skipped {name} (All data after failure removed)"

    # --- Calculations ---
    df["v_shunt"] = df["v_shunt"].astype(float) - V_OFFSET
    df["current"] = df["v_shunt"] / R_MEAN

    # --- Stats per phase ---
    res_rows = []
    for i, (phase, group) in enumerate(df.groupby("phase", sort=False)):
        res_rows.append(
            f"{i},{phase},{group['v_shunt'].mean():.9f},{group['v_shunt'].std():.9f},{len(group)}\n"
        )

    # --- Extract run id ---
    run_id = "unknown"
    for line in meta:
        parts = line.strip().split(",")
        if len(parts) >= 2 and parts[0].strip() == "run":
            run_id = parts[1].strip()
            break

    # --- Output file ---
    out_name = f"ble_nrf52_full_payload_clean_run_{run_id}.csv"
    out_path = os.path.join(OUTPUT_DIR, out_name)

    with open(out_path, "w") as f:
        # META
        f.write("# META\n")
        f.writelines(meta)

        # EVENTS (keep only successful ones)
        f.write("\n# EVENTS\n")
        for ev in successful_events:
            f.write(",".join(ev) + "\n")

        # RESULTS
        f.write("\n# RESULTS\n")
        f.write(RESULTS_HEADER)
        f.writelines(res_rows)

        # METER
        f.write("\n# METER\n")
        f.write(METER_HEADER)

        for _, row in df.iterrows():
            # Formatting timestamp to match your original format exactly
            ts_str = row['timestamp'].strftime('%Y-%m-%d %H:%M:%S.%f')
            f.write(
                f"{ts_str},{row['v_shunt']:.9e},{row['phase']},{row['current']:.9e}\n"
            )

    return f"Processed {name} -> {out_name}"

# ---------------- RUN ----------------

def main():
    files = [f for f in os.listdir(INPUT_DIR) if f.endswith(".csv")]
    print(f"Processing {len(files)} files...")

    for f in files:
        path = os.path.join(INPUT_DIR, f)
        print(process_file(path))

    print("Done.")

if __name__ == "__main__":
    main()