"""
BTR Experiment Analysis Script
================================
Reads all CSVs from the `analyze_data/` folder (placed alongside this script),
validates experiment consistency, and produces per-experiment-group plots.

Filename convention:
    <module>_<strategy>_run<NN>.csv       e.g. ble_nrf52_full_payload_run01.csv
    shortcircuit.csv                      zero-offset calibration run (probes shorted)

SHORT-CIRCUIT CALIBRATION
--------------------------
Place a file named `shortcircuit.csv` in the `analyze_data/` folder.
It must have the same CSV format as experiment files (# METER block with
timestamp, v_shunt, phase columns). Phase labels are ignored — all samples
are treated as zero-input readings.

From this file the script computes:
    mu_offset   – mean voltage when input = 0 V  (systematic bias)
    sigma_noise – SD of those readings            (random noise floor)

Every v_shunt reading in experiment files is then corrected:
    v_corrected = v_measured - mu_offset

Total voltage uncertainty per sample (1-sigma, combined in quadrature):
    sigma_v = sqrt(sigma_noise^2 + sigma_instrument^2)

where sigma_instrument comes from the HMC8012 DC voltage spec:
    ±(0.05% of reading + 0.005% of range)
    Range used: 600 mV  ->  sigma_instrument per sample varies with reading.

This propagates to current uncertainty:
    sigma_I = sigma_v / R_shunt   [in mA]

And to energy uncertainty via the trapezoidal rule:
    sigma_E = sqrt( sum_i( (dt_i * sigma_P_i)^2 ) )   [in mJ]
where sigma_P_i = sigma_I_i * V_supply.

Any payload phase whose mean current is below SNR_THRESHOLD * sigma_I_floor
is flagged as UNRELIABLE in the summary CSV and marked on plots.

Outputs (saved to analyze_data/plots/):
    shortcircuit_noise_floor.png           – noise floor characterisation plot
    <module>_<strategy>_mean_power_per_run.png
    <module>_<strategy>_total_energy_per_run.png
    <module>_<strategy>_run_duration_per_payload.png
    <module>_<strategy>_energy_per_payload.png
    <module>_<strategy>_efficiency_per_payload.png
    <module>_<strategy>_current_trace_overlay.png
    <module>_<strategy>_baseline_stability.png
    <module>_<strategy>_summary.csv

STATISTICS NOTE
    Cross-run SD uses ddof=1 (sample SD).
    Within-run SD uses pandas default (also ddof=1).
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
V_SUPPLY      = 5.013517   # V   (measured; overridden by CSV meta if present)
SHUNT_DEFAULT = 1.131667   # Ohm (measured; overridden by CSV meta if present)

# HMC8012 DC voltage spec
HMC8012_READING_PCT = 0.0005   # 0.05% of reading
HMC8012_RANGE_PCT   = 0.00005  # 0.005% of range
HMC8012_RANGE_V     = 0.600    # 600 mV range (appropriate for shunt voltages)

# Signal-to-noise threshold: phases with mean current < this multiple of the
# noise floor current are flagged as unreliable
SNR_THRESHOLD = 3.0


# ── Colour helper ─────────────────────────────────────────────────────────────
def _cmap(name, n):
    try:
        return plt.colormaps[name].resampled(n)
    except AttributeError:
        return cm.get_cmap(name, n)


# ── Instrument uncertainty (HMC8012 spec) ─────────────────────────────────────
def _sigma_instrument_V(v_reading: float) -> float:
    """
    1-sigma voltage uncertainty from HMC8012 DC spec:
        ±(0.05% of reading + 0.005% of range)
    Treated as a rectangular distribution -> divide by sqrt(3) for 1-sigma.
    """
    half_width = (HMC8012_READING_PCT * abs(v_reading)
                  + HMC8012_RANGE_PCT * HMC8012_RANGE_V)
    return half_width / np.sqrt(3)


# ── Short-circuit calibration ─────────────────────────────────────────────────
def load_noise_floor(data_dir: Path, plots_dir: Path) -> dict:
    """
    Reads shortcircuit.csv, computes offset and noise floor, saves a
    diagnostic plot, and returns a dict:
        mu_offset_V    – mean shunt voltage with probes shorted (V)
        sigma_noise_V  – SD of those readings (V)
        sigma_floor_V  – combined noise floor per sample (noise + instrument)
        sigma_I_floor_mA – noise floor expressed as current (mA)
        n_samples      – number of samples used
    If the file is not found, returns None and prints a warning.
    """
    sc_path = data_dir / "shortcircuit.csv"
    if not sc_path.exists():
        print("  [WARN] shortcircuit.csv not found in analyze_data/.")
        print("         Uncertainty correction will use instrument spec only.")
        print("         To enable full correction: short the probes, record a")
        print("         CSV run, name it shortcircuit.csv, place it in analyze_data/.")
        return None

    # Parse meter block (reuse same format as experiment files)
    rows = []
    in_meter = False
    with open(sc_path, encoding='utf-8') as fh:
        for raw in fh:
            line = raw.strip()
            if line == '# METER':
                in_meter = True; continue
            if in_meter and line and not line.startswith('timestamp'):
                parts = line.split(',')
                if len(parts) >= 2:
                    rows.append(parts[1])   # v_shunt column only

    if not rows:
        print("  [WARN] shortcircuit.csv has no meter data. Skipping calibration.")
        return None

    voltages = pd.to_numeric(pd.Series(rows), errors='coerce').dropna().values
    n = len(voltages)

    mu    = float(np.mean(voltages))
    sigma = float(np.std(voltages, ddof=1))

    # Representative instrument uncertainty at near-zero reading
    sigma_inst = _sigma_instrument_V(mu)

    # Combined noise floor (in quadrature)
    sigma_floor = np.sqrt(sigma**2 + sigma_inst**2)

    # Convert to current
    sigma_I_floor_mA = (sigma_floor / SHUNT_DEFAULT) * 1e3

    print(f"  [Calibration] n={n} samples")
    print(f"    Offset  mu  = {mu*1e3:+.4f} mV  ({mu:.6f} V)")
    print(f"    Noise  sigma= {sigma*1e3:.4f} mV  (random, ddof=1)")
    print(f"    Instrument  = {sigma_inst*1e3:.4f} mV  (HMC8012 spec)")
    print(f"    Combined floor = {sigma_floor*1e3:.4f} mV  -> {sigma_I_floor_mA:.4f} mA")
    print(f"    Reliable signal threshold (>{SNR_THRESHOLD}x floor): "
          f"{SNR_THRESHOLD * sigma_I_floor_mA:.4f} mA")

    # ── Diagnostic plot ──
    fig, axes = plt.subplots(1, 2, figsize=(12, 4))

    ax = axes[0]
    ax.plot(voltages * 1e3, linewidth=0.6, color='steelblue', alpha=0.7)
    ax.axhline(mu * 1e3,           color='tomato',       linestyle='--', linewidth=1.2,
               label=f'Mean = {mu*1e3:+.4f} mV')
    ax.axhline((mu + sigma) * 1e3, color='orange',       linestyle=':',  linewidth=1.0,
               label=f'+1 SD = {sigma*1e3:.4f} mV')
    ax.axhline((mu - sigma) * 1e3, color='orange',       linestyle=':',  linewidth=1.0)
    ax.set_xlabel('Sample #')
    ax.set_ylabel('Shunt Voltage (mV)')
    ax.set_title('Short-Circuit Run: Raw Readings')
    ax.legend(fontsize=8)

    ax = axes[1]
    ax.hist(voltages * 1e3, bins=40, color='steelblue', edgecolor='white',
            linewidth=0.4, density=True)
    ax.axvline(mu * 1e3,           color='tomato', linestyle='--', linewidth=1.5,
               label=f'Mean offset = {mu*1e3:+.4f} mV')
    ax.axvline((mu + sigma_floor) * 1e3, color='orange', linestyle=':', linewidth=1.2,
               label=f'Combined floor = {sigma_floor*1e3:.4f} mV')
    ax.axvline((mu - sigma_floor) * 1e3, color='orange', linestyle=':', linewidth=1.2)
    ax.set_xlabel('Shunt Voltage (mV)')
    ax.set_ylabel('Density')
    ax.set_title('Short-Circuit Voltage Distribution')
    ax.legend(fontsize=8)

    fig.suptitle(f'Noise Floor Characterisation  |  n={n} samples  |  '
                 f'Floor = {sigma_floor*1e3:.4f} mV = {sigma_I_floor_mA:.4f} mA',
                 fontsize=10)
    fig.tight_layout()
    _save(fig, plots_dir, "shortcircuit_noise_floor.png")

    return {
        'mu_offset_V':       mu,
        'sigma_noise_V':     sigma,
        'sigma_floor_V':     sigma_floor,
        'sigma_I_floor_mA':  sigma_I_floor_mA,
        'n_samples':         n,
    }


# ── Filename parsing ──────────────────────────────────────────────────────────
def parse_filename(path: Path):
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
def parse_csv(path: Path, noise: dict | None):
    """
    Parse a BTR CSV file.
    If noise is provided:
      - v_shunt is corrected by subtracting mu_offset
      - per-sample voltage uncertainty is computed and propagated to current & power
    Meter columns added: current_mA, power_mW, elapsed_s,
                         sigma_I_mA (per-sample 1-sigma current uncertainty),
                         sigma_P_mW (per-sample 1-sigma power uncertainty)
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

        # ── Offset correction ──
        if noise is not None:
            meter_df['v_shunt'] = meter_df['v_shunt'] - noise['mu_offset_V']

        # ── Derived quantities ──
        meter_df['current_mA'] = (meter_df['v_shunt'] / shunt) * 1e3
        meter_df['power_mW']   = meter_df['current_mA'] * v_sup

        # ── Per-sample uncertainty propagation ──
        if noise is not None:
            # sigma_v combines noise floor and instrument spec per sample
            sigma_v = np.sqrt(
                noise['sigma_noise_V']**2
                + meter_df['v_shunt'].apply(_sigma_instrument_V).values**2
            )
        else:
            # instrument spec only
            sigma_v = meter_df['v_shunt'].apply(_sigma_instrument_V).values

        meter_df['sigma_I_mA'] = (sigma_v / shunt) * 1e3
        meter_df['sigma_P_mW'] = meter_df['sigma_I_mA'] * v_sup

        meter_df['elapsed_s'] = (
            meter_df['timestamp'] - meter_df['timestamp'].iloc[0]
        ).dt.total_seconds()
    else:
        meter_df = pd.DataFrame()

    return {'meta': meta, 'events': events_df, 'meter': meter_df}


