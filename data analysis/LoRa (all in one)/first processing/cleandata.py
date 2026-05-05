import os
import pandas as pd
import numpy as np

# ---------------- CONFIG ----------------
R_MEAN = 1.134584
V_OFFSET = -0.002182e-3

INPUT_DIR = "/Users/jude/Documents/GitHub/BTR/experiments/LoRa/experiment 1 (all in one)/data/LoRa/full_payload/20260422_182825"
OUTPUT_DIR = "/Users/jude/Documents/GitHub/BTR/data analysis/LoRa (all in one)/clean data"

os.makedirs(OUTPUT_DIR, exist_ok=True)

RESULTS_HEADER = "Index, Phase, Mean_V, Std_V, Count\n"
POWER_RESULTS_HEADER = "Index, PowerPhase, Mean_V, Std_V, Count\n"
METER_HEADER = "timestamp,v_shunt,phase,current,power_phase\n"


# ---------------- HELPERS ----------------

def is_event_row(row):
    """Detect embedded event rows"""
    return len(row) >= 6 and ("True" in row or "False" in row)


def compute_power_phase(df, events):
    """
    Detect peaks relative to baseline noise and assign them
    to closest TX event (payload size).
    """

    # --- Ensure datetime ---
    df["timestamp"] = pd.to_datetime(df["timestamp"])

    # --- Compute baseline stats ONLY from baseline phase ---
    baseline_df = df[df["phase"] == "baseline"]

    if baseline_df.empty:
        # fallback if baseline missing
        mean = df["v_shunt"].mean()
        std = df["v_shunt"].std()
    else:
        mean = baseline_df["v_shunt"].mean()
        std = baseline_df["v_shunt"].std()

    threshold = mean + 3 * std   # stricter than before

    # --- Parse event windows (successful only) ---
    event_windows = []
    for ev in events:
        try:
            success = ev[5].strip() == "True"
            if not success:
                continue

            payload = ev[0].strip()  # payload_size
            start = pd.to_datetime(ev[2], errors="coerce")
            end = pd.to_datetime(ev[3], errors="coerce")
            if pd.isna(start) or pd.isna(end):
                continue

            event_windows.append((start, end, payload))
        except:
            continue

    event_windows.sort(key=lambda x: x[0])

    # --- Assign phases ---
    power_phases = []

    for ts, val in zip(df["timestamp"], df["v_shunt"]):
        if val <= threshold:
            power_phases.append("idle")
            continue

        matched_payload = None
        for start, end, payload in event_windows:
            if start <= ts <= end:
                matched_payload = payload
                break

        if matched_payload is None:
            previous_payload = None
            for start, end, payload in event_windows:
                if start <= ts:
                    previous_payload = payload
                else:
                    break

            if previous_payload is not None:
                power_phases.append(f"active_peak_tx_{previous_payload}")
            else:
                power_phases.append("active_peak_unknown")
        else:
            power_phases.append(f"active_peak_tx_{matched_payload}")

    return power_phases

# ---------------- CORE ----------------

