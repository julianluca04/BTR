"""
BTR Experiment Analysis Script
================================
Reads all CSVs from the `analyze_data/` folder (placed alongside this script),
validates experiment consistency, and produces per-experiment-group plots.

Filename convention expected:
    <module>_<strategy>_run<NN>.csv
    e.g.  ble_nrf52_full_payload_run01.csv
          wifi_esp32c3_chunked_run03.csv
          lora_rn2903_windowed_run12.csv

Outputs (saved to analyze_data/plots/):
    <module>_<strategy>_mean_power_per_run.png         – mean active power (mW) per run
    <module>_<strategy>_total_energy_per_run.png       – total energy across all payloads per run (mJ)
    <module>_<strategy>_run_duration_per_payload.png   – boxplot of tx duration per payload size
    <module>_<strategy>_energy_per_payload.png         – mean±SD energy (mJ) vs payload size
    <module>_<strategy>_efficiency_per_payload.png     – mean±SD energy efficiency (mJ/KB) vs payload size
    <module>_<strategy>_current_trace_overlay.png      – overlaid current traces (first 10 runs)
    <module>_<strategy>_baseline_stability.png         – baseline current stability across runs
    <module>_<strategy>_summary.csv                    – tidy flat CSV for further analysis

NOTE on statistics:
    All standard deviations use ddof=1 (sample SD, not population SD), appropriate
    because the 30 runs are a sample from a larger hypothetical population of runs.
"""

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
V_SUPPLY      = 3.3    # V  (fallback if not in CSV meta)
SHUNT_DEFAULT = 1.13   # Ω  (your measured value; overridden by meta if present)


# ── Colour helper ─────────────────────────────────────────────────────────────
def _cmap(name, n):
    """Matplotlib-version-safe colormap fetch."""
    try:
        return plt.colormaps[name].resampled(n)
    except AttributeError:
        return cm.get_cmap(name, n)


# ── Filename parsing ──────────────────────────────────────────────────────────
def parse_filename(path: Path):
    """
    Returns (module, strategy, run_number) or None.
    Pattern: <module>_<strategy>_run<NN>.csv
    First two underscore-tokens -> module, remaining tokens before _run<NN> -> strategy.
    """
    stem = path.stem
    m = re.match(r'^(.+)_(run\d+)$', stem)
    if not m:
        return None
    prefix  = m.group(1)
    run_num = int(re.search(r'\d+', m.group(2)).group())
    tokens  = prefix.split('_')
    if len(tokens) < 2:
        return None
    module   = '_'.join(tokens[:2])
    strategy = '_'.join(tokens[2:]) if len(tokens) > 2 else 'unknown'
    return module, strategy, run_num


# ── CSV parser ────────────────────────────────────────────────────────────────
def parse_csv(path: Path):
    """
    Parse a BTR CSV file into meta dict, events DataFrame, and meter DataFrame.
    Meter columns: timestamp, v_shunt, phase, current_mA, power_mW, elapsed_s
    """
    meta, events_rows, meter_rows = {}, [], []
    section, events_header = None, None

    with open(path, encoding='utf-8') as fh:
        for raw in fh:
            line = raw.strip()
            if not line:
                continue
            if   line == '# META':   section = 'meta';   continue
            elif line == '# EVENTS': section = 'events'; continue
            elif line == '# METER':  section = 'meter';  continue

            if section == 'meta' and ',' in line:
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

    events_df = (pd.DataFrame(events_rows, columns=events_header)
                 if events_rows and events_header else pd.DataFrame())

    if meter_rows:
        meter_df = pd.DataFrame(meter_rows, columns=['timestamp', 'v_shunt', 'phase'])
        meter_df['timestamp'] = pd.to_datetime(meter_df['timestamp'])
        meter_df['v_shunt']   = pd.to_numeric(meter_df['v_shunt'], errors='coerce')
        meter_df = meter_df.dropna(subset=['v_shunt'])

        shunt = float(meta.get('shunt_ohms', SHUNT_DEFAULT))
        v_sup = float(meta.get('v_supply',   V_SUPPLY))

        # I = V_shunt / R_shunt  (result in A, *1e3 -> mA)
        meter_df['current_mA'] = (meter_df['v_shunt'] / shunt) * 1e3
        # P = I * V_supply  (mA * V = mW)
        meter_df['power_mW']   = meter_df['current_mA'] * v_sup
        meter_df['elapsed_s']  = (
            meter_df['timestamp'] - meter_df['timestamp'].iloc[0]
        ).dt.total_seconds()
    else:
        meter_df = pd.DataFrame()

    return {'meta': meta, 'events': events_df, 'meter': meter_df}


