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

# --- Configuration ---
BASE_PATH = '/Users/foml/coding/MSP/year_3/Thesis work/BTR_results/data'
SAVE_PATH = '/Users/foml/coding/MSP/year_3/Thesis work/BTR_results/plots/5.5-per_byte_method'
CALIB_PATH = '/Users/foml/coding/MSP/year_3/Thesis work/BTR_results/calibration_constants_summary.csv'

METHOD_DISPLAY_MAP = {'BYTE': 'Single Byte', 'CHUNK': 'Chunked Transfer', 'ALL': 'Full Payload'}
PROTO_ORDER = ["WIFI", "BLE", "LORA"]
PROTO_COLORS = {"WIFI": "#1f77b4", "BLE": "#2ca02c", "LORA": "#d62728"}

if not os.path.exists(SAVE_PATH):
    os.makedirs(SAVE_PATH)

def load_calibration_values(path):
    """Loads calibrated mean values for Vs, R, and Offset from CSV."""
    try:
        df = pd.read_csv(path)
        v_supply = df.loc[df['Metric'] == 'Voltage', 'Mean'].values[0]
        r_shunt = df.loc[df['Metric'] == 'Resistance', 'Mean'].values[0]
        v_offset = df.loc[df['Metric'] == 'Offset', 'Mean'].values[0]
        print(f"✅ Calibration Loaded: Vs={v_supply:.4f}V, R={r_shunt:.4f}Ω, Offset={v_offset:.6f}V")
        return v_supply, r_shunt, v_offset
    except Exception as e:
        print(f"⚠️ Warning: Could not load calibration file. using defaults. Error: {e}")
        return 3.3, 0.1, 0.0

# Load constants globally
VOLTAGE_SUPPLY, R_SHUNT, V_OFFSET = load_calibration_values(CALIB_PATH)

def process_energy_events(file_path):
    results = []
    p_lower = file_path.lower()
    protocol = "WIFI" if "wifi" in p_lower else ("LORA" if "lora" in p_lower else "BLE")
    method_key = "BYTE" if "byte" in p_lower else ("CHUNK" if "chunk" in p_lower else "ALL")
    
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        parts = content.split("# METER")
        if len(parts) < 2: return []
        
        df = pd.read_csv(StringIO(parts[1].strip()))
        df.columns = df.columns.str.strip()
        
        # 1. APPLY CALIBRATION & BURDEN VOLTAGE CORRECTION
        v_col = 'V_Shunt' if 'V_Shunt' in df.columns else df.columns[1]
        v_raw = pd.to_numeric(df[v_col], errors='coerce')
        v_raw_v = v_raw.apply(lambda x: x/1000.0 if abs(x) > 2.0 else x)
        
        # Calculate Current (A)
        current_a = (v_raw_v - V_OFFSET) / R_SHUNT
        # Device Voltage (Correcting for drop across Shunt)
        v_at_device = VOLTAGE_SUPPLY - (v_raw_v - V_OFFSET)
        # Power in mW
        df['Power_mW'] = current_a * v_at_device * 1000
        
        # 2. TRAPEZOIDAL INTEGRATION
        time_col = 'Timestamp' if 'Timestamp' in df.columns else df.columns[0]
        df['dt_obj'] = pd.to_datetime(df[time_col], format='ISO8601', errors='coerce')
        df['dt_s'] = df['dt_obj'].diff().dt.total_seconds().fillna(0)
        
        # Consistent integration: (P1 + P2) / 2 * dt
        p_curr = df['Power_mW']
        p_next = df['Power_mW'].shift(-1).fillna(p_curr)
        df['Sample_mJ'] = ((p_curr + p_next) / 2) * df['dt_s']
        
        # 3. UNIFIED AGGREGATION (TX + NEXT IDLE)
        df['block'] = df['Phase'].ne(df['Phase'].shift()).cumsum()
        grouped = df.groupby('block')
        blocks = [{'name': str(g['Phase'].iloc[0]).strip().upper(), 'energy': g['Sample_mJ'].sum()} for _, g in grouped]

        for i in range(len(blocks)):
            if 'TX_' in blocks[i]['name']:
                energy_sum = blocks[i]['energy']
                
                # Add the following Idle/Cooldown phase for a complete energy footprint
                if i + 1 < len(blocks):
                    energy_sum += blocks[i+1]['energy']
                
                match = re.search(r'TX_(\d+)', blocks[i]['name'])
                if match:
                    payload = int(match.group(1))
                    if payload > 0:
                        results.append({
                            'Protocol': protocol, 
                            'Method': METHOD_DISPLAY_MAP.get(method_key, method_key), 
                            'Payload': payload, 
                            'mJ_B': energy_sum / payload
                        })
    except Exception: pass 
    return results