def process_file(filepath):
    name = os.path.basename(filepath)

    with open(filepath, "r") as f:
        lines = f.readlines()

    # --- Split sections ---
    meter_idx = next(i for i, l in enumerate(lines) if "# METER" in l)

    meta = []
    in_meta = False
    
    for line in lines:
        stripped = line.strip()
        
        if stripped.startswith("# META"):
            in_meta = True
            continue
        
        if stripped.startswith("# METER"):
            break  # stop at meter section, don't capture meter rows as meta
        
        if stripped.startswith("# EVENTS"):
            break  # STOP at events section
        
        if in_meta:
            meta.append(line)

    events = []
    events_idx = next((i for i, l in enumerate(lines) if l.strip().startswith("# EVENTS")), None)

    if events_idx is not None:
        for line in lines[events_idx + 1:]:
            row = line.strip().split(",")
            if len(row) >= 6 and ("True" in row or "False" in row):
                events.append(row)

    if events_idx is not None and events_idx > meter_idx:
        data_lines = lines[meter_idx + 1:events_idx]
    else:
        data_lines = lines[meter_idx + 1:]

    # --- Parse rows ---
    meter_rows = []

    for line in data_lines:
        row = line.strip().split(",")

        if not row or len(row) < 2:
            continue

        if is_event_row(row):
            events.append(row)
        else:
            meter_rows.append(row)

    # --- Remove failed payload segments ---
    valid_ranges = []
    current_start = None

    for ev in events:
        try:
            success = ev[5].strip() == "True"
            start = ev[2]
            end = ev[3]

            if success:
                valid_ranges.append((start, end))
        except:
            continue
    
    valid_ranges_dt = [ (pd.to_datetime(start), pd.to_datetime(end)) for start, end in valid_ranges]

    def is_valid_time(ts):
        try:
            ts = pd.to_datetime(ts)
        except:
            return False
        
        for start, end in valid_ranges_dt:
            if start <= ts <= end:
                return True
        return False
    
    # --- Build failed ranges  ---
    failed_ranges = []
    
    for ev in events:
        try:
            success = ev[5].strip() == "True"
            start = pd.to_datetime(ev[2])
            end = pd.to_datetime(ev[3])
            if not success:
                failed_ranges.append((start, end))
        except:
            continue
        
    def is_failed_time(ts):
        try:
            ts = pd.to_datetime(ts)
        except:
            return True  # drop bad rows
            
        for start, end in failed_ranges:
            if start <= ts <= end:
                return True
        return False

    filtered_meter = [
        r for r in meter_rows
        if len(r) >= 3 and not is_failed_time(r[0])
    ]

    # --- Build DataFrame ---
    df = pd.DataFrame(filtered_meter, columns=["timestamp", "v_shunt", "phase"])

    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df["v_shunt"] = df["v_shunt"].astype(float)

    # --- Compute current ---
    df["current"] = (df["v_shunt"] - V_OFFSET) / R_MEAN

    # --- Compute power-based phase ---
    df["power_phase"] = compute_power_phase(df, events)

    # --- Stats: original phase ---
    res_rows = []
    for i, (phase, group) in enumerate(df.groupby("phase")):
        res_rows.append(
            f"{i},{phase},{group['v_shunt'].mean():.9f},{group['v_shunt'].std():.9f},{len(group)}\n"
        )

    # --- Stats: power phase ---
    #power_rows = []
    #for i, (phase, group) in enumerate(df.groupby("power_phase")):
    #    power_rows.append(
    #        f"{i},{phase},{group['v_shunt'].mean():.9f},{group['v_shunt'].std():.9f},{len(group)}\n"
    #    )

    # --- Output file name ---
    run_id = "unknown"
    for line in meta:
        parts = line.strip().split(",")

        if len(parts) >= 2 and parts[0].strip() == "run":
            run_id = parts[1].strip()
            break

    out_name = f"lora_full_payload_clean_run_{run_id}.csv"
    out_path = os.path.join(OUTPUT_DIR, out_name)

    # --- Write output ---
    with open(out_path, "w") as f:
        # META
        f.writelines(meta)

        # EVENTS
        f.write("\n# EVENTS\n")
        for ev in events:
            f.write(",".join(ev) + "\n")

        # RESULTS
        #f.write("\n# RESULTS_ORIGINAL_PHASE\n")
        f.write("\n# RESULTS\n")
        f.write(RESULTS_HEADER)
        f.writelines(res_rows)

        #f.write("\n# RESULTS_POWER_PHASE\n")
        #f.write(POWER_RESULTS_HEADER)
        #f.writelines(power_rows)

        # METER
        f.write("\n# METER\n")
        f.write(METER_HEADER)

        for _, row in df.iterrows():
            f.write(
                f"{row['timestamp']},{row['v_shunt']:.9f},{row['phase']},{row['current']:.9f},{row['power_phase']}\n"
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