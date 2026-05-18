import os
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
from concurrent.futures import ProcessPoolExecutor
from tqdm import tqdm
from io import StringIO
import re
import matplotlib.ticker as ticker
from mpl_toolkits.axes_grid1.inset_locator import inset_axes, mark_inset
from scipy import stats

# --- Configuration ---
BASE_PATH = r'/Users/foml/Library/Mobile Documents/com~apple~CloudDocs/important/coding/MSP/year_3/Thesis work/BTR_results/data'
ROOT_SAVE_PATH = r'/Users/foml/Library/Mobile Documents/com~apple~CloudDocs/important/coding/MSP/year_3/Thesis work/BTR_results/plots/6-total_energy_trends'
CALIB_PATH = r'/Users/foml/Library/Mobile Documents/com~apple~CloudDocs/important/coding/MSP/year_3/Thesis work/BTR_results/calibration_constants_summary.csv'




METHOD_DISPLAY_MAP = {'BYTE': 'Single Byte', 'CHUNK': 'Chunked Transfer', 'ALL': 'Full Payload'}
PROTO_COLORS = {"WIFI": "#1f77b4", "BLE": "#2ca02c", "LORA": "#d62728"}
METHOD_COLORS = {"Single Byte": "#1f77b4", "Chunked Transfer": "#2ca02c", "Full Payload": "#d62728"}

def load_calibration_values(path):
    if not os.path.exists(path):
        print(f"!! WARNING: Calibration file not found at {path}. Using defaults.")
        return 3.3, 0.1, 0.0
    df = pd.read_csv(path)
    v_supply = df.loc[df['Metric'] == 'Voltage', 'Mean'].values[0]
    r_shunt = df.loc[df['Metric'] == 'Resistance', 'Mean'].values[0]
    v_offset = df.loc[df['Metric'] == 'Offset', 'Mean'].values[0]
    return v_supply, r_shunt, v_offset

VOLTAGE_SUPPLY, R_SHUNT, V_OFFSET = load_calibration_values(CALIB_PATH)

def process_energy_events(file_path):
    results = []
    p_lower = file_path.lower()
    protocol = "WIFI" if "wifi" in p_lower else ("LORA" if "lora" in p_lower else "BLE")
    method_key = "BYTE" if "byte" in p_lower else ("CHUNK" if "chunk" in p_lower else "ALL")
    
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        if "# METER" not in content:
            return []
            
        meter_section = content.split("# METER")[-1].strip()
        df = pd.read_csv(StringIO(meter_section), sep=None, engine='python')
        df.columns = [c.strip() for c in df.columns]
        
        v_col = 'V_Shunt' if 'V_Shunt' in df.columns else df.columns[2]
        v_raw = pd.to_numeric(df[v_col], errors='coerce')
        v_raw_v = v_raw.apply(lambda x: x/1000.0 if abs(x) > 2.0 else x)
        
        # --- PHYSICAL CALIBRATION & BURDEN VOLTAGE CORRECTION ---
        current_a = (v_raw_v - V_OFFSET) / R_SHUNT
        v_at_device = VOLTAGE_SUPPLY - (v_raw_v - V_OFFSET)
        power_mw = current_a * v_at_device * 1000
        
        time_col = 'Timestamp_Start' if 'Timestamp_Start' in df.columns else df.columns[0]
        df['dt_obj'] = pd.to_datetime(df[time_col], format='ISO8601', errors='coerce')
        
        # --- SAMPLE-BY-SAMPLE INTEGRATION ---
        df['dt_s'] = df['dt_obj'].diff().dt.total_seconds().fillna(0)
        p_next = power_mw.shift(-1).fillna(power_mw)
        df['Sample_mJ'] = ((power_mw + p_next) / 2) * df['dt_s']
        
        df['block'] = df['Phase'].ne(df['Phase'].shift()).cumsum()
        
        blocks = []
        for _, g in df.groupby('block'):
            phase_name = str(g['Phase'].iloc[0]).strip().upper()
            energy_mj = g['Sample_mJ'].sum()
            blocks.append({'name': phase_name, 'energy': energy_mj})

        for i in range(len(blocks)):
            if 'TX_' in blocks[i]['name']:
                match = re.search(r'TX_(\d+)', blocks[i]['name'])
                if match:
                    payload = int(match.group(1))
                    tx_only = blocks[i]['energy']
                    unified = tx_only
                    if i + 1 < len(blocks) and 'IDLE' in blocks[i+1]['name']:
                        unified += blocks[i+1]['energy']
                    
                    common = {'Protocol': protocol, 'Method': METHOD_DISPLAY_MAP.get(method_key, method_key), 'Payload': payload}
                    results.append({**common, 'Energy_mJ': unified, 'Calc_Type': 'Unified'})
                    results.append({**common, 'Energy_mJ': tx_only, 'Calc_Type': 'Isolated'})
    except Exception: pass
    return results

def should_trigger_zoom(subset, hue_col):
    first_8 = sorted(subset['Payload'].unique())[:8]
    if len(first_8) < 2 or len(subset[hue_col].unique()) < 2: return False
    data_8 = subset[subset['Payload'].isin(first_8)]
    pivot = data_8.groupby(['Payload', hue_col])['Energy_mJ'].mean().unstack()
    LOG_THRESHOLD = 0.25 
    for payload in pivot.index:
        vals = pivot.loc[payload].dropna().values
        if len(vals) < 2: continue
        log_vals = np.log10(vals)
        log_vals.sort()
        if np.min(np.diff(log_vals)) < LOG_THRESHOLD: return True
    return False