# ── Validation ────────────────────────────────────────────────────────────────
def validate_group(group_key, file_list, parsed_list):
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


# ── Energy integration with uncertainty ──────────────────────────────────────
def _trapz_energy_and_uncertainty(grp: pd.DataFrame):
    """
    Trapezoidal energy integral (mJ) and propagated 1-sigma uncertainty (mJ).

    Energy:
        E = sum_i( (P_i + P_{i+1})/2 * dt_i )      [mW * s = mJ]

    Uncertainty propagation (independent samples, in quadrature):
        dE/dP_i = (dt_{i-1} + dt_i) / 2  for interior points
        dE/dP_0 = dt_0 / 2,   dE/dP_N = dt_{N-1} / 2
        sigma_E = sqrt( sum_i( (dE/dP_i * sigma_P_i)^2 ) )
    """
    dt = np.diff(grp['timestamp'].values.astype(np.int64)) / 1e9  # ns -> s
    pw = grp['power_mW'].values
    sp = grp['sigma_P_mW'].values

    if len(dt) == 0:
        energy = float(pw[0] * 0.003)
        sigma  = float(sp[0] * 0.003)
        return energy, sigma

    # midpoint power for trapezoid
    pw_mid = (pw[:-1] + pw[1:]) / 2.0
    energy = float(np.sum(pw_mid * dt))

    # sensitivity of E to each power sample
    sens = np.zeros(len(pw))
    sens[0]  = dt[0] / 2.0
    sens[-1] = dt[-1] / 2.0
    for i in range(1, len(pw) - 1):
        sens[i] = (dt[i-1] + dt[i]) / 2.0

    sigma = float(np.sqrt(np.sum((sens * sp)**2)))
    return energy, sigma