# ── Validation ────────────────────────────────────────────────────────────────
def validate_group(group_key, file_list, parsed_list):
    """
    Checks: (1) exactly REQUIRED_RUNS files, (2) no duplicate run numbers,
    (3) consistent payload phase set across all runs.
    Returns True if all pass.
    """
    module, strategy = group_key
    label = f"{module} / {strategy}"
    ok = True

    run_nums = [info['run'] for info in file_list]

    if len(run_nums) != REQUIRED_RUNS:
        print(f"  [WARN] {label}: expected {REQUIRED_RUNS} runs, found {len(run_nums)}")
        ok = False
    else:
        print(f"  [OK]   {label}: {REQUIRED_RUNS} runs present")

    seen, dups = set(), []
    for r in run_nums:
        if r in seen: dups.append(r)
        seen.add(r)
    if dups:
        print(f"  [WARN] {label}: duplicate run numbers: {dups}")
        ok = False

    payload_sets = []
    for p in parsed_list:
        phases = set(p['meter']['phase'].unique()) if not p['meter'].empty else set()
        payload_sets.append(frozenset(ph for ph in phases if ph.startswith('tx_')))

    if len(set(payload_sets)) > 1:
        print(f"  [WARN] {label}: payload phase sets differ across runs!")
        ok = False
    else:
        sizes = sorted(int(ph.split('_')[1]) for ph in list(payload_sets)[0]) if payload_sets else []
        print(f"  [OK]   {label}: consistent payload sizes: {sizes}")

    return ok


# ── Energy integration ────────────────────────────────────────────────────────
def _trapz_energy_mJ(grp: pd.DataFrame) -> float:
    """
    Trapezoidal integration of power_mW over real sample timestamps.
    Units: mW * s = mJ  (no further conversion needed).
    """
    dt = np.diff(grp['timestamp'].values.astype(np.int64)) / 1e9  # ns -> s
    if len(dt) == 0:
        # Single sample fallback: assume ~3 ms typical meter interval
        return float(grp['power_mW'].iloc[0] * 0.003)
    pw_mid = (grp['power_mW'].values[:-1] + grp['power_mW'].values[1:]) / 2.0
    return float(np.sum(pw_mid * dt))


