import os
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt

# -------- CONFIG --------
DATA_DIR = "/Users/jude/Documents/GitHub/BTR/data analysis/WiFi (all in one)/rephased data"
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
            
        # find meter section
        meter_idx = next(i for i, l in enumerate(lines) if "# METER" in l)
        # header is the NEXT line
        header_line = meter_idx + 1
         
        # read CSV properly
        df = pd.read_csv(path, skiprows=header_line )
        
        # 🔥 force correct column names (in case pandas messes up)
        df.columns = [c.strip() for c in df.columns]
        if "timestamp" not in df.columns:
            print(f"Bad columns in {path}: {df.columns}")
            raise ValueError("CSV parsing failed")

        df["timestamp"] = pd.to_datetime(df["timestamp"], format="mixed", errors="coerce")
        df["v_shunt"] = df["v_shunt"].astype(float)

        # --- normalize time: first NON-baseline = t0 ---
        first_active = df[df["phase"] != "baseline"]["timestamp"].iloc[0]
        df["time_s"] = (df["timestamp"] - first_active).dt.total_seconds()

        runs.append(df)

    return runs


def split_by_phase(df):
    """
    Split into sequential phase blocks
    """
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
    """
    Resample each segment to fixed length
    """
    t_norm = np.linspace(time.min(), time.max(), n_points)
    v_interp = np.interp(t_norm, time, values)
    return t_norm, v_interp


def align_runs_by_phase(runs):
    """
    Align all runs phase-by-phase
    """

    all_segment_lists = [split_by_phase(r) for r in runs]

    # assume same phase order across runs
    n_segments = min(len(s) for s in all_segment_lists)

    aligned_segments = []

    for i in range(n_segments):
        phase = all_segment_lists[0][i]["phase"]

        resampled = []

        for run_segments in all_segment_lists:
            seg = run_segments[i]

            t, v = resample_segment(seg["time"], seg["v"])
            resampled.append(v)

        resampled = np.array(resampled)

        mean = resampled.mean(axis=0)
        std = resampled.std(axis=0)

        aligned_segments.append({
            "phase": phase,
            "mean": mean,
            "std": std,
            "length": len(mean)
        })

    return aligned_segments


def build_global_signal(aligned_segments):
    """
    Stitch segments back into one continuous signal
    """
    if aligned_segments and aligned_segments[-1]["phase"] == "idle":
        aligned_segments = aligned_segments[:-1]

    mean_all = []
    std_all = []
    time_all = []
    phase_marks = []

    t_cursor = 0

    for seg in aligned_segments:
        n = seg["length"]

        t = np.linspace(0, n * DT, n) + t_cursor

        mean_all.extend(seg["mean"])
        std_all.extend(seg["std"])
        time_all.extend(t)

        phase_marks.append((t_cursor, seg["phase"]))

        t_cursor = t[-1]

    return np.array(time_all), np.array(mean_all), np.array(std_all), phase_marks


def plot(time, mean, std, phase_marks):
    fig, ax = plt.subplots(figsize=(16, 6))

    # --- mean + std ---
    ax.plot(time, mean, linewidth=2, color="deeppink")
    ax.fill_between(time, mean - std, mean + std, alpha=0.4, color="deeppink")

    # --- alternating shaded phase regions ---
    for i in range(len(phase_marks)):
        t_start, phase = phase_marks[i]

        if i < len(phase_marks) - 1:
            t_end = phase_marks[i + 1][0]
        else:
            t_end = time[-1]

        # alternate shading
        if i % 2 == 0:
            ax.axvspan(t_start, t_end, alpha=0.15, color="hotpink")
        else:
            ax.axvspan(t_start, t_end, alpha=0.08, color="hotpink")

    # --- phase labels ---
    xticks = []
    xlabels = []

    for i in range(len(phase_marks)):
        t_start, phase = phase_marks[i]

        if i < len(phase_marks) - 1:
            t_end = phase_marks[i + 1][0]
        else:
            t_end = time[-1]

        center = (t_start + t_end) / 2

        xticks.append(center)
        xlabels.append(phase)

    ax.set_xticks(xticks)
    ax.set_xticklabels(xlabels, rotation=45, ha="right")

    ax.set_xlim(time[0], time[-1])

    ax.set_ylabel("Voltage (V)")
    ax.set_title("Phase-aligned Average Voltage Trace WiFi")

    ax.set_xlabel("")
    ax.annotate(
        "Time →",
        xy=(1.0, -0.15),
        xycoords="axes fraction",
        ha="right",
        fontsize=12
    )

    plt.tight_layout()
    plt.show()


def main():
    runs = load_runs(DATA_DIR)

    print(f"Loaded {len(runs)} runs")

    aligned_segments = align_runs_by_phase(runs)

    t, mean, std, phase_marks = build_global_signal(aligned_segments)

    plot(t, mean, std, phase_marks)


if __name__ == "__main__":
    main()