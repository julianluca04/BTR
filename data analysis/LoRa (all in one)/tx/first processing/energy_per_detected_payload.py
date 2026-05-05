import os
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt

# ---------------- CONFIG ----------------
DATA_DIR = "/Users/jude/Documents/GitHub/BTR/data analysis/LoRa (all in one)/clean data"


# ---------------- HELPERS ----------------

def parse_file(path):
    df = None

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


def compute_energy_segment(seg):
    if len(seg) < 2:
        return np.nan

    seg = seg.sort_values("timestamp")

    t = (seg["timestamp"] - seg["timestamp"].iloc[0]).dt.total_seconds().values
    p = seg["v_shunt"].values * seg["current"].values

    return np.trapz(p, t)


# ---------------- DETECT TX SEGMENTS ----------------

def extract_tx_segments(df):
    """
    Find contiguous TX regions using power_phase
    """
    df = df.copy()

    # TX = anything containing 'tx'
    df["is_tx"] = df["power_phase"].str.contains("tx")

    # group contiguous regions
    df["block"] = (df["is_tx"] != df["is_tx"].shift()).cumsum()

    segments = []

    for (_, is_tx), group in df.groupby(["block", "is_tx"]):
        if not is_tx:
            continue

        # extract payload from label
        phases = group["power_phase"].unique()

        payload = None
        for p in phases:
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


# ---------------- MAIN ANALYSIS ----------------

def process_all():
    results = []

    files = [f for f in os.listdir(DATA_DIR) if f.endswith(".csv")]

    for f in files:
        path = os.path.join(DATA_DIR, f)

        df = parse_file(path)

        segments = extract_tx_segments(df)

        for seg in segments:
            energy = compute_energy_segment(seg["data"])

            if np.isnan(energy):
                continue

            results.append({
                "payload": seg["payload"],
                "energy_J": energy
            })

    return pd.DataFrame(results)


# ---------------- STATS ----------------

def summarize(df):
    summary = df.groupby("payload").agg(
        mean_energy=("energy_J", "mean"),
        std_energy=("energy_J", "std"),
        count=("energy_J", "count")
    ).reset_index()

    summary["ci95"] = 1.96 * summary["std_energy"] / np.sqrt(summary["count"])

    return summary.sort_values("payload")


# ---------------- PLOT ----------------
def plot(summary):
    fig, ax = plt.subplots(figsize=(12, 6))

    # --- map payloads to evenly spaced positions ---
    x = np.arange(len(summary))

    ax.errorbar(
        x,
        summary["mean_energy"] * 1000,  # mJ
        yerr=summary["ci95"] * 1000,
        fmt="o-",
        capsize=5,
        linewidth=2,
        color="deeppink",
        markerfacecolor="deeppink"
    )

    # --- categorical x-axis ---
    ax.set_xticks(x)
    ax.set_xticklabels(summary["payload"])

    ax.set_xlabel("Payload size (bytes)")
    ax.set_ylabel("Energy (mJ)")
    ax.set_title("LoRa Energy per detected TX Event (from power peaks)", fontweight="bold")

    ax.grid(True, linestyle="--", alpha=0.5)
    # --- INSET ZOOM for low payload sizes ---
    # Find indices where payload <= 8
    low_payload_mask = summary["payload"] <= 8
    low_indices = np.where(low_payload_mask)[0]

    if len(low_indices) > 0:
        from mpl_toolkits.axes_grid1.inset_locator import inset_axes

        axins = inset_axes(ax, width=4.5, height=1.8, loc="upper center", borderpad=2) 



        axins.errorbar(
            range(len(low_indices)),
            summary.iloc[low_indices]["mean_energy"].values * 1000,
            yerr=summary.iloc[low_indices]["ci95"].values * 1000,
            fmt="o-",
            capsize=4,
            linewidth=2,
            elinewidth=1.5,
            color="deeppink",
            markerfacecolor="deeppink"
        )

        axins.set_xticks(range(len(low_indices)))
        axins.set_xticklabels(summary.iloc[low_indices]["payload"].values, fontsize=8)
        axins.set_ylabel("Energy (mJ)", fontsize=8)
        axins.set_xlabel("Payload (bytes)", fontsize=8)
        axins.tick_params(labelsize=7)
        axins.grid(True, alpha=0.3)

        # Draw rectangle on main plot to show zoom region
        from matplotlib.patches import Rectangle
        x_min = low_indices[0] - 0.5
        x_max = low_indices[-1] + 0.5
        y_min = 0
        y_max = summary.iloc[low_indices]["mean_energy"].max() * 1000 * 1.2

        rect = Rectangle((x_min, y_min), x_max - x_min, y_max - y_min, 
                         linewidth=1.5, edgecolor="deeppink", facecolor="hotpink",
                         linestyle="--", alpha=0.3)
        ax.add_patch(rect)


    plt.tight_layout()
    plt.show()

# ---------------- RUN ----------------

def main():
    df = process_all()

    print("\n=== RAW DETECTED TX EVENTS ===")
    print(df.head())

    summary = summarize(df)

    print("\n=== SUMMARY BY PAYLOAD (DETECTED) ===")
    print(summary.to_string(index=False))

    plot(summary)


if __name__ == "__main__":
    main()