import os
import pandas as pd
import numpy as np

# ---------------- CONFIG ----------------
R_MEAN = 1.134584
V_OFFSET = -0.002182e-3

# Input and Output Directories
INPUT_DIR = "/Users/jude/Documents/GitHub/BTR/experiments/overnight/experiment 1 (all in one)/data/esp32/full_payload/best"
OUTPUT_DIR = "/Users/jude/Documents/GitHub/BTR/data analysis/WiFi (all in one)/tx/first processing/clean data"

os.makedirs(OUTPUT_DIR, exist_ok=True)

RESULTS_HEADER = "Index, Phase, Mean_V, Std_V, Count\n"
METER_HEADER = "timestamp,v_shunt,phase,current\n"
TS_FORMAT = "%Y-%m-%dT%H:%M:%S.%f"

# ---------------- HELPERS ----------------

def is_event_row(row):
    """Identifies if a row belongs to the EVENTS section."""
    return len(row) >= 7 and ("True" in [r.strip() for r in row] or "False" in [r.strip() for r in row])

# ---------------- CORE ----------------

def process_file(filepath):
    name = os.path.basename(filepath)

    with open(filepath, "r") as f:
        lines = f.readlines()

    # --- Locate METER section ---
    try:
        meter_idx = next(i for i, l in enumerate(lines) if "# METER" in l)
    except StopIteration:
        return f"Skipped {name} (No METER section found)"

    # --- Extract META section ---
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

    # --- Extract and Filter EVENTS (The Kill Switch) ---
    all_rows = [l.strip().split(",") for l in lines]
    event_rows = [r for r in all_rows if is_event_row(r)]
    
    first_failure_ts = None
    successful_events = []
    
    for ev in event_rows:
        # Check if 'True' exists in the row (success)
        success = "True" in [s.strip() for s in ev]
        if success:
            successful_events.append(ev)
        else:
            # First failure found! Capture timestamp and trigger Kill Switch
            try:
                # ev[4] is the start timestamp for the transmission
                first_failure_ts = pd.to_datetime(ev[4].strip(), format=TS_FORMAT)
                break 
            except:
                continue

    # --- Extract METER rows ---
    meter_rows = []
    data_lines = lines[meter_idx + 1:]
    for line in data_lines:
        row = line.strip().split(",")
        # Skip empty lines, event lines, or malformed lines
        if not row or len(row) < 3 or is_event_row(row):
            continue
        meter_rows.append(row)

    if not meter_rows:
        return f"Skipped {name} (No valid meter data)"

    # --- Build DataFrame ---
    df = pd.DataFrame(meter_rows, columns=["timestamp", "v_shunt", "phase"])
    
    # Fast parsing with explicit format
    df["timestamp"] = pd.to_datetime(df["timestamp"], format=TS_FORMAT, errors="coerce")
    df = df.dropna(subset=["timestamp"])

    # --- APPLY KILL SWITCH (Truncate everything after first failure) ---
    if first_failure_ts is not None:
        df = df[df["timestamp"] < first_failure_ts]

    if df.empty:
        return f"Skipped {name} (Data fully truncated after initial failure)"

    # --- Calculations ---
    df["v_shunt"] = df["v_shunt"].astype(float) - V_OFFSET
    df["current"] = df["v_shunt"] / R_MEAN

    # --- Stats per phase ---
    res_rows = []
    for i, (phase, group) in enumerate(df.groupby("phase", sort=False)):
        res_rows.append(
            f"{i},{phase},{group['v_shunt'].mean():.9f},{group['v_shunt'].std():.9f},{len(group)}\n"
        )

    # --- Extract run id for naming ---
    run_id = "unknown"
    for line in meta:
        parts = line.strip().split(",")
        if len(parts) >= 2 and parts[0].strip() == "run":
            run_id = parts[1].strip()
            break

    # --- Save Cleaned File ---
    out_name = f"esp32_full_payload_clean_run_{run_id}.csv"
    out_path = os.path.join(OUTPUT_DIR, out_name)

    with open(out_path, "w") as f:
        f.write("# META\n")
        f.writelines(meta)

        f.write("\n# EVENTS\n")
        for ev in successful_events:
            f.write(",".join(ev) + "\n")

        f.write("\n# RESULTS\n")
        f.write(RESULTS_HEADER)
        f.writelines(res_rows)

        f.write("\n# METER\n")
        f.write(METER_HEADER)

        for _, row in df.iterrows():
            # Format back to original string format
            ts_str = row['timestamp'].strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3]
            f.write(
                f"{ts_str},{row['v_shunt']:.9e},{row['phase']},{row['current']:.9e}\n"
            )

    return f"Processed {name} -> {out_name}"

# ---------------- RUN ----------------

def main():
    if not os.path.exists(INPUT_DIR):
        print(f"Error: Input directory not found: {INPUT_DIR}")
        return

    files = [f for f in os.listdir(INPUT_DIR) if f.endswith(".csv")]
    print(f"Processing {len(files)} files...")

    for f in files:
        path = os.path.join(INPUT_DIR, f)
        print(process_file(path))

    print("Done.")

if __name__ == "__main__":
    main()