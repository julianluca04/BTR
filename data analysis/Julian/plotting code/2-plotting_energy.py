import os
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
import numpy as np
import re
from matplotlib.lines import Line2D
from io import StringIO

# --- Configuration ---
BASE_PATH = '/Users/foml/coding/MSP/year_3/Thesis work/BTR_results/data'
OUTPUT_DIR = '/Users/foml/coding/MSP/year_3/Thesis work/BTR_results/plots/2-plotting_energy'
CALIB_PATH = '/Users/foml/coding/MSP/year_3/Thesis work/BTR_results/calibration_constants_summary.csv'
PROTOCOLS = ["wifi", "BLE", "lora"]
EXPERIMENTS = ["chunk", "byte", "all"]

os.makedirs(OUTPUT_DIR, exist_ok=True)

PROTO_COLORS = {"wifi": "#9bbcd9", "BLE": "#a8d4a8", "lora": "#f2b0bd"}
EXP_MAP = {'chunk': 'Chunked Transfer', 'byte': 'Single Byte', 'all': 'Full Payload'}
EXP_ORDER = ['Chunked Transfer', 'Single Byte', 'Full Payload']

def load_calibration_values(path):
    try:
        df = pd.read_csv(path)
        # We don't need V_supply for mA, but we need R and Offset
        r_shunt = df.loc[df['Metric'] == 'Resistance', 'Mean'].values[0]
        v_offset = df.loc[df['Metric'] == 'Offset', 'Mean'].values[0]
        return r_shunt, v_offset
    except Exception:
        return 0.1, 0.0 # Fallback defaults

R_SHUNT, V_OFFSET = load_calibration_values(CALIB_PATH)

def extract_and_group_raw(base_path):
    all_data_frames = []
    
    for proto in PROTOCOLS:
        for exp in EXPERIMENTS:
            folder = os.path.join(base_path, proto, exp)
            if not os.path.isdir(folder): continue
            
            print(f"📂 Processing {proto.upper()} - {exp.upper()}...")
            csv_files = [f for f in os.listdir(folder) if f.endswith('.csv')]
            
            local_max = 0
            temp_data_list = []
            
            for file in csv_files:
                path = os.path.join(folder, file)
                try:
                    meter_idx = -1
                    with open(path, 'r', encoding='utf-8') as f:
                        for i, line in enumerate(f):
                            if "# METER" in line:
                                meter_idx = i; break
                    if meter_idx == -1: continue
                    
                    df = pd.read_csv(path, skiprows=meter_idx + 1)
                    df.columns = df.columns.str.strip()
                    phs_col = 'Phase' if 'Phase' in df.columns else df.columns[2]
                    v_col = 'V_Shunt' if 'V_Shunt' in df.columns else df.columns[3]
                    
                    df[phs_col] = df[phs_col].str.strip().str.upper()
                    df = df[df[phs_col] != 'BASELINE'].copy()
                    
                    # --- PHYSICAL CALIBRATION LOGIC ---
                    v_raw = pd.to_numeric(df[v_col], errors='coerce')
                    v_raw_v = v_raw.apply(lambda x: x/1000.0 if abs(x) > 2.0 else x)
                    
                    # Calculate Current (mA) with Burden/Offset Correction
                    # Current (mA) = ((V_measured - Offset) / R_shunt) * 1000
                    df['Current_mA'] = ((v_raw_v - V_OFFSET) / R_SHUNT) * 1000.0
                    
                    vals = [int(n) for n in re.findall(r'TX_(\d+)', str(df[phs_col].values))]
                    if vals: local_max = max(local_max, max(vals))
                    
                    temp_data_list.append(df[[phs_col, 'Current_mA']])
                except: continue

            if not temp_data_list: continue
            
            combined_raw = pd.concat(temp_data_list)
            raw_phs = combined_raw[phs_col].values
            currents = combined_raw['Current_mA'].values
            
            final_labeled_rows = []
            current_tx_val = None
            
            for i in range(len(raw_phs)):
                phase_str = str(raw_phs[i])
                tx_match = re.search(r'TX_(\d+)', phase_str)
                
                if tx_match:
                    current_tx_val = int(tx_match.group(1))
                    is_lora_220 = (proto.lower() == "lora" and current_tx_val == 220)
                    
                    if current_tx_val == local_max and not is_lora_220:
                        label = f"TX_{current_tx_val} ({current_tx_val} B payload)"
                    else:
                        label = f"TX_{current_tx_val}+IDLE ({current_tx_val} B payload)"
                        
                    final_labeled_rows.append({'Current_mA': currents[i], 'Phase': label})
                
                elif phase_str == "IDLE" and current_tx_val is not None:
                    is_lora_220 = (proto.lower() == "lora" and current_tx_val == 220)
                    if current_tx_val == local_max and not is_lora_220:
                        label = f"TX_{current_tx_val} ({current_tx_val} B payload)"
                    else:
                        label = f"TX_{current_tx_val}+IDLE ({current_tx_val} B payload)"
                    final_labeled_rows.append({'Current_mA': currents[i], 'Phase': label})
                else:
                    current_tx_val = None

            if final_labeled_rows:
                res_df = pd.DataFrame(final_labeled_rows)
                res_df['Protocol'], res_df['Experiment'] = proto, EXP_MAP[exp]
                all_data_frames.append(res_df)
                    
    return pd.concat(all_data_frames, ignore_index=True)

