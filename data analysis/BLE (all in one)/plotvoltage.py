import os
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt

# -------- CONFIG --------
DATA_DIR = "/path/to/your/cleaned/files"

# -----------------------

def load_runs(folder):
    runs = []

    for f in os.listdir(folder):
        if not f.endswith(".csv"):
            continue

        path = os.path.join(folder, f)

        with open(path, "r") as file:
            lines = file.readlines()

        # find meter section
        meter_idx = next(i for i, l in enumerate(lines) if "# METER" in l)

        df = pd.read_csv(
            path,
            skiprows=meter_idx + 2,  # skip header lines
        )

        # clean
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        df["v_shunt"] = df["v_shunt"].astype(float)

        # align time
        t0 = df["timestamp"].iloc[0]
        df["time_s"] = (df["timestamp"] - t0).dt.total_seconds()

        runs.append(df)

    return runs


def resample_runs(runs, dt=0.01):
    """
    Resample all runs onto common time axis
    """

    max_time = max(r["time_s"].max() for r in runs)
    common_time = np.arange(0, max_time, dt)

    aligned = []

    for df in runs:
        interp = np.interp(
            common_time,
            df["time_s"],
            df["v_shunt"]
        )
        aligned.append(interp)

    aligned = np.array(aligned)

    mean = aligned.mean(axis=0)
    std = aligned.std(axis=0)

    return common_time, mean, std


def extract_phase_changes(df):
    """
    Get phase transition times from ONE run (they should be similar)
    """
    changes = df["phase"] != df["phase"].shift()

    return df.loc[changes, ["time_s", "phase"]]


def plot(mean_time, mean, std, phase_changes):
    plt.figure()

    # mean line
    plt.plot(mean_time, mean)

    # std area
    plt.fill_between(mean_time, mean - std, mean + std, alpha=0.3)

    # phase lines
    for _, row in phase_changes.iterrows():
        plt.axvline(x=row["time_s"], linestyle="--")

    plt.xlabel("Time (s)")
    plt.ylabel("Voltage (V)")
    plt.title("Average Power Trace (BLE runs)")

    plt.show()


def main():
    runs = load_runs(DATA_DIR)

    print(f"Loaded {len(runs)} runs")

    # align + average
    t, mean, std = resample_runs(runs)

    # use first run for phase markers
    phase_changes = extract_phase_changes(runs[0])

    plot(t, mean, std, phase_changes)


if __name__ == "__main__":
    main()