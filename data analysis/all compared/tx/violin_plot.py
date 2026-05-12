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


# ---------------- HELPERS ----------------

def load_file(path):

    with open(path) as f:
        lines = f.readlines()

    meter_idx = next(
        i for i, l in enumerate(lines)
        if "# METER" in l
    )

    df = pd.read_csv(path, skiprows=meter_idx + 1)

    df.columns = [c.strip() for c in df.columns]

    df["current"] = df["current"].astype(float)

    return df


def extract_tx_phase_currents(df):
    """
    Returns:
        dict:
            key   -> tx payload label
            value -> mean current for that phase block
    """

    df = df.copy()

    # contiguous phase blocks
    df["block"] = (
        df["phase"] != df["phase"].shift()
    ).cumsum()

    phase_currents = {}

    for _, group in df.groupby("block", sort=False):

        phase = group["phase"].iloc[0]

        # only TX phases
        if not str(phase).startswith("tx_"):
            continue

        mean_current = group["current"].mean()

        if phase not in phase_currents:
            phase_currents[phase] = []

        phase_currents[phase].append(mean_current)

    return phase_currents


def process_dataset(folder):

    all_phase_currents = {}

    files = [
        f for f in os.listdir(folder)
        if f.endswith(".csv")
    ]

    for f in files:

        path = os.path.join(folder, f)

        df = load_file(path)

        phase_data = extract_tx_phase_currents(df)

        for phase, values in phase_data.items():

            if phase not in all_phase_currents:
                all_phase_currents[phase] = []

            all_phase_currents[phase].extend(values)

    return all_phase_currents


# ---------------- PLOT ----------------

def plot_violin(all_results):

    fig, ax = plt.subplots(figsize=(14, 8))

    protocols = list(all_results.keys())

    violin_data = []
    violin_positions = []

    scatter_x = []
    scatter_y = []
    scatter_colors = []

    # color map by payload
    phase_colors = {
        "tx_2": "deeppink",
        "tx_4": "hotpink",
        "tx_8": "mediumvioletred",
        "tx_16": "purple",
        "tx_32": "blueviolet",
        "tx_64": "royalblue",
        "tx_128": "dodgerblue",
        "tx_256": "teal",
        "tx_512": "lightseagreen",
        "tx_1024": "green",
        "tx_2048": "gold",
        "tx_4096": "orange",
        "tx_8192": "darkorange",
        "tx_16384": "tomato",
        "tx_32768": "red",
        "tx_65536": "darkred",
    }

    for idx, protocol in enumerate(protocols):

        phase_dict = all_results[protocol]

        combined = []

        for phase, values in phase_dict.items():

            combined.extend(values)

            # scatter points
            x_jitter = np.random.normal(
                loc=idx,
                scale=0.04,
                size=len(values)
            )

            scatter_x.extend(x_jitter)
            scatter_y.extend(np.array(values) * 1000)  # mA

            color = phase_colors.get(phase, "gray")

            scatter_colors.extend([color] * len(values))

        violin_data.append(np.array(combined) * 1000)  # mA
        violin_positions.append(idx)

    # ---------------- VIOLINS ----------------

    vp = ax.violinplot(
        violin_data,
        positions=violin_positions,
        widths=0.8,
        showmeans=True,
        showextrema=False
    )

    for body in vp["bodies"]:
        body.set_facecolor("lightgray")
        body.set_alpha(0.35)

    vp["cmeans"].set_color("black")
    vp["cmeans"].set_linewidth(2)

    # ---------------- SCATTER ----------------

    ax.scatter(
        scatter_x,
        scatter_y,
        c=scatter_colors,
        alpha=0.8,
        s=22,
        edgecolors="black",
        linewidths=0.3
    )

    # ---------------- LABELS ----------------

    ax.set_xticks(range(len(protocols)))
    ax.set_xticklabels(protocols)

    ax.set_ylabel("Current Draw (mA)")

    ax.set_title(
        "TX Phase Current Distribution\n"
        "(Rephased TX + Idle Segments)"
    )

    ax.grid(axis="y", alpha=0.3)

    # ---------------- LEGEND ----------------

    handles = []

    for phase, color in phase_colors.items():
        handles.append(
            plt.Line2D(
                [0],
                [0],
                marker="o",
                color="w",
                markerfacecolor=color,
                markeredgecolor="black",
                markersize=7,
                label=phase
            )
        )

    ax.legend(
        handles=handles,
        title="TX Payload",
        bbox_to_anchor=(1.02, 1),
        loc="upper left"
    )

    plt.tight_layout()
    plt.show()


# ---------------- RUN ----------------

def main():

    all_results = {}

    for protocol, folder in DATASETS.items():

        print(f"Processing {protocol}...")

        all_results[protocol] = process_dataset(folder)

    plot_violin(all_results)


if __name__ == "__main__":
    main()