def format_thesis_ax(ax, title, is_inset=False, use_log=False):
    if use_log:
        ax.set_yscale('log')
        ax.yaxis.set_major_formatter(ticker.LogFormatterSciNotation())
    else:
        ax.set_yscale('linear')
        ax.yaxis.set_major_formatter(ticker.ScalarFormatter())
    ax.set_xscale('log', base=2)
    ax.grid(True, which="both", axis="y", linestyle="--", linewidth=0.5, alpha=0.4)
    ax.xaxis.set_major_formatter(ticker.ScalarFormatter())
    if is_inset:
        ax.set_ylabel(""); ax.set_xlabel(""); ax.tick_params(axis='both', labelsize=7)
    else:
        ax.set_title(title, fontweight='bold', fontsize=12, pad=55) 
        ax.set_ylabel("Energy Consumption (mJ)", fontweight='bold')
        ax.set_xlabel("Payload Size (Bytes)", fontweight='bold')

def run_analysis():
    print(f"Scanning for files in: {BASE_PATH}")
    files = [os.path.join(r, f) for r, d, fs in os.walk(BASE_PATH) for f in fs if f.endswith('.csv')]
    if not files: return

    all_data = []
    with ProcessPoolExecutor() as executor:
        results = list(tqdm(executor.map(process_energy_events, files), total=len(files), desc="Processing"))
    for r in results: all_data.extend(r)
    df = pd.DataFrame(all_data)
    if df.empty:
        print("!! ERROR: No data found.")
        return

    for calc in ['Unified', 'Isolated']:
        current_save_path = os.path.join(ROOT_SAVE_PATH, "unified_tx_idle" if calc == 'Unified' else "isolated_tx")
        os.makedirs(current_save_path, exist_ok=True)
        calc_df = df[df['Calc_Type'] == calc]
        plot_groups = [('Method', 'Protocol', PROTO_COLORS), ('Protocol', 'Method', METHOD_COLORS)]
        
        for group_col, hue_col, palette in plot_groups:
            for val in calc_df[group_col].unique():
                fig, ax = plt.subplots(figsize=(11, 7.5), constrained_layout=True) 
                subset = calc_df[calc_df[group_col] == val].sort_values('Payload')
                unique_hues = subset[hue_col].unique()
                
                for hue_val in unique_hues:
                    line_data = subset[subset[hue_col] == hue_val]
                    stats_df = line_data.groupby('Payload')['Energy_mJ'].agg(['mean', 'std', 'count']).dropna()
                    
                    def get_ci(row):
                        if row['count'] < 2: return 0
                        t_val = stats.t.ppf(0.975, df=row['count']-1)
                        return t_val * (row['std'] / np.sqrt(row['count']))

                    stats_df['ci_margin'] = stats_df.apply(get_ci, axis=1)
                    rel_err = (stats_df['ci_margin'] / stats_df['mean'].replace(0, np.nan)) * 100
                    color = palette.get(hue_val, "#333333")
                    
                    lbl = f"{hue_val} (Err: ±{rel_err.min():.2f}% to ±{rel_err.max():.2f}%)"
                    
                    ax.plot(stats_df.index, stats_df['mean'], label=lbl, color=color, linewidth=1.8, marker='o', markersize=4)
                    ax.fill_between(stats_df.index, stats_df['mean'] - stats_df['ci_margin'], stats_df['mean'] + stats_df['ci_margin'], color=color, alpha=0.15)

                format_thesis_ax(ax, f"{group_col}: {val}\n{calc} Model (95% CI)", use_log=False)
                
                ax.legend(loc='upper center', bbox_to_anchor=(0.5, 1.08), ncol=len(unique_hues), 
                          fontsize=7.5, frameon=False, handlelength=1.2, columnspacing=1.0)

                if should_trigger_zoom(subset, hue_col):
                    ax_ins = inset_axes(ax, width="38%", height="30%", loc='upper center', borderpad=5) 
                    first_8 = sorted(subset['Payload'].unique())[:8]
                    for hue_val in unique_hues:
                        z_data = subset[(subset[hue_col] == hue_val) & (subset['Payload'].isin(first_8))]
                        z_stats = z_data.groupby('Payload')['Energy_mJ'].agg(['mean', 'std', 'count'])
                        z_err = 1.96 * (z_stats['std'] / np.sqrt(z_stats['count']))
                        ax_ins.plot(z_stats.index, z_stats['mean'], color=palette.get(hue_val), marker='o', markersize=3)
                        ax_ins.fill_between(z_stats.index, z_stats['mean'] - z_err, z_stats['mean'] + z_err, color=palette.get(hue_val), alpha=0.1)
                    format_thesis_ax(ax_ins, "", is_inset=True)
                    ax_ins.set_xticks(first_8)
                    mark_inset(ax, ax_ins, loc1=3, loc2=4, fc="none", ec="0.5", linestyle="--", alpha=0.3)
                    # Force fixed y-axis for LORA depending on calc type
                    if set(subset['Protocol'].unique()) == {'LORA'}:
                        if calc == 'Unified':
                            ax_ins.set_ylim(150, 300)
                        else:
                            ax_ins.set_ylim(0, 200)

                base_fn = os.path.join(current_save_path, f"plot_{val.replace(' ', '_')}")
                plt.savefig(f"{base_fn}.png", dpi=250, bbox_inches='tight')
                plt.savefig(f"{base_fn}.svg", bbox_inches='tight')
                plt.close(fig)

    print("Success. Calibrated trend plots generated.")

if __name__ == "__main__":
    run_analysis()