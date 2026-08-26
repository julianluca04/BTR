import os
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt

# ---------------- CONFIG ----------------
DATA_DIR = "/Users/jude/Documents/GitHub/BTR/data analysis/LoRa (all in one)/clean data"


# ---------------- PARSE FILE ----------------

def parse_file(path):
    with open(path, "r") as f:
        lines = f.readlines()

    meter_idx = next(i for i, l in enumerate(lines) if "# METER" in l)

    df = pd.read_csv(path, skiprows=meter_idx + 1)
    df.columns = [c.strip() for c in df.columns]

    df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
    df["v_shunt"] = df["v_shunt"].astype(float)
    df["current"] = df["current"].astype(float)
    df["power_phase"] = df["power_phase"].astype(str)

    df = df.dropna(subset=["timestamp"])

    return df


# ---------------- TX SEGMENT DETECTION ----------------

def extract_tx_segments(df):
    df = df.copy()

    df["is_tx"] = df["power_phase"].str.contains("tx")

    # group contiguous regions
    df["block"] = (df["is_tx"] != df["is_tx"].shift()).cumsum()

    segments = []

    for (_, is_tx), group in df.groupby(["block", "is_tx"]):
        if not is_tx:
            continue

        # detect payload from label
        payload = None
        for p in group["power_phase"].unique():
            if "tx_" in p:
                try:
                    payload = int(p.split("tx_")[-1])
                    break
                except:
                    continue

        if payload is None:
            continue

        segments.append({
            "payload": payload,
            "data": group
        })

    return segments


# ---------------- ENERGY ----------------

def compute_energy(seg):
    if len(seg) < 2:
        return np.nan

    seg = seg.sort_values("timestamp")

    t = (seg["timestamp"] - seg["timestamp"].iloc[0]).dt.total_seconds().values
    p = seg["v_shunt"].values * seg["current"].values

    return np.trapz(p, t)


# ---------------- MAIN ----------------

def process_all():
    results = []

    files = [f for f in os.listdir(DATA_DIR) if f.endswith(".csv")]

    for f in files:
        path = os.path.join(DATA_DIR, f)

        df = parse_file(path)

        segments = extract_tx_segments(df)

        for seg in segments:
            E = compute_energy(seg["data"])

            if np.isnan(E):
                continue

            payload = seg["payload"]

            # energy per bit
            Eb = E / (payload * 8)

            results.append({
                "payload": payload,
                "energy_J": E,
                "energy_per_bit": Eb
            })

    return pd.DataFrame(results)


# ---------------- SUMMARY ----------------

def summarize(df):
    summary = df.groupby("payload").agg(
        mean_Eb=("energy_per_bit", "mean"),
        std_Eb=("energy_per_bit", "std"),
        count=("energy_per_bit", "count")
    ).reset_index()

    summary["ci95"] = 1.96 * summary["std_Eb"] / np.sqrt(summary["count"])

    return summary.sort_values("payload")


# ---------------- PLOT ----------------

def plot(summary, title_suffix=""):

    x = np.arange(len(summary))

    plt.figure(figsize=(10, 6))

    plt.errorbar(
        x,
        summary["mean_Eb"] * 1e6,      # µJ/bit
        yerr=summary["ci95"] * 1e6,
        fmt="o-",
        capsize=4,
        linewidth=2,
        elinewidth=1.5,
        color="deeppink",
        markerfacecolor="deeppink"
    )

    plt.xticks(x, summary["payload"], rotation=45)

    plt.xlabel("Payload size (bytes)")
    plt.ylabel("Energy per bit (µJ/bit)")
    plt.title(f"LoRa Energy Efficiency vs Payload Size (Detected TX){title_suffix}")

    plt.grid(True, alpha=0.4)

    plt.tight_layout()
    plt.show()


# ---------------- RUN ----------------

def main():
    df = process_all()

    print("\n=== RAW ENERGY PER BIT DATA (LoRa TX only) ===")
    print(df.head())

    summary = summarize(df)

    print("\n=== SUMMARY ===")
    print(summary.to_string(index=False))

    plot(summary)

    # optional: remove payload 1 if it is noisy
    summary_no_small = summary[summary["payload"] > 1].reset_index(drop=True)

    if not summary_no_small.empty:
        plot(summary_no_small, title_suffix=" (excluding payload = 1)")


if __name__ == "__main__":
    main()