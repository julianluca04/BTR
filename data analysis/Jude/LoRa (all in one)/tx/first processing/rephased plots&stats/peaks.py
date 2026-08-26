import os
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt

# -------- CONFIG --------
DATA_DIR = "/Users/jude/Documents/GitHub/BTR/data analysis/LoRa (all in one)/clean data"
DT = 0.002  # resampling resolution (seconds)
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
        header_line = meter_idx + 1

        df = pd.read_csv(path, skiprows=header_line)
        df.columns = [c.strip() for c in df.columns]

        if "timestamp" not in df.columns:
            raise ValueError(f"Bad columns in {path}: {df.columns}")

        if "power_phase" not in df.columns:
            raise ValueError(f"Missing power_phase column in {path}")

        df["timestamp"] = pd.to_datetime(df["timestamp"], format="mixed", errors="coerce")
        df["v_shunt"] = df["v_shunt"].astype(float)
        df["power_phase"] = df["power_phase"].astype(str)

        # normalize time
        first_active = df[df["phase"] != "baseline"]["timestamp"].iloc[0]
        df["time_s"] = (df["timestamp"] - first_active).dt.total_seconds()

        runs.append(df)

    return runs


# -------- ORIGINAL PHASE SPLIT (unchanged) --------
def split_by_phase(df):
    df = df.copy()
    df["block"] = (df["phase"] != df["phase"].shift()).cumsum()

    segments = []
    for (_, phase), group in df.groupby(["block", "phase"], sort=False):
        segments.append({
            "phase": phase,
            "time": group["time_s"].values,
            "v": group["v_shunt"].values
        })

    return segments


def resample_segment(time, values, n_points=200):
    t_norm = np.linspace(time.min(), time.max(), n_points)
    v_interp = np.interp(t_norm, time, values)
    return t_norm, v_interp


# -------- ALIGNMENT (phase-based + TX detection overlay) --------
def align_runs_by_phase(runs):

    all_segment_lists = [split_by_phase(r) for r in runs]
    n_segments = min(len(s) for s in all_segment_lists)

    aligned_segments = []

    for i in range(n_segments):
        phase = all_segment_lists[0][i]["phase"]

        resampled_v = []
        resampled_mask = []

        for run, run_segments in zip(runs, all_segment_lists):
            seg = run_segments[i]

            # --- voltage ---
            t, v = resample_segment(seg["time"], seg["v"])
            resampled_v.append(v)

            # --- power_phase mask ---
            df = run
            mask = (df["time_s"] >= seg["time"].min()) & (df["time_s"] <= seg["time"].max())
            sub = df.loc[mask]

            # TX detection: 1 if TX, else 0
            power_mask = sub["power_phase"].apply(lambda x: 1 if "tx" in x else 0).values

            if len(power_mask) < 2:
                power_interp = np.zeros_like(v)
            else:
                _, power_interp = resample_segment(sub["time_s"].values, power_mask)

            resampled_mask.append(power_interp)

        resampled_v = np.array(resampled_v)
        resampled_mask = np.array(resampled_mask)

        aligned_segments.append({
            "phase": phase,
            "mean": resampled_v.mean(axis=0),
            "std": resampled_v.std(axis=0),
            "mask_mean": resampled_mask.mean(axis=0),  # TX probability
            "length": resampled_v.shape[1]
        })

    return aligned_segments


# -------- BUILD GLOBAL SIGNAL --------
def build_global_signal(aligned_segments):

    mean_all = []
    std_all = []
    mask_all = []
    time_all = []
    phase_marks = []

    t_cursor = 0

    for seg in aligned_segments:
        n = seg["length"]

        t = np.linspace(0, n * DT, n) + t_cursor

        mean_all.extend(seg["mean"])
        std_all.extend(seg["std"])
        mask_all.extend(seg["mask_mean"])
        time_all.extend(t)

        phase_marks.append((t_cursor, seg["phase"]))

        t_cursor = t[-1]

    return (
        np.array(time_all),
        np.array(mean_all),
        np.array(std_all),
        np.array(mask_all),
        phase_marks
    )


# -------- PLOT --------
def plot(time, mean, std, mask, phase_marks):
    fig, ax = plt.subplots(figsize=(16, 6))

    # mean curve
    ax.plot(time, mean, linewidth=2, color="deeppink")
    ax.fill_between(time, mean - std, mean + std, color="deeppink", alpha=0.3)

    # 🔥 TX overlay (consensus detection)
    ax.fill_between(
        time,
        np.min(mean),
        np.max(mean),
        where=mask > 0.5,
        color="deeppink",
        alpha=0.15,
        label="Detected TX (consensus)"
    )

    # light phase background
    for i in range(len(phase_marks)):
        t_start, phase = phase_marks[i]

        if i < len(phase_marks) - 1:
            t_end = phase_marks[i + 1][0]
        else:
            t_end = time[-1]

        ax.axvspan(t_start, t_end, alpha=0.05, color="hotpink")

    ax.set_ylabel("Voltage (V)")
    ax.set_title("Phase-Aligned Trace with Detected TX Overlay (LoRa)", fontweight="bold")

    ax.set_xlabel("")
    ax.annotate(
        "Time →",
        xy=(1.0, -0.15),
        xycoords="axes fraction",
        ha="right",
        fontsize=12
    )

    ax.legend()

    plt.tight_layout()
    plt.show()


# -------- RUN --------
def main():
    runs = load_runs(DATA_DIR)

    print(f"Loaded {len(runs)} runs")

    aligned_segments = align_runs_by_phase(runs)

    t, mean, std, mask, phase_marks = build_global_signal(aligned_segments)

    plot(t, mean, std, mask, phase_marks)


if __name__ == "__main__":
    main()