# Note: plot_thesis_raincloud function remains the same as your original 
# but will now use the calibrated Current_mA values.
def plot_thesis_raincloud(df):
    for proto in PROTOCOLS:
        proto_data = df[df['Protocol'] == proto].copy()
        if proto_data.empty: continue
        
        fig, ax = plt.subplots(figsize=(24, 13)) 
        
        def get_val(s):
            m = re.search(r'TX_(\d+)', s)
            return int(m.group(1)) if m else 0
        
        all_phs = sorted(proto_data['Phase'].unique(), key=get_val)
        palette = sns.color_palette("husl", len(all_phs))
        color_map = {p: palette[i] for i, p in enumerate(all_phs)}

        sns.violinplot(x='Experiment', y='Current_mA', data=proto_data, order=EXP_ORDER,
                       color=PROTO_COLORS[proto], inner=None, linewidth=1.5, alpha=0.6, ax=ax, zorder=1)

        sns.stripplot(x='Experiment', y='Current_mA', hue='Phase', 
                      data=proto_data.sample(frac=min(1.0, 45000/len(proto_data))), 
                      order=EXP_ORDER, palette=color_map, hue_order=all_phs,
                      size=3.0, alpha=0.4, jitter=0.3, dodge=True, legend=False, ax=ax, zorder=2)

        plt.suptitle(f"{proto.upper()} Protocol: Power Consumption Profile", 
                     fontsize=36, fontweight='bold', y=0.97)
        
        ax.set_title("Violin density represents total distribution | Dotted strips represent validated TX+IDLE cycles\nPeak payload TX values reflect standalone transmission only", 
                     fontsize=18, fontstyle='italic', color='#333333', pad=30, linespacing=1.6)

        ax.set_ylabel("Current Consumption (mA)", fontsize=26, fontweight='bold', labelpad=25)
        ax.set_xlabel("Experiment Methodology", fontsize=26, fontweight='bold', labelpad=25)

        new_labels = []
        for exp in EXP_ORDER:
            sub = proto_data[proto_data['Experiment'] == exp]
            if sub.empty: new_labels.append(exp); continue
            m_tx = max([get_val(p) for p in sub['Phase'].unique()])
            new_labels.append(f"{exp}\n(n={len(sub):,})\nPeak Payload: {m_tx} B")

        ax.set_xticklabels(new_labels, fontsize=16, fontweight='medium')

        means = proto_data.groupby('Experiment', observed=True)['Current_mA'].mean().reindex(EXP_ORDER)
        for i, m in enumerate(means):
            ax.scatter(i, m, marker='D', color='white', edgecolor='black', s=250, zorder=10)

        legend_elements = [Line2D([0], [0], marker='o', color='w', label=p, 
                                  markerfacecolor=color_map[p], markersize=14) for p in all_phs]
        legend_elements.append(Line2D([0], [0], marker='D', color='w', label='Global Mean', 
                                      markerfacecolor='white', markeredgecolor='black', markersize=16))
        
        leg = ax.legend(handles=legend_elements, title="Transmission Phases (Payload size)", 
                        bbox_to_anchor=(1.01, 1), loc='upper left', frameon=True, 
                        fontsize=14, title_fontsize=18)
        leg.get_frame().set_edgecolor('#DDDDDD')

        plt.grid(True, axis='y', linestyle='--', alpha=0.3)
        sns.despine(trim=True)
        plt.tight_layout(rect=[0, 0, 0.80, 0.95]) 
        
        base_name = os.path.join(OUTPUT_DIR, f"thesis_final_{proto.lower()}")
        plt.savefig(f"{base_name}.png", dpi=400)
        plt.savefig(f"{base_name}.svg", format='svg')
        plt.close()

if __name__ == "__main__":
    data = extract_and_group_raw(BASE_PATH)
    if not data.empty:
        plot_thesis_raincloud(data)