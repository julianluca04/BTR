"""
BTR Experiment Analysis Script
================================
Reads all CSVs from the `analyze_data/` folder (placed alongside this script),
validates experiment consistency, and produces per-experiment-group plots.

Filename convention expected:
    <module>_<strategy>_run<NN>.csv
    e.g.  ble_nrf52_full_payload_run01.csv
          wifi_esp32_chunked_run03.csv
          lora_rn2903_windowed_run12.csv

Outputs (saved to analyze_data/plots/):
    <module>_<strategy>_mean_power_per_run.png
    <module>_<strategy>_run_duration_per_payload.png
    <module>_<strategy>_energy_per_payload.png
    <module>_<strategy>_current_trace_overlay.png
    <module>_<strategy>_baseline_stability.png
"""

import os
import re
import sys
from collections import defaultdict
from pathlib import Path

import matplotlib.pyplot as plt
import matplotlib.cm as cm
import numpy as np
import pandas as pd

# ── Config ────────────────────────────────────────────────────────────────────
SCRIPT_DIR    = Path(__file__).parent
DATA_DIR      = SCRIPT_DIR / "analyze_data"
PLOTS_DIR     = DATA_DIR / "plots"
REQUIRED_RUNS = 30
V_SUPPLY      = 3.3          # V  (used if not in meta; can be overridden per file)
SHUNT_DEFAULT = 1.13         # Ω  (your measured value; overridden by meta if present)

# ── Helpers ───────────────────────────────────────────────────────────────────

def parse_filename(path: Path):
    """
    Returns (module, strategy, run_number) from the filename, or None if
    the filename doesn't match the expected pattern.
    Pattern: <module>_<strategy>_run<NN>.csv
    Module and strategy may themselves contain underscores, so we anchor on
    the last `_run<digits>` segment.
    """
    stem = path.stem                                  # e.g. ble_nrf52_full_payload_run01
    m = re.match(r'^(.+)_(run\d+)$', stem)
    if not m:
        return None
    prefix, run_tag = m.group(1), m.group(2)
    run_num = int(re.search(r'\d+', run_tag).group())

    # Split prefix into module + strategy on the FIRST underscore that separates
    # a known module token.  We use a simple heuristic: the module is everything
    # up to and including the second underscore-token that looks like a hardware
    # identifier (contains digits OR is a known keyword), and the rest is strategy.
    # Fallback: treat first two tokens as module, rest as strategy.
    tokens = prefix.split('_')
    if len(tokens) < 2:
        return None
    # Heuristic: module = first 2 tokens, strategy = remaining tokens joined
    module   = '_'.join(tokens[:2])
    strategy = '_'.join(tokens[2:]) if len(tokens) > 2 else 'unknown'
    return module, strategy, run_num