# ── Per-run summary ───────────────────────────────────────────────────────────
def summarise_run(parsed, run_num):
    """
    Returns a summary dict for one run.

    mean_power_active_mW:
        Energy-weighted mean power = total_energy_mJ / total_duration_s.
        This is the correct single-number power summary: it avoids over-weighting
        short low-energy payload phases relative to long high-energy ones.
        It equals what you'd get from integrating the entire active waveform
        and dividing by its duration.

    total_energy_mJ:
        Sum of per-payload energies across ALL payload sizes in this run.
        Gives a single "how much did this module consume in this entire experiment run" figure.

    payload_stats per-entry:
        energy_mJ          – trapezoidal integral over that payload's tx phase (mJ)
        efficiency_mJ_per_KB – energy_mJ / (payload_bytes / 1024)
                               lower = more efficient per byte transferred
    """
    meter = parsed['meter']
    if meter.empty:
        return None

    baseline_df   = meter[meter['phase'] == 'baseline']
    baseline_mean = baseline_df['current_mA'].mean()
    # pandas .std() defaults to ddof=1 (sample SD) -- correct for within-run noise
    baseline_std  = baseline_df['current_mA'].std()

    tx_mask = meter['phase'].str.startswith('tx_')

    payload_stats = []
    for phase_label, grp in meter[tx_mask].groupby('phase'):
        grp        = grp.reset_index(drop=True)
        size_bytes = int(phase_label.split('_')[1])
        duration_s = (grp['timestamp'].iloc[-1] - grp['timestamp'].iloc[0]).total_seconds()
        energy_mJ  = _trapz_energy_mJ(grp)
        mean_pw    = grp['power_mW'].mean()
        size_kb    = size_bytes / 1024.0
        efficiency = energy_mJ / size_kb if size_kb > 0 else np.nan

        payload_stats.append({
            'payload_bytes':        size_bytes,
            'duration_s':           duration_s,
            'mean_power_mW':        mean_pw,
            'energy_mJ':            energy_mJ,
            'efficiency_mJ_per_KB': efficiency,
        })

    payload_stats.sort(key=lambda x: x['payload_bytes'])

    total_energy_mJ  = sum(ps['energy_mJ']  for ps in payload_stats)
    total_duration_s = sum(ps['duration_s'] for ps in payload_stats)
    mean_power_active = (total_energy_mJ / total_duration_s
                         if total_duration_s > 0 else np.nan)

    return {
        'run':                  run_num,
        'mean_power_active_mW': mean_power_active,
        'total_energy_mJ':      total_energy_mJ,
        'baseline_mean_mA':     baseline_mean,
        'baseline_std_mA':      baseline_std,
        'payload_stats':        payload_stats,
        'meter':                meter,
    }


# ── Shared plot helpers ───────────────────────────────────────────────────────
def _size_label(sz):
    if sz < 1024:          return f'{sz}B'
    elif sz < 1024**2:     return f'{sz // 1024}KB'
    else:                  return f'{sz // 1024**2}MB'


def _collect(summaries, key):
    """dict: payload_bytes -> list of metric values across all runs."""
    d = defaultdict(list)
    for s in summaries:
        for ps in s['payload_stats']:
            d[ps['payload_bytes']].append(ps[key])
    return d


def _errorbar_plot(ax, sizes, payload_data, ylabel, title):
    """
    Scatter of individual run values + mean ± 1 SD (ddof=1) error bars.
    Used for energy and efficiency plots.
    """
    x     = np.arange(len(sizes))
    means = [np.mean(payload_data[sz])        for sz in sizes]
    stds  = [np.std(payload_data[sz], ddof=1) for sz in sizes]  # sample SD

    for i, sz in enumerate(sizes):
        ax.scatter([i] * len(payload_data[sz]), payload_data[sz],
                   color='steelblue', alpha=0.30, s=12, zorder=2)
    ax.errorbar(x, means, yerr=stds, fmt='o-', color='tomato',
                linewidth=1.5, capsize=4, zorder=3, label='Mean ± 1 SD (n=30)')
    ax.set_xticks(x)
    ax.set_xticklabels([_size_label(sz) for sz in sizes],
                       rotation=45, ha='right', fontsize=8)
    ax.set_ylabel(ylabel)
    ax.set_title(title)
    ax.legend(fontsize=8)


def _save(fig, out_dir, fname):
    path = out_dir / fname
    fig.savefig(path, dpi=150)
    plt.close(fig)
    print(f"  Saved: {fname}")


# ── Plot functions ────────────────────────────────────────────────────────────

