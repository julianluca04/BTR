import os
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt

# -------- CONFIG --------
CLEAN_DIR = "/Users/jude/Documents/GitHub/BTR/data analysis/WiFi (all in one)/tx/clean data"
REPHASED_DIR = "/Users/jude/Documents/GitHub/BTR/data analysis/WiFi (all in one)/tx/rephased data"

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
        df["current"] = df["current"].astype(float)

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
            "i": group["current"].values
        })

    return segments


def resample_segment(time, values, n_points=200):
    """
    Resample each segment to fixed length
    """
    t_norm = np.linspace(time.min(), time.max(), n_points)
    i_interp = np.interp(t_norm, time, values)
    return t_norm, i_interp


def align_runs_by_phase(runs):
    """
    Align all runs phase-by-phase
    """

    all_segment_lists = [split_by_phase(r) for r in runs]

    # assume same phase order across runs
    n_segments = min(len(s) for s in all_segment_lists)

    aligned_segments = []

    for seg_idx in range(n_segments):
        phase = all_segment_lists[0][seg_idx]["phase"]

        resampled = []

        for run_segments in all_segment_lists:
            seg = run_segments[seg_idx]

            t, i = resample_segment(seg["time"], seg["i"])
            resampled.append(i)

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


def plot_subplot(ax, time, mean, std, phase_marks, title):
    # --- mean + std ---
    ax.plot(time, mean, linewidth=2, color="deeppink")
    ax.fill_between(
        time,
        mean - std,
        mean + std,
        alpha=0.35,
        color="deeppink"
    )

    # --- alternating background regions ---
    for idx in range(len(phase_marks)):
        t_start, phase = phase_marks[idx]

        if idx < len(phase_marks) - 1:
            t_end = phase_marks[idx + 1][0]
        else:
            t_end = time[-1]

        # alternate strictly by index
        alpha = 0.12 if idx % 2 == 0 else 0.05

        ax.axvspan(
            t_start,
            t_end,
            alpha=alpha,
            color="hotpink"
        )

    # --- labels ---
    xticks = []
    xlabels = []

    for idx in range(len(phase_marks)):
        t_start, phase = phase_marks[idx]

        if idx < len(phase_marks) - 1:
            t_end = phase_marks[idx + 1][0]
        else:
            t_end = time[-1]

        center = (t_start + t_end) / 2

        xticks.append(center)
        xlabels.append(phase)

    ax.set_xticks(xticks)
    ax.set_xticklabels(
        xlabels,
        rotation=45,
        ha="right",
        fontsize=8
    )

    ax.set_xlim(time[0], time[-1])

    ax.set_ylabel("Current (A)")
    ax.set_title(title)


def plot_comparison(clean_data, rephased_data):
    fig, axes = plt.subplots(
        2,
        1,
        figsize=(18, 10),
        sharex=False
    )

    # --- CLEAN ---
    plot_subplot(
        axes[0],
        *clean_data,
        title="Original Data Phase-aligned Average Current Trace WiFi"
    )

    # --- REPHASED ---
    plot_subplot(
        axes[1],
        *rephased_data,
        title="Rephased Data Phase-aligned Average Current Trace WiFi"
    )

    axes[1].annotate("Time →", xy=(1.0, -0.15), xycoords="axes fraction", ha="right")

    plt.tight_layout()
    plt.show()



def main():

    # ---------------- CLEAN ----------------
    clean_runs = load_runs(CLEAN_DIR)

    print(f"Loaded {len(clean_runs)} clean runs")

    clean_segments = align_runs_by_phase(clean_runs)

    clean_data = build_global_signal(clean_segments)

    # ---------------- REPHASED ----------------
    rephased_runs = load_runs(REPHASED_DIR)

    print(f"Loaded {len(rephased_runs)} rephased runs")

    rephased_segments = align_runs_by_phase(rephased_runs)

    rephased_data = build_global_signal(rephased_segments)

    # ---------------- PLOT ----------------
    plot_comparison(clean_data, rephased_data)


if __name__ == "__main__":
    main()