import os
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt

# ---------------- CONFIG ----------------
DATA_DIR = "/Users/jude/Documents/GitHub/BTR/data analysis/BLE (all in one)/rephased data"

R_MEAN = 1.134584
V_OFFSET = -0.002182e-3


# ---------------- HELPERS ----------------

def parse_file(path):
    """
    Returns:
        df: time series
        events: list of (payload, start, end, success)
        run_id: string
    """

    with open(path, "r") as f:
        lines = f.readlines()

    meta, events = [], []

    meter_idx = next(i for i, l in enumerate(lines) if "# METER" in l)
    event_idx = next(i for i, l in enumerate(lines) if "# EVENTS" in l)

    # --- META ---
    for l in lines:
        if l.startswith("# META"):
            continue
        if l.startswith("# EVENTS"):
            break
        meta.append(l)

    # --- EVENTS ---
    for l in lines:
        if l.startswith("# EVENTS") or l.startswith("# META"):
            continue
        if l.startswith("# METER"):
            break
        parts = l.strip().split(",")
        if len(parts) >= 7:
            events.append(parts)

    # --- DATA ---
    df = pd.read_csv(path, skiprows=meter_idx + 1)
    df.columns = [c.strip() for c in df.columns]

    df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
    df["v_shunt"] = df["v_shunt"].astype(float)
    df["current"] = df["current"].astype(float)

    df = df.dropna(subset=["timestamp"])

    run_id = "unknown"
    for l in meta:
        if "run" in l:
            try:
                run_id = l.split(",")[1].strip()
            except:
                pass

    return df, events, run_id


def compute_energy(df, start, end):
    """
    Compute energy over interval
    Energy = integral of power = integral of (v_shunt * current) over time
    """
    mask = (df["timestamp"] >= start) & (df["timestamp"] <= end)
    seg = df.loc[mask].copy()

    if len(seg) < 2:
        return np.nan

    seg = seg.sort_values("timestamp")

    t = (seg["timestamp"] - seg["timestamp"].iloc[0]).dt.total_seconds().values
    v = seg["v_shunt"].values
    i = seg["current"].values

    power = v * i
    energy = np.trapz(power, t)

    return energy


# ---------------- MAIN ANALYSIS ----------------

def process_all():
    results = []

    files = [f for f in os.listdir(DATA_DIR) if f.endswith(".csv")]

    for f in files:
        path = os.path.join(DATA_DIR, f)

        df, events, run_id = parse_file(path)

        for ev in events:
            try:
                payload = int(ev[1])
                start = pd.to_datetime(ev[4])
                end = pd.to_datetime(ev[5])
                success = ev[6].strip() == "True"

                if not success:
                    continue

                energy = compute_energy(df, start, end)

                if np.isnan(energy):
                    continue

                results.append({
                    "run": run_id,
                    "payload": payload,
                    "energy_J": energy
                })

            except:
                continue

    return pd.DataFrame(results)


# ---------------- STATS ----------------

def summarize(df):
    summary = df.groupby("payload").agg(
        mean_energy=("energy_J", "mean"),
        std_energy=("energy_J", "std"),
        count=("energy_J", "count")
    ).reset_index()

    # 95% CI
    summary["ci95"] = 1.96 * summary["std_energy"] / np.sqrt(summary["count"])

    return summary


# ---------------- PLOT ----------------

def plot(summary):
    fig, ax = plt.subplots(figsize=(12, 6))

    ax.errorbar(
        range(len(summary)),
        summary["mean_energy"] * 1000,  # Convert J to mJ
        yerr=summary["ci95"] * 1000,    # Convert J to mJ
        fmt="o-",
        capsize=5,
        linewidth=2,
        elinewidth=1.5,
        color="deeppink",
        markerfacecolor="deeppink"
    )

    ax.set_xticks(range(len(summary)))
    ax.set_xticklabels(summary["payload"])
    ax.set_xlabel("Payload size (bytes)")
    ax.set_ylabel("Energy (mJ)")
    ax.set_title("WiFi Payload Size vs Energy Consumption (95% CI)")
    ax.grid(True)

    # --- INSET ZOOM for low payload sizes ---
    # Find indices where payload <= 2048
    low_payload_mask = summary["payload"] <= 2048
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

    print("\n=== RAW EVENT TABLE ===")
    print(df.head())

    summary = summarize(df)

    print("\n=== SUMMARY BY PAYLOAD ===")
    print(summary.to_string(index=False))

    print("\n=== OVERALL STATS ===")
    print("Total events:", len(df))
    print("Payload sizes:", sorted(df["payload"].unique()))
    print("Mean energy (all):", df["energy_J"].mean())
    print("Std energy (all):", df["energy_J"].std())

    plot(summary)


if __name__ == "__main__":
    main()