def plot_mean_power_per_run(summaries, module, strategy, out_dir):
    """
    Bar chart of energy-weighted mean active power (mW) per run.
    = total_energy_mJ / total_duration_s for each run.
    Shows whether power draw is consistent across runs.
    """
    runs  = [s['run']                  for s in summaries]
    power = [s['mean_power_active_mW'] for s in summaries]
    grand = np.nanmean(power)

    fig, ax = plt.subplots(figsize=(12, 4))
    ax.bar(runs, power, color='steelblue', edgecolor='white', linewidth=0.5)
    ax.axhline(grand, color='tomato', linestyle='--', linewidth=1.2,
               label=f'Mean = {grand:.2f} mW')
    ax.set_xlabel('Run #')
    ax.set_ylabel('Mean Active Power (mW)')
    ax.set_title(f'{module.upper()} · {strategy} — Energy-Weighted Mean Active Power per Run')
    ax.set_xticks(runs)
    ax.set_xticklabels([str(r) for r in runs], fontsize=7, rotation=45)
    ax.legend()
    fig.tight_layout()
    _save(fig, out_dir, f"{module}_{strategy}_mean_power_per_run.png")


def plot_total_energy_per_run(summaries, module, strategy, out_dir):
    """
    Bar chart of total energy consumed (mJ) in each run (all payload sizes summed).
    Shows experiment-level consumption variability across runs.
    """
    runs   = [s['run']             for s in summaries]
    totals = [s['total_energy_mJ'] for s in summaries]
    grand  = np.nanmean(totals)
    sd     = np.nanstd(totals, ddof=1)  # sample SD across runs

    fig, ax = plt.subplots(figsize=(12, 4))
    ax.bar(runs, totals, color='mediumseagreen', edgecolor='white', linewidth=0.5)
    ax.axhline(grand, color='tomato', linestyle='--', linewidth=1.2,
               label=f'Mean = {grand:.1f} mJ  (SD = {sd:.1f} mJ)')
    ax.set_xlabel('Run #')
    ax.set_ylabel('Total Energy (mJ)')
    ax.set_title(f'{module.upper()} · {strategy} — Total Energy per Run (all payload sizes summed)')
    ax.set_xticks(runs)
    ax.set_xticklabels([str(r) for r in runs], fontsize=7, rotation=45)
    ax.legend()
    fig.tight_layout()
    _save(fig, out_dir, f"{module}_{strategy}_total_energy_per_run.png")


def plot_run_duration_per_payload(summaries, module, strategy, out_dir):
    """
    Box plot: distribution (across 30 runs) of TX phase duration per payload size.
    Reveals timing variability — e.g. wireless connection/negotiation jitter.
    """
    payload_data = _collect(summaries, 'duration_s')
    sizes = sorted(payload_data.keys())
    data  = [payload_data[sz] for sz in sizes]

    fig, ax = plt.subplots(figsize=(max(10, len(sizes) * 0.85), 5))
    bp = ax.boxplot(data, patch_artist=True,
                    medianprops=dict(color='tomato', linewidth=1.5))
    for patch in bp['boxes']:
        patch.set_facecolor('lightsteelblue')
    ax.set_xticklabels([_size_label(sz) for sz in sizes],
                       rotation=45, ha='right', fontsize=8)
    ax.set_xlabel('Payload Size')
    ax.set_ylabel('TX Phase Duration (s)')
    ax.set_title(f'{module.upper()} · {strategy} — TX Duration per Payload Size (n=30 runs)')
    fig.tight_layout()
    _save(fig, out_dir, f"{module}_{strategy}_run_duration_per_payload.png")


def plot_energy_per_payload(summaries, module, strategy, out_dir):
    """
    Mean ± SD energy (mJ) per payload size with per-run scatter.
    Primary plot for cross-module energy comparison.
    SD uses ddof=1 (sample SD across 30 runs).
    """
    payload_data = _collect(summaries, 'energy_mJ')
    sizes = sorted(payload_data.keys())

    fig, ax = plt.subplots(figsize=(max(10, len(sizes) * 0.85), 5))
    _errorbar_plot(ax, sizes, payload_data,
                   ylabel='Energy (mJ)',
                   title=f'{module.upper()} · {strategy} — Energy per Payload Size')
    fig.tight_layout()
    _save(fig, out_dir, f"{module}_{strategy}_energy_per_payload.png")