def parse_csv(path: Path):
    """
    Parse a BTR CSV file.
    Returns dict with keys:
        meta    – dict of scalar metadata
        events  – pd.DataFrame (may be empty)
        meter   – pd.DataFrame with columns [timestamp, v_shunt, phase,
                                              current_mA, power_mW]
    """
    meta   = {}
    events_rows = []
    meter_rows  = []
    section = None
    events_header = None

    with open(path, encoding='utf-8') as fh:
        for raw in fh:
            line = raw.strip()
            if not line:
                continue
            if line == '# META':
                section = 'meta'; continue
            if line == '# EVENTS':
                section = 'events'; continue
            if line == '# METER':
                section = 'meter'; continue

            if section == 'meta':
                if ',' in line:
                    k, v = line.split(',', 1)
                    try:    meta[k.strip()] = float(v.strip())
                    except: meta[k.strip()] = v.strip()

            elif section == 'events':
                if events_header is None:
                    events_header = [c.strip() for c in line.split(',')]
                else:
                    events_rows.append([c.strip() for c in line.split(',')])

            elif section == 'meter':
                if line.startswith('timestamp'):
                    continue
                parts = line.split(',')
                if len(parts) == 3:
                    meter_rows.append(parts)

    # Build DataFrames
    if events_rows and events_header:
        events_df = pd.DataFrame(events_rows, columns=events_header)
    else:
        events_df = pd.DataFrame()

    if meter_rows:
        meter_df = pd.DataFrame(meter_rows, columns=['timestamp', 'v_shunt', 'phase'])
        meter_df['timestamp'] = pd.to_datetime(meter_df['timestamp'])
        meter_df['v_shunt']   = pd.to_numeric(meter_df['v_shunt'], errors='coerce')
        meter_df = meter_df.dropna(subset=['v_shunt'])
        shunt = float(meta.get('shunt_ohms', SHUNT_DEFAULT))
        meter_df['current_mA'] = (meter_df['v_shunt'] / shunt) * 1e3
        v_sup = float(meta.get('v_supply', V_SUPPLY))
        meter_df['power_mW']   = meter_df['current_mA'] * v_sup
        # elapsed seconds from first sample
        meter_df['elapsed_s'] = (meter_df['timestamp'] - meter_df['timestamp'].iloc[0]).dt.total_seconds()
    else:
        meter_df = pd.DataFrame()

    return {'meta': meta, 'events': events_df, 'meter': meter_df}


# ── Validation ────────────────────────────────────────────────────────────────

def validate_group(group_key, file_list, parsed_list):
    """
    Checks:
      1. Exactly REQUIRED_RUNS files present.
      2. All runs have the same set of payload phases.
      3. No duplicate run numbers.
    Prints warnings; returns True if all checks pass.
    """
    module, strategy = group_key
    label = f"{module} / {strategy}"
    ok = True

    # --- run count ---
    run_nums = [info['run'] for info in file_list]
    if len(run_nums) != REQUIRED_RUNS:
        print(f"  [WARN] {label}: expected {REQUIRED_RUNS} runs, found {len(run_nums)}")
        ok = False
    else:
        print(f"  [OK]   {label}: {REQUIRED_RUNS} runs present")

    # --- duplicate run numbers ---
    seen = set()
    dups = [r for r in run_nums if r in seen or seen.add(r)]
    if dups:
        print(f"  [WARN] {label}: duplicate run numbers: {dups}")
        ok = False

    # --- consistent payload set across runs ---
    payload_sets = []
    for p in parsed_list:
        phases = set(p['meter']['phase'].unique()) if not p['meter'].empty else set()
        tx_phases = {ph for ph in phases if ph.startswith('tx_')}
        payload_sets.append(frozenset(tx_phases))
    if len(set(payload_sets)) > 1:
        print(f"  [WARN] {label}: payload phase sets differ across runs!")
        ok = False
    else:
        sizes = sorted([int(ph.split('_')[1]) for ph in list(payload_sets)[0]]) if payload_sets else []
        print(f"  [OK]   {label}: consistent payload sizes across runs: {sizes}")

    return ok


# ── Per-run summary extraction ────────────────────────────────────────────────

