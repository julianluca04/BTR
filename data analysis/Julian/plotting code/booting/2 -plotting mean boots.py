import os
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.patches import Patch
from io import StringIO

# --- Path Configuration ---
# Parent path updated to iCloud location
BTR_RESULTS_PATH = '/Users/foml/Library/Mobile Documents/com~apple~CloudDocs/important/coding/MSP/year_3/Thesis work/BTR_results'
BOOT_DATA_PATH = os.path.join(BTR_RESULTS_PATH, 'boot data')
BASE_SAVE_PATH = os.path.join(BTR_RESULTS_PATH, 'plots', 'boots')
SAVE_PATH = os.path.join(BASE_SAVE_PATH, '2 - experiment overlays boots')
CALIB_PATH = os.path.join(BTR_RESULTS_PATH, 'calibration_constants_summary.csv')

if not os.path.exists(SAVE_PATH):
    os.makedirs(SAVE_PATH)

# --- Configuration ---
THRESHOLD_PCT = 0.05   
LOOKAHEAD_SAMPLES = 5  
PRE_BOOT_OFFSET_MS = 500     
PLATEAU_WINDOW_SAMPLES = 40  
STABILITY_THRESH = 0.00025   
MAX_SEARCH_TIME_MS = 6000    
PROTOCOLS = ["wifi", "ble", "lora"]

def load_calibration_values(path):
    try:
        df = pd.read_csv(path)
        v_supply = df.loc[df['Metric'] == 'Voltage', 'Mean'].values[0]
        r_shunt = df.loc[df['Metric'] == 'Resistance', 'Mean'].values[0]
        v_offset = df.loc[df['Metric'] == 'Offset', 'Mean'].values[0]
        return v_supply, r_shunt, v_offset
    except Exception:
        return 3.3, 0.1, 0.0

def find_col(columns, keyword):
    matches = [c for c in columns if keyword.lower() in c.lower().strip()]
    return matches[0] if matches else None

