import os
import pandas as pd

# ---------------- CONFIG ----------------
INPUT_DIR = "/Users/jude/Documents/GitHub/BTR/experiments/BLE/Boot up experiment/data/ble_nrf52/boot/BEST"
OUTPUT_DIR = "/Users/jude/Documents/GitHub/BTR/data analysis/BLE (all in one)/boot/clean data"

V_OFFSET = -0.002182e-3  # volts 
R_MEAN = 1.134584

os.makedirs(OUTPUT_DIR, exist_ok=True)

METER_HEADER = "timestamp,v_shunt,current\n"

TRIM_START_RATIO = 0.4
TRIM_END_RATIO = 0

# ---------------- HELPERS ----------------

def trim_start(df, ratio):
    """
    Remove first X% of the signal
    """
    if df.empty:
        return df

    df = df.sort_values("timestamp").copy()

    t0 = df["timestamp"].iloc[0]
    df["time_s"] = (df["timestamp"] - t0).dt.total_seconds()

    max_time = df["time_s"].max()
    cutoff = max_time * ratio

    df = df[df["time_s"] >= cutoff]

    return df.drop(columns=["time_s"])

def trim_end(df, ratio):
    """
    Remove last X% of the signal
    """
    if df.empty:
        return df

    df = df.sort_values("timestamp").copy()

    t0 = df["timestamp"].iloc[0]
    df["time_s"] = (df["timestamp"] - t0).dt.total_seconds()

    max_time = df["time_s"].max()
    cutoff = max_time * (1 - ratio)

    # keep only up to cutoff
    df = df[df["time_s"] <= cutoff]

    return df.drop(columns=["time_s"])


def parse_file(path):
    with open(path, "r") as f:
        lines = f.readlines()

    meta = []
    data_started = False
    meter_rows = []

    boot_number = "unknown"

    for line in lines:
        stripped = line.strip()

        # --- META ---
        if stripped.startswith("# META"):
            continue
        elif stripped.startswith("# DATA"):
            data_started = True
            continue

        if not data_started:
            meta.append(line)

            # extract boot number
            if stripped.startswith("boot_number"):
                try:
                    boot_number = stripped.split(",")[1]
                except:
                    pass

        else:
            # skip header
            if stripped.startswith("type"):
                continue

            parts = stripped.split(",")

            if len(parts) < 4:
                continue

            row_type = parts[0]

            if row_type == "METER":
                timestamp = parts[1]
                voltage = parts[2]

                try:
                    v = float(voltage)
                except:
                    continue

                meter_rows.append({
                    "timestamp": timestamp,
                    "v_shunt": v
                })

    df = pd.DataFrame(meter_rows)

    if df.empty:
        return None, boot_number, meta

    # --- Convert types ---
    df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
    df = df.dropna(subset=["timestamp"])

    # --- Correct voltage ---
    df["v_shunt"] = df["v_shunt"] - V_OFFSET
    # --- Compute current ---
    df["current"] = df["v_shunt"] / R_MEAN

    # --- Trim idle ---
    df = trim_start(df, ratio=TRIM_START_RATIO)
    df = trim_end(df, ratio=TRIM_END_RATIO)

    return df, boot_number, meta


# ---------------- PROCESS ----------------

def process_file(filepath):
    name = os.path.basename(filepath)

    df, boot_number, meta = parse_file(filepath)

    if df is None or df.empty:
        return f"Skipped {name} (no valid data)"

    # --- Output name ---
    out_name = f"ble_boot_{boot_number}.csv"
    out_path = os.path.join(OUTPUT_DIR, out_name)

    # --- Write file ---
    with open(out_path, "w") as f:

        # --- META ---
        f.write("# META\n")
        for line in meta:
            f.write(line)

        # Ensure boot number is explicitly written
        #f.write(f"boot_number,{boot_number}\n")

        # --- METER ---
        f.write("\n# METER\n")
        f.write(METER_HEADER)

        for _, row in df.iterrows():
            f.write(
                f"{row['timestamp']},{row['v_shunt']:.9e},{row['current']:.9e}\n"
            )

    return f"Processed {name} -> {out_name}"


# ---------------- RUN ----------------

def main():
    files = [f for f in os.listdir(INPUT_DIR) if f.endswith(".csv")]

    print(f"Found {len(files)} files")

    for f in files:
        path = os.path.join(INPUT_DIR, f)
        print(process_file(path))

    print("Done.")


if __name__ == "__main__":
    main()