# ── Per-run summary ───────────────────────────────────────────────────────────
def summarise_run(parsed, run_num, noise: dict | None):
    """
    Summarise a single run. Returns dict with per-payload stats including
    energy uncertainty and SNR flag.
    """
    meter = parsed['meter']
    if meter.empty:
        return None

    # Noise floor current (for SNR check)
    sigma_I_floor = noise['sigma_I_floor_mA'] if noise else 0.0

    baseline_df   = meter[meter['phase'] == 'baseline']
    baseline_mean = baseline_df['current_mA'].mean()
    baseline_std  = baseline_df['current_mA'].std()   # ddof=1 via pandas

    tx_mask = meter['phase'].str.startswith('tx_')

    payload_stats = []
    for phase_label, grp in meter[tx_mask].groupby('phase'):
        grp        = grp.reset_index(drop=True)
        size_bytes = int(phase_label.split('_')[1])
        duration_s = (grp['timestamp'].iloc[-1] - grp['timestamp'].iloc[0]).total_seconds()

        energy_mJ, sigma_E_mJ = _trapz_energy_and_uncertainty(grp)

        mean_pw      = grp['power_mW'].mean()
        mean_I       = grp['current_mA'].mean()
        size_kb      = size_bytes / 1024.0
        efficiency   = energy_mJ / size_kb if size_kb > 0 else np.nan
        eff_sigma    = sigma_E_mJ / size_kb if size_kb > 0 else np.nan

        # SNR: is the mean current distinguishable from the noise floor?
        snr          = mean_I / sigma_I_floor if sigma_I_floor > 0 else np.inf
        unreliable   = snr < SNR_THRESHOLD

        payload_stats.append({
            'payload_bytes':        size_bytes,
            'duration_s':           duration_s,
            'mean_power_mW':        mean_pw,
            'mean_current_mA':      mean_I,
            'energy_mJ':            energy_mJ,
            'sigma_energy_mJ':      sigma_E_mJ,
            'efficiency_mJ_per_KB': efficiency,
            'sigma_eff_mJ_per_KB':  eff_sigma,
            'snr':                  snr,
            'unreliable':           unreliable,
        })

    payload_stats.sort(key=lambda x: x['payload_bytes'])

    total_energy_mJ  = sum(ps['energy_mJ']  for ps in payload_stats)
    total_duration_s = sum(ps['duration_s'] for ps in payload_stats)
    # Propagate total energy uncertainty in quadrature across payload phases
    total_sigma_E    = float(np.sqrt(sum(ps['sigma_energy_mJ']**2 for ps in payload_stats)))
    mean_power_active = total_energy_mJ / total_duration_s if total_duration_s > 0 else np.nan

    return {
        'run':                  run_num,
        'mean_power_active_mW': mean_power_active,
        'total_energy_mJ':      total_energy_mJ,
        'total_sigma_E_mJ':     total_sigma_E,
        'baseline_mean_mA':     baseline_mean,
        'baseline_std_mA':      baseline_std,
        'payload_stats':        payload_stats,
        'meter':                meter,
    }


