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

STABILITY_WINDOW = 50        # samples for rolling std
STABILITY_THRESHOLD = 5e-6   # tune if needed
POST_STABLE_TIME = 0.5       # seconds after stabilization

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


def find_stabilization_time(df, window=50, min_stable_points=100):
    df = df.sort_values("timestamp").copy()

    v = df["v_shunt"].values

    # rolling std
    rolling_std = pd.Series(v).rolling(window=window, center=True).std()

    # estimate steady-state noise from LAST 20% of signal
    tail = v[int(len(v)*0.8):]
    steady_std = np.std(tail)

    threshold = steady_std * 2  # allow small margin

    stable = rolling_std < threshold

    count = 0
    for i, s in enumerate(stable):
        if s:
            count += 1
            if count >= min_stable_points:
                return df["timestamp"].iloc[i]
        else:
            count = 0

    return df["timestamp"].iloc[-1]



def compute_energy(df):
    """
    Compute energy from start to stabilization + margin
    """

    # detect stabilization and convert to time_s
    stab_time = find_stabilization_time(df)
    t_end_time = stab_time + pd.Timedelta(seconds=POST_STABLE_TIME)

    # convert to relative time (seconds)
    t_end = (t_end_time - df["timestamp"].iloc[0]).total_seconds()

    seg = df[df["time_s"] <= t_end]

    if len(seg) < 2:
        return np.nan

    t = seg["time_s"].values
    power = seg["v_shunt"].values * seg["current"].values
    # Sanity check
    #print("Stabilization at:", t_end)

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