def save_standalone_plot(data_subset, method_name, payload, n_count, folder):
    fig, ax = plt.subplots(figsize=(10, 7))
    sns.set_theme(style="whitegrid")
    
    for proto in PROTO_ORDER:
        p_data = data_subset[data_subset['Protocol'] == proto]
        if not p_data.empty:
            mu, sigma = p_data['mJ_B'].mean(), p_data['mJ_B'].std()
            stat_label = f"{proto}\nμ={mu:.2e}, σ={sigma:.2e}"
            sns.histplot(data=p_data, x="mJ_B", color=PROTO_COLORS[proto], label=stat_label,
                         element="step", fill=True, stat="probability", kde=True, alpha=0.2, linewidth=2.5, ax=ax)
    
    ax.set_title(f"Method: {method_name} | {payload} Bytes (N={n_count})\n"
                 f"Burden Voltage Corrected | Unified TX+Idle Energy", fontweight='bold', fontsize=14, pad=20)
    ax.set_xlabel("Energy Efficiency (mJ/Byte)", fontsize=12, fontweight='medium', labelpad=10)
    ax.set_ylabel("Probability Distribution", fontsize=12, fontweight='medium', labelpad=10)
    ax.xaxis.set_major_formatter(ticker.ScalarFormatter(useMathText=True))
    ax.ticklabel_format(style='sci', axis='x', scilimits=(0,0))
    ax.legend(title="Wireless Protocol Stats", loc='upper right', frameon=True, fontsize=9)
    
    plt.tight_layout()
    os.makedirs(folder, exist_ok=True)
    base_fn = f"comp_{method_name.replace(' ', '_')}_{payload}B"
    fig.savefig(os.path.join(folder, f"png-{base_fn}.png"), dpi=400, bbox_inches='tight')
    fig.savefig(os.path.join(folder, f"svg-{base_fn}.svg"), format='svg', bbox_inches='tight')
    plt.close(fig)

def run_analysis():
    print(f"🚀 Starting analysis in: {BASE_PATH}")
    files = [os.path.join(r, f) for r, d, fs in os.walk(BASE_PATH) for f in fs if f.endswith('.csv')]
    if not files:
        print("❌ No CSV files found!")
        return

    all_data = []
    with ProcessPoolExecutor() as executor:
        results = list(tqdm(executor.map(process_energy_events, files), total=len(files), desc="Processing Files"))
    for r in results: all_data.extend(r)
    df = pd.DataFrame(all_data)
    
    if df.empty:
        print("❌ Dataframe is empty after processing.")
        return

    for method in df['Method'].unique():
        method_df = df[df['Method'] == method].sort_values('Payload')
        counts = method_df.groupby('Payload').size().to_dict()
        INDIV_FOLDER = os.path.join(SAVE_PATH, f"standalone_{method.replace(' ', '_')}")
        os.makedirs(INDIV_FOLDER, exist_ok=True)

        sns.set_theme(style="whitegrid")
        g = sns.FacetGrid(method_df, col="Payload", col_wrap=4, hue="Protocol", 
                         hue_order=PROTO_ORDER, sharex=False, sharey=False, 
                         height=4.5, aspect=1.2, palette=PROTO_COLORS, despine=False)

        g.map_dataframe(
            sns.histplot,
            x="mJ_B",
            element="step",
            fill=True,
            stat="probability",
            alpha=0.25,
            kde=True,
            linewidth=2
        )
        
        for ax in g.axes.flat:
            ax.xaxis.set_major_formatter(ticker.ScalarFormatter(useMathText=True))
            ax.ticklabel_format(style='sci', axis='x', scilimits=(0,0))
            
            title_text = ax.get_title()
            match = re.search(r'Payload = (\d+)', title_text)
            if match:
                p_val = int(match.group(1))
                ax.set_title(f"Payload: {p_val}B\n(N={counts.get(p_val, 0)})", fontweight='bold')

        # Legend for Master Grid
        g.add_legend(title="Wireless Protocol", loc='upper center', bbox_to_anchor=(0.5, 0.92), ncol=3, frameon=True)
        plt.subplots_adjust(top=0.82, hspace=0.6)
        
        g.fig.suptitle(f"Method: {method} - Protocol Comparison\n"
                       f"Unified TX+Idle | Vs={VOLTAGE_SUPPLY:.4f}V | Burden-Corrected", 
                       fontsize=20, fontweight='bold', y=0.98)
        
        os.makedirs(SAVE_PATH, exist_ok=True)
        master_png = os.path.join(SAVE_PATH, f"png-master_comparison_{method.replace(' ', '_')}.png")
        master_svg = os.path.join(SAVE_PATH, f"svg-master_comparison_{method.replace(' ', '_')}.svg")

        g.fig.savefig(master_png, dpi=300, bbox_inches='tight')
        g.fig.savefig(master_svg, format='svg', bbox_inches='tight')
        print(f"✅ Saved Master Grid: {method}")

        plt.close(g.fig)

        for payload in method_df['Payload'].unique():
            subset = method_df[method_df['Payload'] == payload]
            save_standalone_plot(subset, method, payload, len(subset), INDIV_FOLDER)

    print(f"✅ Full analysis complete. All plots saved to {SAVE_PATH}")

if __name__ == "__main__": 
    run_analysis()