import os
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt

# ---------------- CONFIG ----------------
DATA_DIR = "/Users/jude/Documents/GitHub/BTR/data analysis/BLE (all in one)/clean data"


# ---------------- PARSE FILE ----------------

def parse_file(path):
    with open(path, "r") as f:
        lines = f.readlines()

    meter_idx = next(i for i, l in enumerate(lines) if "# METER" in l)

    events = []

    for l in lines:
        if l.startswith("# EVENTS") or l.startswith("# META") or l.startswith("# METER"):
            continue
        parts = l.strip().split(",")
        if len(parts) >= 7:
            events.append(parts)

    df = pd.read_csv(path, skiprows=meter_idx + 1)
    df.columns = [c.strip() for c in df.columns]

    df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
    df["v_shunt"] = df["v_shunt"].astype(float)
    df["current"] = df["current"].astype(float)

    return df, events


# ---------------- ENERGY CALC ----------------

def compute_energy(df, start, end):
    mask = (df["timestamp"] >= start) & (df["timestamp"] <= end)
    seg = df.loc[mask].copy()

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

        df, events = parse_file(path)

        for ev in events:
            try:
                payload = int(ev[1])
                start = pd.to_datetime(ev[4])
                end = pd.to_datetime(ev[5])
                success = ev[6].strip() == "True"

                if not success:
                    continue

                E = compute_energy(df, start, end)

                if np.isnan(E):
                    continue

                E_bit = E / (payload * 8)

                results.append({
                    "payload": payload,
                    "energy_J": E,
                    "energy_per_bit": E_bit
                })

            except:
                continue

    return pd.DataFrame(results)


# ---------------- SUMMARY ----------------

def summarize(df):
    summary = df.groupby("payload").agg(
        mean_Eb=("energy_per_bit", "mean"),
        std_Eb=("energy_per_bit", "std"),
        count=("energy_per_bit", "count")
    ).reset_index()

    summary["ci95"] = 1.96 * summary["std_Eb"] / np.sqrt(summary["count"])

    return summary


# ---------------- PLOT ----------------

def plot(summary, title_suffix=""):

    plt.figure(figsize=(10, 6))

    plt.errorbar(
        range(len(summary)),
        summary["mean_Eb"] * 1e6,
        yerr=summary["ci95"] * 1e6,
        fmt="o-",
        capsize=4,
        linewidth=2,
        elinewidth=1.5,
        color="deeppink",
        markerfacecolor="deeppink"
    )

    plt.xticks(range(len(summary)), summary["payload"], rotation=45)

    plt.xlabel("Payload size (bytes)")
    plt.ylabel("Energy per bit (µJ/bit)")
    plt.title(f"BLE Energy Efficiency vs Payload Size{title_suffix}")

    plt.grid(True, alpha=0.4)

    plt.tight_layout()
    plt.show()


# ---------------- RUN ----------------

def main():
    df = process_all()

    print("\n=== RAW ENERGY PER BIT DATA ===")
    print(df.head())

    summary = summarize(df)

    print("\n=== SUMMARY ===")
    print(summary.to_string(index=False))

    plot(summary)

    summary_no_tx1 = summary[summary["payload"] != 1].reset_index(drop=True)
    if not summary_no_tx1.empty:
        plot(summary_no_tx1, title_suffix=" (excluding payload 1)")


if __name__ == "__main__":
    main()