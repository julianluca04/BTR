import os
import pandas as pd

# ---------------- CONFIG ----------------
INPUT_DIR = "/Users/jude/Documents/GitHub/BTR/experiments/LoRa/julian/loraboot/data/LoRa/boot_energy/20260506_082336"
OUTPUT_DIR = "/Users/jude/Documents/GitHub/BTR/data analysis/LoRa (all in one)/boot/clean data"

V_OFFSET = -0.002182e-3
R_MEAN = 1.134584

TRIM_START_RATIO = 0.1
TRIM_END_RATIO = 0.45

os.makedirs(OUTPUT_DIR, exist_ok=True)

METER_HEADER = "timestamp,v_shunt,current\n"

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

    run_id = "unknown"

    # --- Extract run id ---
    for line in lines:
        if line.startswith("# META"):
            parts = line.strip().split(",")

            if len(parts) > 1:
                raw = parts[1].strip()

                # Convert "Run_1" -> "1"
                if "_" in raw:
                    run_id = raw.split("_")[-1]
                else:
                    run_id = raw

            break

    # --- LOAD DATA ---
    df = pd.read_csv(path, comment="#")
    df.columns = [c.strip() for c in df.columns]

    if "timestamp" not in df.columns:
        return None, run_id

    # --- CLEAN TYPES ---
    df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
    df["v_shunt"] = df["v_shunt"].astype(float)

    df = df.dropna(subset=["timestamp"])

    # --- REMOVE BASELINE ---
    df = df[~df["phase"].str.contains("baseline", case=False, na=False)]

    # --- CORRECT VOLTAGE ---
    df["v_shunt"] = df["v_shunt"] - V_OFFSET
    # --- COMPUTE CURRENT ---
    df["current"] = df["v_shunt"] / R_MEAN

    # --- TRIM IDLE ---
    df = trim_start(df, TRIM_START_RATIO)
    df = trim_end(df, TRIM_END_RATIO)

    return df, run_id


# ---------------- PROCESS ----------------

def process_file(filepath):
    name = os.path.basename(filepath)

    df, run_id = parse_file(filepath)

    if df is None or df.empty:
        return f"Skipped {name}"

    out_name = f"lora_boot_{run_id}.csv"
    out_path = os.path.join(OUTPUT_DIR, out_name)

    with open(out_path, "w") as f:
        # META
        f.write("# META\n")
        f.write(f"# Run ID: {run_id}\n")

        # METER
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