# ── Shared plot helpers ───────────────────────────────────────────────────────
def _size_label(sz):
    if sz < 1024:      return f'{sz}B'
    elif sz < 1024**2: return f'{sz // 1024}KB'
    else:              return f'{sz // 1024**2}MB'


def _collect(summaries, key):
    d = defaultdict(list)
    for s in summaries:
        for ps in s['payload_stats']:
            d[ps['payload_bytes']].append(ps[key])
    return d


def _unreliable_sizes(summaries):
    """Return set of payload sizes flagged as unreliable in ANY run."""
    bad = set()
    for s in summaries:
        for ps in s['payload_stats']:
            if ps['unreliable']:
                bad.add(ps['payload_bytes'])
    return bad


def _errorbar_plot(ax, sizes, payload_data, ylabel, title, unreliable=None):
    """
    Per-run scatter + mean ± 1 SD error bars.
    Unreliable payload sizes (below SNR threshold) are shown in grey
    with a hatched background and labelled.
    """
    unreliable = unreliable or set()
    x     = np.arange(len(sizes))
    means = [np.mean(payload_data[sz])        for sz in sizes]
    stds  = [np.std(payload_data[sz], ddof=1) for sz in sizes]

    for i, sz in enumerate(sizes):
        colour = 'lightgrey' if sz in unreliable else 'steelblue'
        ax.scatter([i] * len(payload_data[sz]), payload_data[sz],
                   color=colour, alpha=0.40, s=12, zorder=2)
        if sz in unreliable:
            ax.axvspan(i - 0.4, i + 0.4, color='lightyellow',
                       alpha=0.6, zorder=1, linewidth=0)

    reliable_x     = [x[i] for i, sz in enumerate(sizes) if sz not in unreliable]
    reliable_means = [means[i] for i, sz in enumerate(sizes) if sz not in unreliable]
    reliable_stds  = [stds[i]  for i, sz in enumerate(sizes) if sz not in unreliable]
    unreliable_x   = [x[i] for i, sz in enumerate(sizes) if sz in unreliable]
    unreliable_m   = [means[i] for i, sz in enumerate(sizes) if sz in unreliable]
    unreliable_s   = [stds[i]  for i, sz in enumerate(sizes) if sz in unreliable]

    if reliable_x:
        ax.errorbar(reliable_x, reliable_means, yerr=reliable_stds,
                    fmt='o-', color='tomato', linewidth=1.5, capsize=4,
                    zorder=3, label='Mean +/- 1 SD (n=30)')
    if unreliable_x:
        ax.errorbar(unreliable_x, unreliable_m, yerr=unreliable_s,
                    fmt='s--', color='grey', linewidth=1.0, capsize=4,
                    zorder=3, label='Mean +/- 1 SD (below SNR threshold)')

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
    runs  = [s['run']                  for s in summaries]
    power = [s['mean_power_active_mW'] for s in summaries]
    grand = np.nanmean(power)

    fig, ax = plt.subplots(figsize=(12, 4))
    ax.bar(runs, power, color='steelblue', edgecolor='white', linewidth=0.5)
    ax.axhline(grand, color='tomato', linestyle='--', linewidth=1.2,
               label=f'Mean = {grand:.2f} mW')
    ax.set_xlabel('Run #')
    ax.set_ylabel('Mean Active Power (mW)')
    ax.set_title(f'{module.upper()} / {strategy} -- Energy-Weighted Mean Active Power per Run')
    ax.set_xticks(runs)
    ax.set_xticklabels([str(r) for r in runs], fontsize=7, rotation=45)
    ax.legend()
    fig.tight_layout()
    _save(fig, out_dir, f"{module}_{strategy}_mean_power_per_run.png")


