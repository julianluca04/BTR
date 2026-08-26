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
BASE_PATH = r'/Users/foml/Library/Mobile Documents/com~apple~CloudDocs/important/coding/MSP/year_3/Thesis work/BTR_results/data'
SAVE_PATH = r'/Users/foml/Library/Mobile Documents/com~apple~CloudDocs/important/coding/MSP/year_3/Thesis work/BTR_results/plots/5-per_byte_wireless'
CALIB_PATH = r'/Users/foml/Library/Mobile Documents/com~apple~CloudDocs/important/coding/MSP/year_3/Thesis work/BTR_results/calibration_constants_summary.csv'

METHOD_DISPLAY_MAP = {'BYTE': 'Single Byte', 'CHUNK': 'Chunked Transfer', 'ALL': 'Full Payload'}
vibrant_colors = {"Single Byte": "#1f77b4", "Chunked Transfer": "#2ca02c", "Full Payload": "#d62728"}

if not os.path.exists(SAVE_PATH):
    os.makedirs(SAVE_PATH)

def load_calibration_values(path):
    """Loads mean values from the calibration summary."""
    try:
        df = pd.read_csv(path)
        v_supply = df.loc[df['Metric'] == 'Voltage', 'Mean'].values[0]
        r_shunt = df.loc[df['Metric'] == 'Resistance', 'Mean'].values[0]
        v_offset = df.loc[df['Metric'] == 'Offset', 'Mean'].values[0]
        print(f"✅ Calibration Loaded: Vs={v_supply:.4f}V, R={r_shunt:.4f}Ω, Offset={v_offset:.6f}V")
        return v_supply, r_shunt, v_offset
    except Exception as e:
        print(f"⚠️ Error loading calibration: {e}. Using defaults.")
        return 3.3, 0.1, 0.0

# Global constants
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
        
        # --- 1. APPLY PHYSICAL CALIBRATION & BURDEN VOLTAGE CORRECTION ---
        v_col = 'V_Shunt' if 'V_Shunt' in df.columns else df.columns[1]
        v_raw = pd.to_numeric(df[v_col], errors='coerce')
        v_raw_v = v_raw.apply(lambda x: x/1000.0 if abs(x) > 2.0 else x)
        
        # Current (A)
        current_a = (v_raw_v - V_OFFSET) / R_SHUNT
        # Instantaneous Voltage at Device (Correcting for Shunt Drop)
        v_at_device = VOLTAGE_SUPPLY - (v_raw_v - V_OFFSET)
        # Calibrated Power (mW)
        df['Power_mW'] = current_a * v_at_device * 1000
        
        # --- 2. TRAPEZOIDAL INTEGRATION (Consistent with Boot Logic) ---
        time_col = 'Timestamp' if 'Timestamp' in df.columns else df.columns[0]
        df['dt_obj'] = pd.to_datetime(df[time_col], format='ISO8601', errors='coerce')
        df['dt_s'] = df['dt_obj'].diff().dt.total_seconds().fillna(0)
        
        # (P_now + P_next) / 2 * dt
        p_curr = df['Power_mW']
        p_next = df['Power_mW'].shift(-1).fillna(p_curr)
        df['Sample_mJ'] = ((p_curr + p_next) / 2) * df['dt_s']
        
        # --- 3. UNIFIED AGGREGATION (TX + NEXT IDLE) ---
        df['block'] = df['Phase'].ne(df['Phase'].shift()).cumsum()
        grouped = df.groupby('block')
        blocks = [{'name': str(g['Phase'].iloc[0]).strip().upper(), 'energy': g['Sample_mJ'].sum()} for _, g in grouped]

        for i in range(len(blocks)):
            if 'TX_' in blocks[i]['name']:
                energy_sum = blocks[i]['energy']
                
                # Add the following Idle/Cooldown block
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
                            'mJ/B': energy_sum / payload
                        })
    except Exception: pass 
    return results