def summarise_run(parsed, run_num):
    """
    Returns a dict summarising a single run:
      - run: run number
      - mean_power_mW: mean power over the whole recording (excl. baseline)
      - baseline_mean_mA / baseline_std_mA
      - per-payload: duration_s, mean_power_mW, energy_mJ
    """
    meter = parsed['meter']
    if meter.empty:
        return None

    baseline_df = meter[meter['phase'] == 'baseline']
    baseline_mean = baseline_df['current_mA'].mean()
    baseline_std  = baseline_df['current_mA'].std()

    tx_phases = meter[meter['phase'].str.startswith('tx_')]
    mean_power_active = tx_phases['power_mW'].mean() if not tx_phases.empty else np.nan

    payload_stats = []
    for phase_label, grp in meter[meter['phase'].str.startswith('tx_')].groupby('phase'):
        size_bytes = int(phase_label.split('_')[1])
        t = grp['elapsed_s'].values
        # duration = span of samples in this phase
        duration_s = grp['timestamp'].iloc[-1].timestamp() - grp['timestamp'].iloc[0].timestamp()
        mean_pw    = grp['power_mW'].mean()
        # energy = mean_power × duration (trapezoidal would need timestamps)
        dt = np.diff(grp['timestamp'].values.astype(np.int64)) / 1e9  # ns→s
        if len(dt):
            energy_mJ = float(np.sum(grp['power_mW'].values[:-1] * dt))
        else:
            energy_mJ = mean_pw * duration_s / 1e3
        payload_stats.append({
            'payload_bytes': size_bytes,
            'duration_s':    duration_s,
            'mean_power_mW': mean_pw,
            'energy_mJ':     energy_mJ,
        })

    return {
        'run':                run_num,
        'mean_power_active_mW': mean_power_active,
        'baseline_mean_mA':   baseline_mean,
        'baseline_std_mA':    baseline_std,
        'payload_stats':      sorted(payload_stats, key=lambda x: x['payload_bytes']),
        'meter':              meter,
    }


# ── Plotting ──────────────────────────────────────────────────────────────────

def plot_mean_power_per_run(summaries, module, strategy, out_dir):
    """Bar chart: mean active power (mW) for each run."""
    runs   = [s['run'] for s in summaries]
    powers = [s['mean_power_active_mW'] for s in summaries]

    fig, ax = plt.subplots(figsize=(12, 4))
    bars = ax.bar(runs, powers, color='steelblue', edgecolor='white', linewidth=0.5)
    ax.axhline(np.nanmean(powers), color='tomato', linestyle='--', linewidth=1.2, label=f'Mean = {np.nanmean(powers):.2f} mW')
    ax.set_xlabel('Run #')
    ax.set_ylabel('Mean Active Power (mW)')
    ax.set_title(f'{module.upper()} · {strategy} — Mean Active Power per Run')
    ax.legend()
    ax.set_xticks(runs)
    ax.set_xticklabels([str(r) for r in runs], fontsize=7, rotation=45)
    fig.tight_layout()
    fname = out_dir / f"{module}_{strategy}_mean_power_per_run.png"
    fig.savefig(fname, dpi=150)
    plt.close(fig)
    print(f"  Saved: {fname.name}")


def plot_run_duration_per_payload(summaries, module, strategy, out_dir):
    """
    Box plot: distribution of per-payload tx duration across 30 runs,
    one box per payload size.
    """
    # Collect durations keyed by payload_bytes
    payload_data = defaultdict(list)
    for s in summaries:
        for ps in s['payload_stats']:
            payload_data[ps['payload_bytes']].append(ps['duration_s'])

    sizes  = sorted(payload_data.keys())
    labels = [str(sz) if sz < 1024 else (f'{sz//1024}K' if sz < 1048576 else f'{sz//1048576}M') for sz in sizes]
    data   = [payload_data[sz] for sz in sizes]

    fig, ax = plt.subplots(figsize=(max(10, len(sizes) * 0.8), 5))
    bp = ax.boxplot(data, patch_artist=True, medianprops=dict(color='tomato', linewidth=1.5))
    for patch in bp['boxes']:
        patch.set_facecolor('lightsteelblue')
    ax.set_xticklabels(labels, rotation=45, ha='right', fontsize=8)
    ax.set_xlabel('Payload Size (bytes)')
    ax.set_ylabel('TX Duration (s)')
    ax.set_title(f'{module.upper()} · {strategy} — TX Duration per Payload Size')
    fig.tight_layout()
    fname = out_dir / f"{module}_{strategy}_run_duration_per_payload.png"
    fig.savefig(fname, dpi=150)
    plt.close(fig)
    print(f"  Saved: {fname.name}")