def plot_total_energy_per_run(summaries, module, strategy, out_dir):
    runs   = [s['run']             for s in summaries]
    totals = [s['total_energy_mJ'] for s in summaries]
    sigmas = [s['total_sigma_E_mJ'] for s in summaries]
    grand  = np.nanmean(totals)
    sd     = np.nanstd(totals, ddof=1)

    fig, ax = plt.subplots(figsize=(12, 4))
    ax.bar(runs, totals, color='mediumseagreen', edgecolor='white', linewidth=0.5,
           label='Total energy per run')
    ax.errorbar(runs, totals, yerr=sigmas, fmt='none', color='black',
                capsize=3, linewidth=1.0, label='Measurement uncertainty (1 sigma)')
    ax.axhline(grand, color='tomato', linestyle='--', linewidth=1.2,
               label=f'Mean = {grand:.1f} mJ  (SD = {sd:.1f} mJ)')
    ax.set_xlabel('Run #')
    ax.set_ylabel('Total Energy (mJ)')
    ax.set_title(f'{module.upper()} / {strategy} -- Total Energy per Run (all payload sizes summed)')
    ax.set_xticks(runs)
    ax.set_xticklabels([str(r) for r in runs], fontsize=7, rotation=45)
    ax.legend(fontsize=8)
    fig.tight_layout()
    _save(fig, out_dir, f"{module}_{strategy}_total_energy_per_run.png")


