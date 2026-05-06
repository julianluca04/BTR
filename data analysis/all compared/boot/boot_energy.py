import os
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt

# ---------------- CONFIG ----------------
DATASETS = {
    "WiFi": "/Users/jude/Documents/GitHub/BTR/data analysis/WiFi (all in one)/boot/clean data",
    "BLE":  "/Users/jude/Documents/GitHub/BTR/data analysis/BLE (all in one)/boot/clean data",
    "LoRa": "/Users/jude/Documents/GitHub/BTR/data analysis/LoRa (all in one)/boot/clean data",
}

# ----------------------------------------


# ---------------- HELPERS ----------------

def load_file(path):
    with open(path) as f:
        lines = f.readlines()

    meter_idx = next(i for i, l in enumerate(lines) if "# METER" in l)

    df = pd.read_csv(path, skiprows=meter_idx + 1)
    df.columns = [c.strip() for c in df.columns]

    df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
    df["v_shunt"] = df["v_shunt"].astype(float)
    df["current"] = df["current"].astype(float)

    df = df.dropna(subset=["timestamp"])

    # normalize time
    t0 = df["timestamp"].iloc[0]
    df["time_s"] = (df["timestamp"] - t0).dt.total_seconds()

    return df


def compute_energy(df):
    if len(df) < 2:
        return np.nan

    t = df["time_s"].values
    power = df["v_shunt"].values * df["current"].values

    return np.trapz(power, t)


# ---------------- PROCESS ----------------

def process_dataset(folder):
    energies = []

    for f in os.listdir(folder):
        if not f.endswith(".csv"):
            continue

        path = os.path.join(folder, f)

        df = load_file(path)

        E = compute_energy(df)

        if not np.isnan(E):
            energies.append(E)

    return np.array(energies)


# ---------------- SUMMARY ----------------

def summarize(energies):
    mean = np.mean(energies)
    std = np.std(energies)
    n = len(energies)

    ci95 = 1.96 * std / np.sqrt(n)

    return mean, std, ci95


# ---------------- PLOT ----------------

def plot(results):
    labels = list(results.keys())

    means = [results[k][0] * 1000 for k in labels]   # mJ
    ci95s = [results[k][2] * 1000 for k in labels]

    x = np.arange(len(labels))

    plt.figure(figsize=(8, 6))

    plt.bar(
        x,
        means,
        yerr=ci95s,
        color=["deeppink", "hotpink", "mediumvioletred"],
        capsize=6
    )

    plt.yscale("log")
    plt.xticks(x, labels)
    plt.ylabel("Boot Energy (mJ)")
    plt.title("Boot Energy Comparison (Mean ± 95% CI)")

    plt.grid(axis="y", alpha=0.3)

    plt.tight_layout()
    plt.show()


# ---------------- RUN ----------------

def main():
    results = {}

    for name, path in DATASETS.items():
        print(f"\nProcessing {name}...")

        energies = process_dataset(path)

        mean, std, ci95 = summarize(energies)

        results[name] = (mean, std, ci95)

        print(f"{name}:")
        print(f"  runs = {len(energies)}")
        print(f"  mean = {mean:.6e} J")
        print(f"  std  = {std:.6e}")
        print(f"  ci95 = {ci95:.6e}")

    plot(results)


if __name__ == "__main__":
    main()