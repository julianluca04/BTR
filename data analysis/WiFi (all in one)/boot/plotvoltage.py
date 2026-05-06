import os
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt

# -------- CONFIG --------
DATA_DIR = "/Users/jude/Documents/GitHub/BTR/data analysis/WiFi (all in one)/boot/clean data"
N_POINTS = 1000  # resolution of final curve
# -----------------------


def load_runs(folder):
    runs = []

    for f in os.listdir(folder):
        if not f.endswith(".csv"):
            continue

        path = os.path.join(folder, f)

        with open(path) as file:
            lines = file.readlines()

        meter_idx = next(i for i, l in enumerate(lines) if "# METER" in l)

        df = pd.read_csv(path, skiprows=meter_idx + 1)
        df.columns = [c.strip() for c in df.columns]

        df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
        df["v_shunt"] = df["v_shunt"].astype(float)

        df = df.dropna(subset=["timestamp"])

        # --- normalize time: start = 0 ---
        t0 = df["timestamp"].iloc[0]
        df["time_s"] = (df["timestamp"] - t0).dt.total_seconds()

        runs.append(df)

    return runs


def resample_run(df, n_points=N_POINTS):
    t = df["time_s"].values
    v = df["v_shunt"].values

    if len(t) < 2:
        return None

    t_norm = np.linspace(t.min(), t.max(), n_points)
    v_interp = np.interp(t_norm, t, v)

    return t_norm, v_interp


def align_runs(runs):
    resampled = []

    for df in runs:
        result = resample_run(df)
        if result is not None:
            _, v = result
            resampled.append(v)

    resampled = np.array(resampled)

    mean = resampled.mean(axis=0)
    std = resampled.std(axis=0)

    # common time axis
    t = np.linspace(0, 1, resampled.shape[1])  # normalized time

    return t, mean, std


def plot(t, mean, std):
    plt.figure(figsize=(10, 6))

    plt.plot(t, mean, linewidth=2, color="deeppink")
    plt.fill_between(t, mean - std, mean + std, alpha=0.4, color="deeppink")

    plt.xlabel("Normalized Time")
    plt.ylabel("Voltage (V)")
    plt.title("WiFi Boot Average Voltage Trace with idle trimmed (Mean ± Std)")

    plt.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.show()


def main():
    runs = load_runs(DATA_DIR)

    print(f"Loaded {len(runs)} runs")

    t, mean, std = align_runs(runs)

    plot(t, mean, std)


if __name__ == "__main__":
    main()