def plot_run_duration_per_payload(summaries, module, strategy, out_dir):
    payload_data = _collect(summaries, 'duration_s')
    sizes = sorted(payload_data.keys())
    data  = [payload_data[sz] for sz in sizes]
    unreliable = _unreliable_sizes(summaries)

    fig, ax = plt.subplots(figsize=(max(10, len(sizes) * 0.85), 5))
    bp = ax.boxplot(data, patch_artist=True,
                    medianprops=dict(color='tomato', linewidth=1.5))
    for i, (patch, sz) in enumerate(zip(bp['boxes'], sizes)):
        patch.set_facecolor('lightgrey' if sz in unreliable else 'lightsteelblue')

    ax.set_xticklabels([_size_label(sz) for sz in sizes],
                       rotation=45, ha='right', fontsize=8)
    ax.set_xlabel('Payload Size')
    ax.set_ylabel('TX Phase Duration (s)')
    ax.set_title(f'{module.upper()} / {strategy} -- TX Duration per Payload Size (n=30 runs)')
    if unreliable:
        ax.text(0.01, 0.98, 'Grey boxes: below SNR threshold',
                transform=ax.transAxes, fontsize=7, va='top', color='grey')
    fig.tight_layout()
    _save(fig, out_dir, f"{module}_{strategy}_run_duration_per_payload.png")


def plot_energy_per_payload(summaries, module, strategy, out_dir, noise: dict | None):
    """
    Mean +/- 1 SD energy (mJ) per payload size.
    Error bars show cross-run SD (measurement repeatability).
    A second lighter error bar shows mean measurement uncertainty (1 sigma)
    from the propagated instrument + noise floor uncertainty.
    """
    payload_data  = _collect(summaries, 'energy_mJ')
    sigma_data    = _collect(summaries, 'sigma_energy_mJ')
    unreliable    = _unreliable_sizes(summaries)
    sizes = sorted(payload_data.keys())
    x     = np.arange(len(sizes))

    means      = [np.mean(payload_data[sz])        for sz in sizes]
    stds       = [np.std(payload_data[sz], ddof=1) for sz in sizes]
    mean_sigma = [np.mean(sigma_data[sz])           for sz in sizes]  # avg measurement unc

    fig, ax = plt.subplots(figsize=(max(10, len(sizes) * 0.85), 5))
    _errorbar_plot(ax, sizes, payload_data,
                   ylabel='Energy (mJ)',
                   title=f'{module.upper()} / {strategy} -- Energy per Payload Size',
                   unreliable=unreliable)

    # Overlay mean measurement uncertainty as a narrower bar
    ax.errorbar(x, means, yerr=mean_sigma, fmt='none', color='darkorange',
                capsize=2, linewidth=0.8, alpha=0.8,
                label='Measurement uncertainty (1 sigma, mean)')
    ax.legend(fontsize=7)
    fig.tight_layout()
    _save(fig, out_dir, f"{module}_{strategy}_energy_per_payload.png")


