import os
import pandas as pd

# ---------------- CONFIG ----------------
INPUT_DIR = "/Users/jude/Documents/GitHub/BTR/data analysis/WiFi (all in one)/tx/clean data"
OUTPUT_DIR = "/Users/jude/Documents/GitHub/BTR/data analysis/WiFi (all in one)/tx/rephased data"

os.makedirs(OUTPUT_DIR, exist_ok=True)


# ---------------- CORE LOGIC ----------------

def reassign_phases(df):
    df = df.copy()

    # --- keep original phases ---
    original_phase = df["phase"].copy()

    # identify TX
    df["is_tx"] = original_phase.str.contains("tx")

    # group contiguous blocks
    df["block"] = (original_phase != original_phase.shift()).cumsum()

    new_phase = [""] * len(df)

    last_tx_label = None
    seen_non_baseline = False
    startup_done = False

    for block_id, group in df.groupby("block"):
        phase = group["phase"].iloc[0]
        idx = group.index

        # --- BASELINE (leave untouched for now) ---
        if phase == "baseline":
            for i in idx:
                new_phase[i] = "baseline"
            continue

        # --- TX BLOCK ---
        if "tx_" in phase:
            last_tx_label = phase
            seen_non_baseline = True

            for i in idx:
                new_phase[i] = phase
            continue

        # --- IDLE BLOCK ---
        if phase == "idle":

            # first idle AFTER baseline
            if not startup_done and not seen_non_baseline:
                for i in idx:
                    new_phase[i] = "startup_idle"
                startup_done = True
                continue

            # idle AFTER TX → merge into TX
            if last_tx_label is not None:
                for i in idx:
                    new_phase[i] = last_tx_label
                continue

            # fallback idle
            for i in idx:
                new_phase[i] = "idle"

    df["phase"] = new_phase

    # --- FINAL STEP: convert baseline → idle ---
    df["phase"] = df["phase"].replace("baseline", "idle")

    return df

# ---------------- FILE PROCESSING ----------------

def process_file(path):
    name = os.path.basename(path)

    with open(path, "r") as f:
        lines = f.readlines()

    meter_idx = next(i for i, l in enumerate(lines) if "# METER" in l)

    header_line = meter_idx + 1

    df = pd.read_csv(path, skiprows=header_line)
    df.columns = [c.strip() for c in df.columns]

    # --- remove final idle phase BEFORE reassigning ---
    if not df.empty and df["phase"].iloc[-1] == "idle":
        # group contiguous blocks
        df["block"] = (df["phase"] != df["phase"].shift()).cumsum()
        last_block = df["block"].iloc[-1]
        df = df[df["block"] != last_block]

    # --- apply new phase logic ---
    df = reassign_phases(df)

    # --- rebuild file ---
    out_path = os.path.join(OUTPUT_DIR, name)

    with open(out_path, "w") as f:
        # copy everything before METER
        f.writelines(lines[:meter_idx])

        # write meter section
        f.write("# METER\n")
        f.write("timestamp,v_shunt,phase,current\n")

        for _, row in df.iterrows():
            f.write(
                f"{row['timestamp']},{row['v_shunt']},{row['phase']},{row['current']}\n"
            )

    return f"Processed {name}"


# ---------------- RUN ----------------

def main():
    files = [f for f in os.listdir(INPUT_DIR) if f.endswith(".csv")]

    print(f"Processing {len(files)} files...")

    for f in files:
        print(process_file(os.path.join(INPUT_DIR, f)))

    print("Done.")


if __name__ == "__main__":
    main()