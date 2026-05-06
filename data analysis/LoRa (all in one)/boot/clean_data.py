import os
import pandas as pd

# ---------------- CONFIG ----------------
INPUT_DIR = "/Users/jude/Documents/GitHub/BTR/experiments/LoRa/julian/loraboot/data/LoRa/boot_energy/20260506_082336"
OUTPUT_DIR = "/Users/jude/Documents/GitHub/BTR/data analysis/LoRa (all in one)/boot/clean data"

V_OFFSET = -0.002182e-3
R_MEAN = 1.134584

IDLE_TRIM_SECONDS = 0.5  # keep some idle, not all

os.makedirs(OUTPUT_DIR, exist_ok=True)

METER_HEADER = "timestamp,v_shunt,current\n"

# ---------------- HELPERS ----------------

def trim_idle_tail(df, seconds=0.5):
    """
    Keep only the first part of idle phase
    """
    df = df.sort_values("timestamp").copy()

    idle_df = df[df["phase"].str.contains("idle", case=False, na=False)]

    if idle_df.empty:
        return df

    idle_start = idle_df["timestamp"].iloc[0]
    cutoff = idle_start + pd.Timedelta(seconds=seconds)

    return df[df["timestamp"] <= cutoff]


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

    # --- COMPUTE CURRENT ---
    df["current"] = (df["v_shunt"] - V_OFFSET) / R_MEAN

    # --- TRIM IDLE ---
    df = trim_idle_tail(df, seconds=IDLE_TRIM_SECONDS)

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