def plot_efficiency_per_payload(summaries, module, strategy, out_dir):
    payload_data = _collect(summaries, 'efficiency_mJ_per_KB')
    unreliable   = _unreliable_sizes(summaries)
    sizes = sorted(payload_data.keys())

    fig, ax = plt.subplots(figsize=(max(10, len(sizes) * 0.85), 5))
    _errorbar_plot(ax, sizes, payload_data,
                   ylabel='Energy Efficiency (mJ / KB)  [log scale]',
                   title=f'{module.upper()} / {strategy} -- Energy Efficiency per Payload Size',
                   unreliable=unreliable)
    try:
        ax.set_yscale('log')
    except Exception:
        pass
    fig.tight_layout()
    _save(fig, out_dir, f"{module}_{strategy}_efficiency_per_payload.png")


def plot_current_trace_overlay(summaries, module, strategy, out_dir, noise: dict | None):
    n    = len(summaries)
    cmap = _cmap('tab20' if n > 10 else 'tab10', n)

    fig, ax = plt.subplots(figsize=(16, 5))
    for i, s in enumerate(summaries):
        meter = s['meter']
        ax.plot(meter['elapsed_s'], meter['current_mA'],
                linewidth=0.5, alpha=0.5, color=cmap(i), label=f'Run {s["run"]}')

    # Draw noise floor band if calibration available
    if noise:
        floor = noise['sigma_I_floor_mA']
        ax.axhspan(-floor * SNR_THRESHOLD, floor * SNR_THRESHOLD,
                   color='lightyellow', alpha=0.5, zorder=0,
                   label=f'Noise floor +/-{SNR_THRESHOLD}x sigma ({floor*SNR_THRESHOLD:.3f} mA)')

    ax.set_xlabel('Elapsed Time (s)')
    ax.set_ylabel('Current (mA)')
    line1 = f'{module.upper()} / {strategy} -- Current Draw: All {n} Runs Overlaid'
    line2 = '(each trace = full experiment: baseline + all payload sizes in sequence)'
    ax.set_title(line1 + chr(10) + line2)
    ax.legend(fontsize=6, ncol=5, loc='upper left')
    fig.tight_layout()
    _save(fig, out_dir, f"{module}_{strategy}_current_trace_overlay.png")


def plot_baseline_stability(summaries, module, strategy, out_dir):
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
    ax.set_title(f'{module.upper()} / {strategy} -- Baseline Current Stability across Runs')
    ax.set_xticks(runs)
    ax.set_xticklabels([str(r) for r in runs], fontsize=7, rotation=45)
    ax.legend()
    fig.tight_layout()
    _save(fig, out_dir, f"{module}_{strategy}_baseline_stability.png")