def plot_energy_per_payload(summaries, module, strategy, out_dir):
    """
    Mean ± std energy (mJ) vs payload size, with individual run scatter.
    """
    payload_data = defaultdict(list)
    for s in summaries:
        for ps in s['payload_stats']:
            payload_data[ps['payload_bytes']].append(ps['energy_mJ'])

    sizes  = sorted(payload_data.keys())
    means  = [np.mean(payload_data[sz]) for sz in sizes]
    stds   = [np.std(payload_data[sz])  for sz in sizes]
    labels = [str(sz) if sz < 1024 else (f'{sz//1024}K' if sz < 1048576 else f'{sz//1048576}M') for sz in sizes]

    fig, ax = plt.subplots(figsize=(max(10, len(sizes) * 0.8), 5))
    x = np.arange(len(sizes))

    # scatter individual run points
    for i, sz in enumerate(sizes):
        ys = payload_data[sz]
        ax.scatter([i] * len(ys), ys, color='steelblue', alpha=0.35, s=15, zorder=2)

    ax.errorbar(x, means, yerr=stds, fmt='o-', color='tomato', linewidth=1.5,
                capsize=4, zorder=3, label='Mean ± 1 SD')
    ax.set_xticks(x)
    ax.set_xticklabels(labels, rotation=45, ha='right', fontsize=8)
    ax.set_xlabel('Payload Size (bytes)')
    ax.set_ylabel('Energy (mJ)')
    ax.set_title(f'{module.upper()} · {strategy} — Energy per Payload (all runs)')
    ax.legend()
    fig.tight_layout()
    fname = out_dir / f"{module}_{strategy}_energy_per_payload.png"
    fig.savefig(fname, dpi=150)
    plt.close(fig)
    print(f"  Saved: {fname.name}")


def plot_current_trace_overlay(summaries, module, strategy, out_dir, max_runs=10):
    """
    Overlay of current (mA) vs elapsed time for up to `max_runs` runs.
    Each trace is colour-coded.
    """
    n = min(max_runs, len(summaries))
    cmap = cm.colormaps.get_cmap('tab10').resampled(n)

    fig, ax = plt.subplots(figsize=(14, 5))
    for i, s in enumerate(summaries[:n]):
        meter = s['meter']
        ax.plot(meter['elapsed_s'], meter['current_mA'],
                linewidth=0.6, alpha=0.7, color=cmap(i), label=f'Run {s["run"]}')

    ax.set_xlabel('Elapsed Time (s)')
    ax.set_ylabel('Current (mA)')
    ax.set_title(f'{module.upper()} · {strategy} — Current Trace Overlay (first {n} runs)')
    ax.legend(fontsize=7, ncol=2)
    fig.tight_layout()
    fname = out_dir / f"{module}_{strategy}_current_trace_overlay.png"
    fig.savefig(fname, dpi=150)
    plt.close(fig)
    print(f"  Saved: {fname.name}")


def plot_baseline_stability(summaries, module, strategy, out_dir):
    """
    Baseline mean current per run with ±1 SD error bars.
    Helps spot drift or warm-up effects.
    """
    runs   = [s['run']              for s in summaries]
    means  = [s['baseline_mean_mA'] for s in summaries]
    stds   = [s['baseline_std_mA']  for s in summaries]

    fig, ax = plt.subplots(figsize=(12, 4))
    ax.errorbar(runs, means, yerr=stds, fmt='o-', color='steelblue',
                capsize=4, linewidth=1.2, markersize=4)
    ax.axhline(np.nanmean(means), color='tomato', linestyle='--', linewidth=1,
               label=f'Grand mean = {np.nanmean(means):.3f} mA')
    ax.set_xlabel('Run #')
    ax.set_ylabel('Baseline Current (mA)')
    ax.set_title(f'{module.upper()} · {strategy} — Baseline Stability across Runs')
    ax.set_xticks(runs)
    ax.set_xticklabels([str(r) for r in runs], fontsize=7, rotation=45)
    ax.legend()
    fig.tight_layout()
    fname = out_dir / f"{module}_{strategy}_baseline_stability.png"
    fig.savefig(fname, dpi=150)
    plt.close(fig)
    print(f"  Saved: {fname.name}")


