import os
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from scipy.stats import gaussian_kde

# ---------------- CONFIG ----------------

DATASETS = {
    "WiFi": {
        "clean": "/Users/jude/Documents/GitHub/BTR/data analysis/WiFi (all in one)/tx/final analysis/clean data",
        "rephased": "/Users/jude/Documents/GitHub/BTR/data analysis/WiFi (all in one)/tx/final analysis/rephased data",
        "v_supply": 5.013517,
        "color": "deeppink"
    },

    "BLE": {
        "clean": "/Users/jude/Documents/GitHub/BTR/data analysis/BLE (all in one)/tx/final analysis/clean data",
        "rephased": "/Users/jude/Documents/GitHub/BTR/data analysis/BLE (all in one)/tx/final analysis/rephased data",
        "v_supply": 5.013517,
        "color": "lightseagreen"
    },

    "LoRa": {
        "clean": "/Users/jude/Documents/GitHub/BTR/data analysis/LoRa (all in one)/tx/final analysis/clean data",
        "rephased": "/Users/jude/Documents/GitHub/BTR/data analysis/LoRa (all in one)/tx/final analysis/rephased data",
        "v_supply": 5.013517,
        "color": "tomato"
    }
}

# ----------------------------------------


# ---------------- HELPERS ----------------

def load_file(path):

    with open(path) as f:
        lines = f.readlines()

    meter_idx = next(i for i, l in enumerate(lines) if "# METER" in l)

    df = pd.read_csv(path, skiprows=meter_idx + 1)

    df.columns = [c.strip() for c in df.columns]

    df["timestamp"] = pd.to_datetime(
        df["timestamp"],
        errors="coerce"
    )

    df["current"] = df["current"].astype(float)

    df = df.dropna(subset=["timestamp"])

    return df


def compute_phase_energy(group, v_supply):
    """
    Compute energy of ONE phase block.
    """

    if len(group) < 2:
        return np.nan

    group = group.sort_values("timestamp")

    t = (
        group["timestamp"]
        - group["timestamp"].iloc[0]
    ).dt.total_seconds().values

    current = group["current"].values

    power = v_supply * current

    energy = np.trapz(power, t)

    return energy


def extract_tx_energies(folder, v_supply):
    """
    Extract energies from ALL tx_* phases
    across all runs.
    """

    energies = []

    files = [
        f for f in os.listdir(folder)
        if f.endswith(".csv")
    ]

    for f in files:

        path = os.path.join(folder, f)

        df = load_file(path)

        # split contiguous blocks
        df["block"] = (
            df["phase"]
            != df["phase"].shift()
        ).cumsum()

        for _, group in df.groupby("block", sort=False):

            phase = group["phase"].iloc[0]

            # keep tx_* only
            if not str(phase).startswith("tx_"):
                continue

            E = compute_phase_energy(
                group,
                v_supply
            )

            if not np.isnan(E):
                energies.append(E)

    return np.array(energies)


# ---------------- PLOT ----------------

def plot_energy_distributions():

    fig, ax = plt.subplots(figsize=(12, 7))

    for name, cfg in DATASETS.items():

        color = cfg["color"]

        # -------- CLEAN --------

        clean_E = extract_tx_energies(
            cfg["clean"],
            cfg["v_supply"]
        )

        if len(clean_E) > 10:

            kde_clean = gaussian_kde(clean_E)

            x_clean = np.linspace(
                clean_E.min(),
                clean_E.max(),
                500
            )

            y_clean = kde_clean(x_clean)

            ax.plot(
                x_clean,
                y_clean,
                linewidth=2.5,
                linestyle="-",
                color=color,
                label=f"{name} TX only"
            )

            print(f"\n{name} CLEAN")
            print(f"Mean Energy = {clean_E.mean():.6f} J")
            print(f"Std Energy  = {clean_E.std():.6f} J")

        # -------- REPHASED --------

        re_E = extract_tx_energies(
            cfg["rephased"],
            cfg["v_supply"]
        )

        if len(re_E) > 10:

            kde_re = gaussian_kde(re_E)

            x_re = np.linspace(
                re_E.min(),
                re_E.max(),
                500
            )

            y_re = kde_re(x_re)

            ax.plot(
                x_re,
                y_re,
                linewidth=2.5,
                linestyle="--",
                color=color,
                label=f"{name} TX + idle"
            )

            print(f"\n{name} REPHASED")
            print(f"Mean Energy = {re_E.mean():.6f} J")
            print(f"Std Energy  = {re_E.std():.6f} J")

    # ---------------- FORMATTING ----------------

    ax.set_xlabel("Phase Energy (J)")
    ax.set_ylabel("Probability Density")

    ax.set_title(
        "Distribution of TX Phase Energy"
    )

    ax.grid(alpha=0.3)

    ax.legend()

    plt.tight_layout()
    plt.show()


# ---------------- RUN ----------------

if __name__ == "__main__":
    plot_energy_distributions()