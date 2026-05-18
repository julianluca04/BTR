import os
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt

# ---------------- CONFIG ----------------
DATA_DIR = "/Users/jude/Documents/GitHub/BTR/data analysis/BLE (all in one)/tx/final analysis/rephased data"

V_SUPPLY = 5.013517  # actual supply voltage

# ----------------------------------------


# ---------------- HELPERS ----------------

def parse_file(path):
    """
    Returns:
        df: time series
        run_id: string
    """

    with open(path, "r") as f:
        lines = f.readlines()

    meta = []

    meter_idx = next(i for i, l in enumerate(lines) if "# METER" in l)

    # --- META ---
    for l in lines:
        if l.startswith("# META"):
            continue
        if l.startswith("# EVENTS"):
            break
        meta.append(l)

    # --- DATA ---
    df = pd.read_csv(path, skiprows=meter_idx + 1)
    df.columns = [c.strip() for c in df.columns]

    df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
    df["current"] = df["current"].astype(float)

    df = df.dropna(subset=["timestamp"])

    run_id = "unknown"

    for l in meta:
        if "run" in l:
            try:
                run_id = l.split(",")[1].strip()
            except:
                pass

    return df, run_id


# ---------------- ENERGY BY PHASE ----------------

def compute_phase_energies(df):
    """
    Integrate energy using PHASE LABELS
    instead of EVENTS section.

    Energy:
        E = integral(P dt)
        P = V_supply * I
    """

    results = []

    # split sequential phase blocks
    df = df.copy()

    df["block"] = (
        df["phase"] != df["phase"].shift()
    ).cumsum()

    for _, group in df.groupby("block", sort=False):

        phase = group["phase"].iloc[0]

        # skip baseline + idle
        if "baseline" in phase.lower():
            continue

        if "idle" in phase.lower():
            continue

        # extract payload from tx_XXXX
        try:
            payload = int(phase.split("_")[1])
        except:
            continue

        if len(group) < 2:
            continue

        group = group.sort_values("timestamp")

        # relative time axis
        t = (
            group["timestamp"] - group["timestamp"].iloc[0]
        ).dt.total_seconds().values

        current = group["current"].values

        # correct power
        power = V_SUPPLY * current

        # integrate
        energy = np.trapz(power, t)

        results.append({
            "payload": payload,
            "energy_J": energy
        })

    return results


# ---------------- MAIN ANALYSIS ----------------

def process_all():

    all_results = []

    files = [
        f for f in os.listdir(DATA_DIR)
        if f.endswith(".csv")
    ]

    for f in files:

        path = os.path.join(DATA_DIR, f)

        df, run_id = parse_file(path)

        phase_results = compute_phase_energies(df)

        for r in phase_results:
            r["run"] = run_id
            all_results.append(r)

    return pd.DataFrame(all_results)


# ---------------- STATS ----------------

def summarize(df):

    summary = df.groupby("payload").agg(
        mean_energy=("energy_J", "mean"),
        std_energy=("energy_J", "std"),
        count=("energy_J", "count")
    ).reset_index()

    summary["ci95"] = (
        1.96
        * summary["std_energy"]
        / np.sqrt(summary["count"])
    )

    return summary.sort_values("payload")


# ---------------- PLOT ----------------

def plot(summary):

    fig, ax = plt.subplots(figsize=(12, 6))

    ax.errorbar(
        range(len(summary)),
        summary["mean_energy"],  # J
        yerr=summary["ci95"],
        fmt="o-",
        capsize=5,
        linewidth=2,
        elinewidth=1.5,
        color="lightseagreen",
        markerfacecolor="lightseagreen"
    )

    ax.set_xticks(range(len(summary)))
    ax.set_xticklabels(summary["payload"])

    ax.set_xlabel("Payload size (bytes)")
    ax.set_ylabel("Energy (J)")

    ax.set_title(
        "BLE Payload Size vs Energy Consumption"
    )

    ax.grid(True)

    # ---- inset zoom ----

    low_payload_mask = summary["payload"] <= 4096
    low_indices = np.where(low_payload_mask)[0]

    if len(low_indices) > 0:

        from mpl_toolkits.axes_grid1.inset_locator import inset_axes
        from matplotlib.patches import Rectangle

        axins = inset_axes(
            ax,
            width=4.5,
            height=1.8,
            loc="upper center",
            borderpad=2
        )

        axins.errorbar(
            range(len(low_indices)),
            summary.iloc[low_indices]["mean_energy"].values,
            yerr=summary.iloc[low_indices]["ci95"].values,
            fmt="o-",
            capsize=4,
            linewidth=2,
            elinewidth=1.5,
            color="lightseagreen",
            markerfacecolor="lightseagreen"
        )

        axins.set_xticks(range(len(low_indices)))

        axins.set_xticklabels(
            summary.iloc[low_indices]["payload"].values,
            fontsize=8
        )

        axins.set_ylabel("Energy (J)", fontsize=8)
        axins.set_xlabel("Payload (bytes)", fontsize=8)

        axins.tick_params(labelsize=7)

        axins.grid(True, alpha=0.3)

        # --- Draw rectangle showing zoomed region ---
        x_min = low_indices[0] - 0.5
        x_max = low_indices[-1] + 0.5
        y_min = 0
        y_max = (
            summary.iloc[low_indices]["mean_energy"].max()
            + summary.iloc[low_indices]["ci95"].max()
        ) * 1.15

        rect = Rectangle((x_min, y_min), x_max - x_min, y_max - y_min, 
                         linewidth=1.5, edgecolor="lightseagreen", facecolor="paleturquoise",
                         linestyle="--", alpha=0.3)
        ax.add_patch(rect)

    plt.tight_layout()
    plt.show()


# ---------------- RUN ----------------

def main():

    df = process_all()

    print("\n=== RAW PHASE TABLE ===")
    print(df.head())

    summary = summarize(df)

    print("\n=== SUMMARY BY PAYLOAD ===")
    print(summary.to_string(index=False))

    print("\n=== OVERALL STATS ===")
    print("Total phases:", len(df))
    print("Payload sizes:", sorted(df["payload"].unique()))
    print("Mean energy:", df["energy_J"].mean())
    print("Std energy:", df["energy_J"].std())

    plot(summary)


if __name__ == "__main__":
    main()