def save_standalone_plot(data_subset, protocol, payload, n_count, folder):
    fig, ax = plt.subplots(figsize=(10, 7))
    sns.set_theme(style="whitegrid")
    
    display_order = ['Single Byte', 'Chunked Transfer', 'Full Payload']
    
    for m in display_order:
        m_data = data_subset[data_subset['Method'] == m]
        if not m_data.empty:
            mu, sigma = m_data['mJ/B'].mean(), m_data['mJ/B'].std()
            stat_label = f"{m}\nμ={mu:.2e}, σ={sigma:.2e}"
            sns.histplot(data=m_data, x="mJ/B", color=vibrant_colors.get(m), 
                         label=stat_label, element="step", fill=True, stat="probability", 
                         kde=True, alpha=0.2,linewidth=2.5, ax=ax)
    
    ax.set_title(f"{protocol} Efficiency: {payload} Bytes (N={n_count})\nCalibrated Unified TX+Idle Energy (mJ/Byte)", 
                 fontweight='bold', fontsize=14, pad=20)
    ax.set_xlabel("Energy Efficiency (mJ/Byte)", fontsize=12, fontweight='medium', labelpad=10)
    ax.set_ylabel("Probability Distribution", fontsize=12, fontweight='medium', labelpad=10)
    ax.xaxis.set_major_formatter(ticker.ScalarFormatter(useMathText=True))
    ax.ticklabel_format(style='sci', axis='x', scilimits=(0,0))
    ax.legend(title="Method Statistics", loc='upper right', frameon=True, fontsize=9)
    plt.tight_layout()
    plt.savefig(os.path.join(folder, f"{protocol}_standalone_{payload}B.png"), dpi=400)
    plt.savefig(os.path.join(folder, f"{protocol}_standalone_{payload}B.svg"), format='svg')
    plt.close(fig)

def run_analysis():
    print(f"🚀 Scanning for files in: {BASE_PATH}")
    files = [os.path.join(r, f) for r, d, fs in os.walk(BASE_PATH) for f in fs if f.endswith('.csv')]
    if not files: return

    all_data = []
    with ProcessPoolExecutor() as executor:
        results = list(tqdm(executor.map(process_energy_events, files), total=len(files), desc="Processing Files"))
    for r in results: all_data.extend(r)
    df = pd.DataFrame(all_data)
    if df.empty: return

    for proto in df['Protocol'].unique():
        proto_df = df[df['Protocol'] == proto].sort_values('Payload')
        counts = proto_df.groupby('Payload').size().to_dict()
        INDIV_FOLDER = os.path.join(SAVE_PATH, f"{proto}_standalone_assets")
        os.makedirs(INDIV_FOLDER, exist_ok=True)
        
        sns.set_theme(style="whitegrid")
        g = sns.FacetGrid(proto_df, col="Payload", col_wrap=4, hue="Method", 
                         hue_order=['Single Byte', 'Chunked Transfer', 'Full Payload'], 
                         sharex=False, sharey=False, height=4.5, aspect=1.2, 
                         palette=vibrant_colors, despine=False)
        
        g.map_dataframe(sns.histplot, x="mJ/B", element="step", fill=True, 
                        stat="probability", common_norm=False, kde=True, alpha=0.2)
        
        for ax in g.axes.flat:
            ax.xaxis.set_major_formatter(ticker.ScalarFormatter(useMathText=True))
            ax.ticklabel_format(style='sci', axis='x', scilimits=(0,0))
            title_text = ax.get_title()
            match = re.search(r'Payload = (\d+)', title_text)
            if match:
                p_val = int(match.group(1))
                ax.set_title(f"Payload: {p_val}B\n(N={counts.get(p_val, 0)})", fontweight='bold')

        g.add_legend(title="Data Transfer Method", loc='upper center', bbox_to_anchor=(0.5, 0.92), ncol=3, frameon=True)
        plt.subplots_adjust(top=0.82, hspace=0.6)
        g.fig.suptitle(f"{proto} Efficiency: Burden Voltage Corrected\nVs={VOLTAGE_SUPPLY:.4f}V | R={R_SHUNT:.4f}Ω", 
                       fontsize=20, fontweight='bold', y=0.98)
        
        g.savefig(os.path.join(SAVE_PATH, f"master_grid_{proto}.png"), dpi=300, bbox_inches='tight')
        g.savefig(os.path.join(SAVE_PATH, f"master_grid_{proto}.svg"), format='svg', bbox_inches='tight')
        plt.close()

        for payload in proto_df['Payload'].unique():
            subset = proto_df[payload == proto_df['Payload']]
            save_standalone_plot(subset, proto, payload, len(subset), INDIV_FOLDER)

    print(f"✅ Success. Calibrated per-byte plots saved to {SAVE_PATH}")

if __name__ == "__main__": 
    run_analysis()