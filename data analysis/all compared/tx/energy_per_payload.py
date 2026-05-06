import os
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt

# ---------------- CONFIG ----------------
DATASETS = {
    "WiFi": "/Users/jude/Documents/GitHub/BTR/data analysis/WiFi (all in one)/tx/rephased data",
    "BLE":  "/Users/jude/Documents/GitHub/BTR/data analysis/BLE (all in one)/tx/rephased data",
    "LoRa": "/Users/jude/Documents/GitHub/BTR/data analysis/LoRa (all in one)/tx/rephased data",
}

V_supply = 5.013517

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

    df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
    df["v_shunt"] = df["v_shunt"].astype(float)
    df["current"] = df["current"].astype(float)

    return df, events


def compute_energy(df, start, end, V_supply=5.013517):
    mask = (df["timestamp"] >= start) & (df["timestamp"] <= end)
    seg = df.loc[mask].copy()

    if len(seg) < 2:
        return np.nan

    seg = seg.sort_values("timestamp")

    t = (seg["timestamp"] - seg["timestamp"].iloc[0]).dt.total_seconds().values

    current = seg["current"].values
    power = V_supply * current   # ✅ correct power

    return np.trapz(power, t)


# ---------------- PROCESS ----------------

def process_dataset(data_dir):
    results = []

    files = [f for f in os.listdir(data_dir) if f.endswith(".csv")]

    for f in files:
        path = os.path.join(data_dir, f)
        df, events = parse_file(path)

        for ev in events:
            try:
                if len(ev) >= 7:
                    payload = int(ev[1])
                    start = pd.to_datetime(ev[4])
                    end = pd.to_datetime(ev[5])
                    success = ev[6].strip() == "True"
                elif len(ev) == 6:
                    payload = int(ev[0])
                    start = pd.to_datetime(ev[1])
                    end = pd.to_datetime(ev[3])
                    success = ev[5].strip() == "True"
                else:
                    continue

                if not success:
                    continue

                energy = compute_energy(df, start, end, V_supply)

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

        zoom = summary[summary["payload"] <= 128]
        x = [x_map[p] for p in zoom["payload"]]

        axins.errorbar(
            x,
            zoom["mean_energy"] * 1000,
            yerr=zoom["ci95"] * 1000,
            fmt=shapes[name] + "-",
            capsize=3,
            linewidth=1.8,
            color=colors[name],
            label=name
        )

    zoom_payloads = [p for p in all_payloads if p <= 128]
    axins.set_xticks([x_map[p] for p in zoom_payloads])
    axins.set_xticklabels([p for p in zoom_payloads], fontsize=7, rotation=45)

    axins.set_title("Zoom: BLE & LoRa (1–128 bytes)", fontsize=9)
    axins.grid(True, alpha=0.3)

    plt.tight_layout()
    plt.show()


# ---------------- RUN ----------------

def main():
    summaries = {}

    for name, path in DATASETS.items():
        print(f"\nProcessing {name}...")
        df = process_dataset(path)

        summary = summarize(df)
        summaries[name] = summary

        #print(summary.to_string(index=False))

    plot_all(summaries)


if __name__ == "__main__":
    main()