def plot_boot_overlay(protocol, file_list, calib_vals):
    module_mapping = {"wifi": "ESP32-C3", "lora": "RN2903", "ble": "nRF52840"}
    module_name = module_mapping.get(protocol, protocol.upper())
    Vs, R, Offset = calib_vals

    common_time_grid = np.linspace(0, 15000, 10000) 
    interpolated_signals = []
    boot_end_times = []
    energies_mj = []
    valid_runs = 0

    for file_path in file_list:
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()
            
            met_idx = next((i for i, l in enumerate(lines) if "# METER" in l), -1)
            if met_idx == -1: continue

            df = pd.read_csv(StringIO("".join(lines[met_idx + 1:])))
            df.columns = df.columns.str.strip()
            v_col = find_col(df.columns, 'shunt')
            
            v_raw = pd.to_numeric(df[v_col], errors='coerce')
            v_raw_v = v_raw.apply(lambda x: x/1000.0 if abs(x) > 2.0 else x)
            
            # --- Calculation Logic: mA and Power ---
            # Corrected Current in mA: (V_shunt - Offset) / R * 1000
            df['current_ma'] = ((v_raw_v - Offset) / R) * 1000.0
            
            # Instantaneous Voltage reaching the device (V)
            # Device receives Supply minus the drop across the shunt
            v_device = Vs - (v_raw_v - Offset)
            
            # Power (mW) = Amps * Volts * 1000
            i_a = (v_raw_v - Offset) / R
            df['Power_mW'] = i_a * v_device * 1000
            
            # Trigger detection based on voltage (consistent with hardware rise)
            baseline_floor_v = v_raw_v.min()
            rise_threshold = baseline_floor_v + (abs(baseline_floor_v) * THRESHOLD_PCT)
            if baseline_floor_v <= 0: rise_threshold = 0.0002 

            potential_hits = df.index[v_raw_v > rise_threshold].tolist()
            trigger_idx = None
            for idx in potential_hits:
                if idx + LOOKAHEAD_SAMPLES < len(df):
                    if v_raw_v.iloc[idx : idx + LOOKAHEAD_SAMPLES].min() > rise_threshold:
                        trigger_idx = idx
                        break
            if trigger_idx is None: continue

            df['Timestamp_Start'] = pd.to_datetime(df['Timestamp_Start'], format='ISO8601')
            actual_rise_time = df.loc[trigger_idx, 'Timestamp_Start']
            origin_time = actual_rise_time - pd.Timedelta(milliseconds=PRE_BOOT_OFFSET_MS)
            df['rel_ms'] = (df['Timestamp_Start'] - origin_time).dt.total_seconds() * 1000

            # Plateau search logic
            search_df = df[df['rel_ms'] <= MAX_SEARCH_TIME_MS].copy()
            boot_end_ms = search_df['rel_ms'].max()
            last_valid_idx = search_df.index[-1]

            for i in range(last_valid_idx, trigger_idx + PLATEAU_WINDOW_SAMPLES, -2):
                window = v_raw_v.iloc[i - PLATEAU_WINDOW_SAMPLES : i]
                if window.std() > STABILITY_THRESH:
                    boot_end_ms = df.loc[i, 'rel_ms']
                    break
            
            # --- Energy Integration ---
            boot_mask = (df['rel_ms'] >= 0) & (df['rel_ms'] <= boot_end_ms)
            boot_df = df[boot_mask].copy()
            if not boot_df.empty:
                dt_s = boot_df['rel_ms'].diff().fillna(0) / 1000.0
                p_curr = boot_df['Power_mW']
                p_next = boot_df['Power_mW'].shift(-1).fillna(p_curr)
                energy_mj = np.sum(((p_curr + p_next) / 2) * dt_s)
                energies_mj.append(energy_mj)

            boot_end_times.append(boot_end_ms)
            # Interpolate current instead of voltage for the overlay signal
            interpolated_signals.append(np.interp(common_time_grid, df['rel_ms'], df['current_ma']))
            valid_runs += 1

        except Exception:
            continue

    if valid_runs < 2: return

    signals_array = np.array(interpolated_signals)
    mean_signal = np.mean(signals_array, axis=0)
    ci_95 = 1.96 * (np.std(signals_array, axis=0) / np.sqrt(valid_runs))
    
    avg_boot_end = np.mean(boot_end_times)
    energy_mean = np.mean(energies_mj)
    energy_std = np.std(energies_mj)

    # --- Plotting ---
    fig, ax1 = plt.subplots(figsize=(14, 8))
    
    ax1.fill_between(common_time_grid, mean_signal - ci_95, mean_signal + ci_95, color='#e74c3c', alpha=0.15)
    ax1.plot(common_time_grid, mean_signal, color='#1a5276', lw=2.0)
    ax1.axvline(x=avg_boot_end, color='#27ae60', linestyle='--', lw=2.0)

    plt.suptitle(f"{protocol.upper()} ({module_name}) Boot Energy Analysis", fontsize=24, fontweight='bold')
    # Main title (dominant line)
    ax1.set_title(
        f"Total Boot Energy (X=0 to End): {energy_mean:.4f} ± {energy_std:.4f} mJ | Duration: {avg_boot_end:.1f} ms",
        fontsize=20, color='#333333', pad=25
    )
    # Secondary title line (smaller, above)
    ax1.text(
        0.5, 1.02,
        f"Mean of {valid_runs} Runs | 95% Confidence Interval Variability",
        transform=ax1.transAxes,
        ha='center',
        fontsize=16,
        color='#333333'
    )
    
    # Label updated to mA
    ax1.set_ylabel("Current Consumption (mA)", fontsize=28, fontweight='bold')
    ax1.set_xlabel("Time from Origin [ms]", fontsize=28, fontweight='bold')
    ax1.tick_params(axis='both', labelsize=24)
    ax1.set_xlim(0, avg_boot_end + 1000)
    ax1.grid(True, linestyle='--', alpha=0.4)
    
    legend_elements = [
        Line2D([0], [0], color='#1a5276', lw=2, label='Mean Current (mA)'),
        Patch(facecolor='#e74c3c', alpha=0.15, label='95% CI (Variability)'),
        Line2D([0], [0], color='#27ae60', linestyle='--', lw=2, label=f'Boot End ({avg_boot_end:.1f}ms)')
    ]
    ax1.legend(handles=legend_elements, loc='lower right', frameon=True, fontsize=28)

    plt.tight_layout(rect=[0, 0.03, 1, 0.95]) 

    file_base = f"boot_energy_{protocol}"
    plt.savefig(os.path.join(SAVE_PATH, f"png - {file_base}.png"), dpi=300)
    plt.savefig(os.path.join(SAVE_PATH, f"svg - {file_base}.svg"))
    plt.close()
    print(f"  ✅ Saved {protocol}: {energy_mean:.4f} mJ (Corrected for Burden Voltage)")

if __name__ == "__main__":
    calib_vals = load_calibration_values(CALIB_PATH)
    for proto in PROTOCOLS:
        proto_dir = os.path.join(BOOT_DATA_PATH, proto)
        if os.path.isdir(proto_dir):
            files = [os.path.join(proto_dir, f) for f in os.listdir(proto_dir) if f.endswith('.csv')]
            if files: plot_boot_overlay(proto, files, calib_vals)