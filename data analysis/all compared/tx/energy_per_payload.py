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

V_supply = {}
V_supply["WiFi"] = 5.013517
V_supply["BLE"] = 5.013517
V_supply["LoRa"] = 5.011090

# ---------------- HELPERS ----------------

def parse_file(path):
    with open(path, "r") as f:
        lines = f.readlines()

    meter_idx = next(i for i, l in enumerate(lines) if "# METER" in l)

    events = []
    for l in lines:
        if l.startswith("# EVENTS") or l.startswith("# META") or l.startswith("# METER"):
            continue
        parts = l.strip().split(",")
        if len(parts) >= 6:
            events.append(parts)

    df = pd.read_csv(path, skiprows=meter_idx + 1)
    df.columns = [c.strip() for c in df.columns]
    df = pd.read_csv(path, skiprows=meter_idx + 1)

    df["phase"] = df["phase"].astype(str)

    df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
    df["v_shunt"] = df["v_shunt"].astype(float)
    df["current"] = df["current"].astype(float)

    return df, events


# ---------------- PROCESS ----------------

def process_dataset(data_dir, name):
    results = []

    files = [f for f in os.listdir(data_dir) if f.endswith(".csv")]

    for f in files:
        path = os.path.join(data_dir, f)
        df, _ = parse_file(path)

        if "phase" not in df.columns:
            continue

        # --- keep only TX phases ---
        df = df[df["phase"].str.contains("tx", case=False, na=False)].copy()

        if df.empty:
            continue

        # --- identify contiguous phase blocks ---
        df["block"] = (df["phase"] != df["phase"].shift()).cumsum()

        for (_, phase), group in df.groupby(["block", "phase"]):
            try:
                if len(group) < 2:
                    continue

                # extract payload from phase name (e.g. tx_64 → 64)
                payload = int(phase.split("_")[-1])

                group = group.sort_values("timestamp")

                t = (group["timestamp"] - group["timestamp"].iloc[0]).dt.total_seconds().values
                power = V_supply[name] * group["current"].values

                energy = np.trapz(power, t)

                if np.isnan(energy):
                    continue

                results.append({
                    "payload": payload,
                    "energy_J": energy
                })

            except:
                continue

    return pd.DataFrame(results)


# ---------------- SUMMARY ----------------

def summarize(df):
    summary = df.groupby("payload").agg(
        mean_energy=("energy_J", "mean"),
        std_energy=("energy_J", "std"),
        count=("energy_J", "count")
    ).reset_index()

    summary["ci95"] = 1.96 * summary["std_energy"] / np.sqrt(summary["count"])

    return summary.sort_values("payload")


# ---------------- PLOT ----------------

def plot_all(summaries):
    plt.figure(figsize=(14, 6))

    colors = {
        "WiFi": "deeppink",
        "BLE": "lightseagreen",
        "LoRa": "tomato"
    }

    shapes = {
        "WiFi": "o",
        "BLE": "s",
        "LoRa": "^"
    }

    # ---- GLOBAL PAYLOAD AXIS ----
    all_payloads = sorted(set(
        p for s in summaries.values() for p in s["payload"]
    ))
    
    # ---- DEFAULT EVEN SPACING ----
    x_map = {p: i for i, p in enumerate(all_payloads)}
    
    # ---- LOCAL COMPRESSION AROUND 220–256 ----
    if 220 in x_map and 256 in x_map:
        idx_220 = x_map[220]
        idx_256 = x_map[256]
        
        # how much to compress (tune this)
        compression = 0.6

        # shift everything AFTER 220 slightly left
        for p in all_payloads:
            if x_map[p] > idx_220:
                x_map[p] -= compression

        # now explicitly place 256 closer to 220
        x_map[256] = idx_220 + 0.4

    # ---- MAIN PLOT ----
    for name, summary in summaries.items():
        x = [x_map[p] for p in summary["payload"]]

        plt.errorbar(
            x,
            summary["mean_energy"],
            yerr=summary["ci95"],
            fmt=shapes[name] + "-",
            capsize=4,
            linewidth=2,
            label=name,
            color=colors[name]
        )

    # ---- X LABELS (all payloads) ----
    xticks = [x_map[p] for p in all_payloads]
    xlabels = [p for p in all_payloads]

    plt.xticks(xticks, xlabels, rotation=45)

    plt.xlabel("Payload size (bytes)")
    plt.ylabel("Energy (J)")
    plt.title("Energy vs Payload Size (WiFi vs BLE vs LoRa)")
    plt.grid(True, alpha=0.3)
    plt.legend()

    # ---- INSET ZOOM (BLE + LoRa, 1–128) ----
    from mpl_toolkits.axes_grid1.inset_locator import inset_axes

    ax = plt.gca()
    axins = inset_axes(ax, width="40%", height="40%", loc="upper center", borderpad=2)

    for name in ["BLE", "LoRa"]:
        summary = summaries[name]

        zoom = summary[summary["payload"] <= 64]
        x = [x_map[p] for p in zoom["payload"]]

        axins.errorbar(
            x,
            zoom["mean_energy"],
            yerr=zoom["ci95"],
            fmt=shapes[name] + "-",
            capsize=3,
            linewidth=1.8,
            color=colors[name],
            label=name
        )

    zoom_payloads = [p for p in all_payloads if p <= 64]
    axins.set_xticks([x_map[p] for p in zoom_payloads])
    axins.set_xticklabels([p for p in zoom_payloads], fontsize=7, rotation=45)

    axins.set_title("Zoom: BLE & LoRa (1–64 bytes)", fontsize=9)
    axins.grid(True, alpha=0.3)

    plt.tight_layout()
    plt.show()


# ---------------- RUN ----------------

def main():
    summaries = {}

    for name, path in DATASETS.items():
        print(f"\nProcessing {name}...")
        df = process_dataset(path, name)

        summary = summarize(df)
        summaries[name] = summary

        #print(summary.to_string(index=False))

    plot_all(summaries)


if __name__ == "__main__":
    main()