def export_summary_csv(summaries, module, strategy, out_dir):
    """
    Flat CSV: one row per (run, payload_size) with duration, mean_power, energy.
    """
    rows = []
    for s in summaries:
        for ps in s['payload_stats']:
            rows.append({
                'module':          module,
                'strategy':        strategy,
                'run':             s['run'],
                'payload_bytes':   ps['payload_bytes'],
                'duration_s':      round(ps['duration_s'],    6),
                'mean_power_mW':   round(ps['mean_power_mW'], 4),
                'energy_mJ':       round(ps['energy_mJ'],     6),
                'baseline_mean_mA': round(s['baseline_mean_mA'], 5),
                'baseline_std_mA':  round(s['baseline_std_mA'],  5),
                'run_mean_active_power_mW': round(s['mean_power_active_mW'], 4),
            })
    df = pd.DataFrame(rows)
    fname = out_dir / f"{module}_{strategy}_summary.csv"
    df.to_csv(fname, index=False)
    print(f"  Saved: {fname.name}")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    if not DATA_DIR.exists():
        print(f"[ERROR] Data directory not found: {DATA_DIR}")
        print("  Create a folder called 'analyze_data' next to this script and put your CSVs in it.")
        sys.exit(1)

    PLOTS_DIR.mkdir(parents=True, exist_ok=True)

    # ── Discover and group files ───────────────────────────────────────────
    csv_files = sorted(DATA_DIR.glob("*.csv"))
    if not csv_files:
        print(f"[ERROR] No CSV files found in {DATA_DIR}")
        sys.exit(1)

    groups = defaultdict(list)   # (module, strategy) → list of {path, run}
    skipped = []

    for f in csv_files:
        parsed_name = parse_filename(f)
        if parsed_name is None:
            skipped.append(f.name)
            continue
        module, strategy, run_num = parsed_name
        groups[(module, strategy)].append({'path': f, 'run': run_num})

    if skipped:
        print(f"\n[WARN] Skipped {len(skipped)} file(s) with unrecognised names:")
        for s in skipped:
            print(f"  {s}")

    print(f"\nFound {len(groups)} experiment group(s) in {DATA_DIR}:\n")

    all_ok = True

    for group_key, file_list in sorted(groups.items()):
        module, strategy = group_key
        file_list_sorted = sorted(file_list, key=lambda x: x['run'])

        print(f"━━ {module.upper()} / {strategy} ({'×'.join(str(len(file_list)))} runs) ━━")

        # Parse all CSVs
        parsed_list = [parse_csv(info['path']) for info in file_list_sorted]

        # Validate
        group_ok = validate_group(group_key, file_list_sorted, parsed_list)
        all_ok = all_ok and group_ok

        # Summarise each run
        summaries = []
        for info, parsed in zip(file_list_sorted, parsed_list):
            s = summarise_run(parsed, info['run'])
            if s is not None:
                summaries.append(s)

        if not summaries:
            print("  [WARN] No valid meter data found — skipping plots.")
            continue

        # Plots
        plot_mean_power_per_run(    summaries, module, strategy, PLOTS_DIR)
        plot_run_duration_per_payload(summaries, module, strategy, PLOTS_DIR)
        plot_energy_per_payload(    summaries, module, strategy, PLOTS_DIR)
        plot_current_trace_overlay( summaries, module, strategy, PLOTS_DIR)
        plot_baseline_stability(    summaries, module, strategy, PLOTS_DIR)
        export_summary_csv(         summaries, module, strategy, PLOTS_DIR)

        print()

    if all_ok:
        print("✓ All validation checks passed.")
    else:
        print("⚠ Some validation checks FAILED — see warnings above.")

    print(f"\nAll outputs saved to: {PLOTS_DIR}")


if __name__ == '__main__':
    main()