def plot_efficiency_per_payload(summaries, module, strategy, out_dir):
    """
    Mean ± SD energy efficiency (mJ/KB) per payload size with per-run scatter.
    Normalises energy for payload size: shows whether larger payloads amortise
    connection/framing overhead, delivering more bytes per mJ.
    Lower mJ/KB = more efficient.
    SD uses ddof=1 (sample SD across 30 runs).
    Y-axis is log-scale because values span several orders of magnitude
    (1B is extremely inefficient per KB; 1MB approaches the physical minimum).
    """
    payload_data = _collect(summaries, 'efficiency_mJ_per_KB')
    sizes = sorted(payload_data.keys())

    fig, ax = plt.subplots(figsize=(max(10, len(sizes) * 0.85), 5))
    _errorbar_plot(ax, sizes, payload_data,
                   ylabel='Energy Efficiency (mJ / KB)  [log scale]',
                   title=f'{module.upper()} · {strategy} — Energy Efficiency per Payload Size')
    try:
        ax.set_yscale('log')
    except Exception:
        pass
    fig.tight_layout()
    _save(fig, out_dir, f"{module}_{strategy}_efficiency_per_payload.png")


def plot_current_trace_overlay(summaries, module, strategy, out_dir):
    """
    Overlay of current (mA) vs elapsed time for ALL runs.
    Each trace is one complete experiment run: baseline phase followed by every
    payload size transmitted sequentially, with idle periods between payloads.
    Overlaying all 30 runs reveals waveform consistency and outlier runs.
    """
    n    = len(summaries)
    cmap = _cmap('tab20' if n > 10 else 'tab10', n)

    fig, ax = plt.subplots(figsize=(16, 5))
    for i, s in enumerate(summaries):
        meter = s['meter']
        ax.plot(meter['elapsed_s'], meter['current_mA'],
                linewidth=0.5, alpha=0.5, color=cmap(i), label=f'Run {s["run"]}')
    ax.set_xlabel('Elapsed Time (s)')
    ax.set_ylabel('Current (mA)')
    line1 = f'{module.upper()} [{strategy}] -- Current Draw: All {n} Runs Overlaid'
    line2 = '(each trace = full experiment: baseline + all payload sizes in sequence)'
    ax.set_title(line1 + chr(10) + line2)
    ax.legend(fontsize=6, ncol=5, loc='upper left')
    fig.tight_layout()
    _save(fig, out_dir, f"{module}_{strategy}_current_trace_overlay.png")


def plot_baseline_stability(summaries, module, strategy, out_dir):
    """
    Per-run baseline current (mean ± within-run SD).
    Checks for thermal drift or power-supply instability across the 30 runs.
    """
    runs  = [s['run']              for s in summaries]
    means = [s['baseline_mean_mA'] for s in summaries]
    stds  = [s['baseline_std_mA']  for s in summaries]

    fig, ax = plt.subplots(figsize=(12, 4))
    ax.errorbar(runs, means, yerr=stds, fmt='o-', color='steelblue',
                capsize=4, linewidth=1.2, markersize=4)
    ax.axhline(np.nanmean(means), color='tomato', linestyle='--', linewidth=1,
               label=f'Mean = {np.nanmean(means):.3f} mA')
    ax.set_xlabel('Run #')
    ax.set_ylabel('Baseline Current (mA)')
    ax.set_title(f'{module.upper()} · {strategy} — Baseline Current Stability across Runs')
    ax.set_xticks(runs)
    ax.set_xticklabels([str(r) for r in runs], fontsize=7, rotation=45)
    ax.legend()
    fig.tight_layout()
    _save(fig, out_dir, f"{module}_{strategy}_baseline_stability.png")


