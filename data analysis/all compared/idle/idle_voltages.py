import os
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt

# ---------------- CONFIG ----------------
DATASETS = {
    "WiFi": "/Users/jude/Documents/GitHub/BTR/data analysis/WiFi (all in one)/tx/final analysis/rephased data",
    "BLE":  "/Users/jude/Documents/GitHub/BTR/data analysis/BLE (all in one)/tx/final analysis/rephased data",
    "LoRa": "/Users/jude/Documents/GitHub/BTR/data analysis/LoRa (all in one)/tx/final analysis/rephased data",
}

# ----------------------------------------

V_supply = {}
V_supply["WiFi"] = 5.013517
V_supply["BLE"] = 5.013517
V_supply["LoRa"] = 5.011090

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

    if "phase" not in df.columns:
        raise ValueError(f"No phase column in {path}")

    df = df.dropna(subset=["timestamp"])

    return df


# ---------------- IDLE METRICS ----------------

def compute_idle_metrics(df, v_supply):
    """
    Returns:
        mean_voltage (V)
        mean_power (W)
    """

    idle_df = df[df["phase"].str.contains("idle", case=False, na=False)].copy()

    if len(idle_df) < 2:
        return np.nan, np.nan

    v = idle_df["v_shunt"].values
    i = idle_df["current"].values
    p = v_supply * i # device power


    mean_voltage = np.mean(v)
    mean_power = np.mean(p)
    mean_current = np.mean(i)

    return mean_voltage, mean_power, mean_current


# ---------------- PROCESS ----------------

def process_dataset(folder, v_supply):
    voltages = []
    powers = []
    currents = []

    for f in os.listdir(folder):
        if not f.endswith(".csv"):
            continue

        path = os.path.join(folder, f)

        df = load_file(path)

        v, p, i = compute_idle_metrics(df, v_supply)

        if not np.isnan(v):
            voltages.append(v)
        if not np.isnan(p):
            powers.append(p)
        if not np.isnan(i):
            currents.append(i)

    return np.array(voltages), np.array(powers), np.array(currents)


# ---------------- SUMMARY ----------------

def summarize(arr):
    mean = np.mean(arr)
    std = np.std(arr)
    n = len(arr)

    ci95 = 1.96 * std / np.sqrt(n)

    return mean, std, ci95


# ---------------- PLOT ----------------

def plot(results, ylabel, scale=1):
    labels = list(results.keys())

    means = [results[k][0] * scale for k in labels]
    ci95s = [results[k][2] * scale for k in labels]

    x = np.arange(len(labels))

    plt.figure(figsize=(8, 6))

    plt.bar(
        x,
        means,
        yerr=ci95s,
        color=["deeppink", "lightseagreen", "tomato"],
        capsize=6
    )

    plt.xticks(x, labels)
    plt.ylabel(ylabel)
    plt.title(f"{ylabel} (Mean ± 95% CI)")

    plt.grid(axis="y", alpha=0.3)

    plt.tight_layout()
    plt.show()


# ---------------- RUN ----------------

def main():
    voltage_results = {}
    power_results = {}
    current_results = {}

    for name, path in DATASETS.items():
        print(f"\nProcessing {name}...")

        voltages, powers, currents = process_dataset(path, V_supply[name])

        v_mean, v_std, v_ci = summarize(voltages)
        p_mean, p_std, p_ci = summarize(powers)
        i_mean, i_std, i_ci = summarize(currents)

        voltage_results[name] = (v_mean, v_std, v_ci)
        power_results[name] = (p_mean, p_std, p_ci)
        current_results[name] = (i_mean, i_std, i_ci)

        print(f"{name}:")
        print(f"  Voltage: mean={v_mean:.6e} V, ci95={v_ci:.6e}")
        print(f"  Power:   mean={p_mean:.6e} W, ci95={p_ci:.6e}")
        print(f"  Current: mean={i_mean:.6e} A, ci95={i_ci:.6e}")

    # ---- PLOTS ----
    plot(voltage_results, "Idle Voltage (V)")
    plot(current_results, "Idle Current (mA)", scale=1e3)
    plot(power_results, "Idle Power (W)")


if __name__ == "__main__":
    main()