# ── CSV export ────────────────────────────────────────────────────────────────
def export_summary_csv(summaries, module, strategy, out_dir, noise: dict | None):
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
                'mean_current_mA':          round(ps['mean_current_mA'],        5),
                'energy_mJ':                round(ps['energy_mJ'],              6),
                'sigma_energy_mJ':          round(ps['sigma_energy_mJ'],        6),
                'efficiency_mJ_per_KB':     round(ps['efficiency_mJ_per_KB'],   6),
                'sigma_eff_mJ_per_KB':      round(ps['sigma_eff_mJ_per_KB'],    6),
                'snr':                      round(ps['snr'],                    3),
                'unreliable':               ps['unreliable'],
                'run_total_energy_mJ':      round(s['total_energy_mJ'],         4),
                'run_total_sigma_E_mJ':     round(s['total_sigma_E_mJ'],        4),
                'run_mean_active_power_mW': round(s['mean_power_active_mW'],    4),
                'baseline_mean_mA':         round(s['baseline_mean_mA'],        5),
                'baseline_std_mA':          round(s['baseline_std_mA'],         5),
                'noise_floor_mA':           round(noise['sigma_I_floor_mA'], 6) if noise else 'N/A',
                'offset_correction_mV':     round(noise['mu_offset_V']*1e3, 4) if noise else 'N/A',
            })
    df = pd.DataFrame(rows)
    fname = out_dir / f"{module}_{strategy}_summary.csv"
    df.to_csv(fname, index=False)
    print(f"  Saved: {fname.name}")


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    if not DATA_DIR.exists():
        print(f"[ERROR] Data directory not found: {DATA_DIR}")
        sys.exit(1)

    PLOTS_DIR.mkdir(parents=True, exist_ok=True)

    # ── Load noise floor calibration ──
    print("── Noise Floor Calibration ──")
    noise = load_noise_floor(DATA_DIR, PLOTS_DIR)
    print()

    # ── Discover experiment files ──
    csv_files = sorted(DATA_DIR.glob("*.csv"))
    csv_files = [f for f in csv_files if f.name != "shortcircuit.csv"]
    if not csv_files:
        print(f"[ERROR] No experiment CSV files found in {DATA_DIR}")
        sys.exit(1)

    groups, skipped = defaultdict(list), []
    for f in csv_files:
        result = parse_filename(f)
        if result is None:
            skipped.append(f.name); continue
        module, strategy, run_num = result
        groups[(module, strategy)].append({'path': f, 'run': run_num})

    if skipped:
        print(f"[WARN] Skipped {len(skipped)} unrecognised file(s):")
        for s in skipped: print(f"  {s}")

    print(f"Found {len(groups)} experiment group(s) in {DATA_DIR}:\n")
    all_ok = True

    for group_key, file_list in sorted(groups.items()):
        module, strategy = group_key
        file_list_sorted = sorted(file_list, key=lambda x: x['run'])
        print(f"━━ {module.upper()} / {strategy} ({len(file_list)} runs) ━━")

        parsed_list = [parse_csv(info['path'], noise) for info in file_list_sorted]
        all_ok = validate_group(group_key, file_list_sorted, parsed_list) and all_ok

        summaries = [s for s in
                     (summarise_run(p, i['run'], noise)
                      for p, i in zip(parsed_list, file_list_sorted))
                     if s is not None]

        if not summaries:
            print("  [WARN] No valid meter data -- skipping plots."); continue

        # Report unreliable sizes
        bad = _unreliable_sizes(summaries)
        if bad:
            labels = ', '.join(_size_label(sz) for sz in sorted(bad))
            print(f"  [WARN] Payload sizes below SNR threshold (flagged): {labels}")
        else:
            print(f"  [OK]   All payload sizes above SNR threshold")

        plot_mean_power_per_run(       summaries, module, strategy, PLOTS_DIR)
        plot_total_energy_per_run(     summaries, module, strategy, PLOTS_DIR)
        plot_run_duration_per_payload( summaries, module, strategy, PLOTS_DIR)
        plot_energy_per_payload(       summaries, module, strategy, PLOTS_DIR, noise)
        plot_efficiency_per_payload(   summaries, module, strategy, PLOTS_DIR)
        plot_current_trace_overlay(    summaries, module, strategy, PLOTS_DIR, noise)
        plot_baseline_stability(       summaries, module, strategy, PLOTS_DIR)
        export_summary_csv(            summaries, module, strategy, PLOTS_DIR, noise)
        print()

    print("✓ All validation checks passed." if all_ok
          else "⚠ Some validation checks FAILED -- see warnings above.")
    print(f"\nAll outputs saved to: {PLOTS_DIR}")


if __name__ == '__main__':
    main()