# ── CSV export ────────────────────────────────────────────────────────────────
def export_summary_csv(summaries, module, strategy, out_dir):
    """Tidy flat CSV: one row per (run × payload_size) with all derived metrics."""
    rows = []
    for s in summaries:
        for ps in s['payload_stats']:
            rows.append({
                'module':                   module,
                'strategy':                 strategy,
                'run':                      s['run'],
                'payload_bytes':            ps['payload_bytes'],
                'duration_s':               round(ps['duration_s'],             6),
                'mean_power_mW':            round(ps['mean_power_mW'],          4),
                'energy_mJ':                round(ps['energy_mJ'],              6),
                'efficiency_mJ_per_KB':     round(ps['efficiency_mJ_per_KB'],   6),
                'run_total_energy_mJ':      round(s['total_energy_mJ'],         4),
                'run_mean_active_power_mW': round(s['mean_power_active_mW'],    4),
                'baseline_mean_mA':         round(s['baseline_mean_mA'],        5),
                'baseline_std_mA':          round(s['baseline_std_mA'],         5),
            })
    df = pd.DataFrame(rows)
    fname = out_dir / f"{module}_{strategy}_summary.csv"
    df.to_csv(fname, index=False)
    print(f"  Saved: {fname.name}")


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    if not DATA_DIR.exists():
        print(f"[ERROR] Data directory not found: {DATA_DIR}")
        print("  Create a folder called 'analyze_data' next to this script.")
        sys.exit(1)

    PLOTS_DIR.mkdir(parents=True, exist_ok=True)

    csv_files = sorted(DATA_DIR.glob("*.csv"))
    if not csv_files:
        print(f"[ERROR] No CSV files found in {DATA_DIR}")
        sys.exit(1)

    groups, skipped = defaultdict(list), []
    for f in csv_files:
        result = parse_filename(f)
        if result is None:
            skipped.append(f.name); continue
        module, strategy, run_num = result
        groups[(module, strategy)].append({'path': f, 'run': run_num})

    if skipped:
        print(f"\n[WARN] Skipped {len(skipped)} file(s) with unrecognised names:")
        for s in skipped: print(f"  {s}")

    print(f"\nFound {len(groups)} experiment group(s) in {DATA_DIR}:\n")
    all_ok = True

    for group_key, file_list in sorted(groups.items()):
        module, strategy = group_key
        file_list_sorted = sorted(file_list, key=lambda x: x['run'])
        print(f"━━ {module.upper()} / {strategy} ({len(file_list)} runs) ━━")

        parsed_list = [parse_csv(info['path']) for info in file_list_sorted]
        all_ok = validate_group(group_key, file_list_sorted, parsed_list) and all_ok

        summaries = [s for s in
                     (summarise_run(p, i['run']) for p, i in zip(parsed_list, file_list_sorted))
                     if s is not None]

        if not summaries:
            print("  [WARN] No valid meter data — skipping plots."); continue

        plot_mean_power_per_run(       summaries, module, strategy, PLOTS_DIR)
        plot_total_energy_per_run(     summaries, module, strategy, PLOTS_DIR)
        plot_run_duration_per_payload( summaries, module, strategy, PLOTS_DIR)
        plot_energy_per_payload(       summaries, module, strategy, PLOTS_DIR)
        plot_efficiency_per_payload(   summaries, module, strategy, PLOTS_DIR)
        plot_current_trace_overlay(    summaries, module, strategy, PLOTS_DIR)
        plot_baseline_stability(       summaries, module, strategy, PLOTS_DIR)
        export_summary_csv(            summaries, module, strategy, PLOTS_DIR)
        print()

    print("✓ All validation checks passed." if all_ok
          else "⚠ Some validation checks FAILED — see warnings above.")
    print(f"\nAll outputs saved to: {PLOTS_DIR}")


if __name__ == '__main__':
    main()