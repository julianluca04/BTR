import os
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
from tqdm import tqdm
from io import StringIO
import re
import matplotlib.ticker as ticker
from mpl_toolkits.axes_grid1.inset_locator import inset_axes, mark_inset

# --- Configuration ---

BASE_PATH = r'/Users/foml/Library/Mobile Documents/com~apple~CloudDocs/important/coding/MSP/year_3/Thesis work/BTR_results/data'
SAVE_PATH = r'/Users/foml/Library/Mobile Documents/com~apple~CloudDocs/important/coding/MSP/year_3/Thesis work/BTR_results/plots/7-master_comparison'
CALIB_PATH = r'/Users/foml/Library/Mobile Documents/com~apple~CloudDocs/important/coding/MSP/year_3/Thesis work/BTR_results/calibration_constants_summary.csv'



os.makedirs(SAVE_PATH, exist_ok=True)
print(f"Saving plots to: {SAVE_PATH}")

# Fixed color mapping
PROTOCOL_COLORS = {
    'WIFI': 'orange',
    'BLE': 'blue',
    'LORA': 'red'
}

METHOD_COLORS = {
    'CHUNK': 'green',
    'BYTE': 'blue',
    'ALL': 'red'
}

def load_calibration_values(path):
    try:
        df = pd.read_csv(path)
        return (df.loc[df['Metric'] == 'Voltage', 'Mean'].values[0],
                df.loc[df['Metric'] == 'Resistance', 'Mean'].values[0],
                df.loc[df['Metric'] == 'Offset', 'Mean'].values[0])
    except:
        return 5.0204, 1.1346, -0.000002

VOLTAGE_SUPPLY, R_SHUNT, V_OFFSET = load_calibration_values(CALIB_PATH)

def process_file(file_path):
    results = []
    p_lower = file_path.lower()
    protocol = "WIFI" if "wifi" in p_lower else ("LORA" if "lora" in p_lower else "BLE")
    method = "BYTE" if "byte" in p_lower else ("CHUNK" if "chunk" in p_lower else "ALL")
    
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        parts = content.split("# METER")
        if len(parts) < 2: return []
        
        df_raw = pd.read_csv(StringIO(parts[1].strip()))
        df_raw.columns = [c.strip() for c in df_raw.columns]
        
        time_col = next((c for c in df_raw.columns if 'time' in c.lower()), 'Timestamp')
        v_col = 'V_Shunt' if 'V_Shunt' in df_raw.columns else df_raw.columns[1]
        phase_col = 'Phase' if 'Phase' in df_raw.columns else 'Phase'

        v_shunt_v = pd.to_numeric(df_raw[v_col], errors='coerce').apply(lambda x: x/1000.0 if abs(x) > 2.0 else x)
        current_a = (v_shunt_v - V_OFFSET) / R_SHUNT
        # P = I * (Vs - Vshunt)
        power_mw = current_a * (VOLTAGE_SUPPLY - (v_shunt_v - V_OFFSET)) * 1000

        df_raw[time_col] = pd.to_datetime(df_raw[time_col], errors='coerce')
        time_sec = (df_raw[time_col] - df_raw[time_col].iloc[0]).dt.total_seconds().values
        
        dt = np.diff(time_sec)
        p_avg = (power_mw.values[:-1] + power_mw.values[1:]) / 2.0
        df_raw['Sample_mJ'] = np.append(p_avg * dt, 0)
        
        df_raw['block'] = df_raw[phase_col].ne(df_raw[phase_col].shift()).cumsum()
        grouped = df_raw.groupby('block')
        blocks = [{'name': str(g[phase_col].iloc[0]).strip().upper(), 'energy': g['Sample_mJ'].sum()} for _, g in grouped]

        for i in range(len(blocks)):
            if 'TX_' in blocks[i]['name']:
                energy_total = blocks[i]['energy']
                # Correctly include the "tail" energy of the radio shutting down
                if i + 1 < len(blocks) and 'TX_' not in blocks[i+1]['name']:
                    energy_total += blocks[i+1]['energy']
                
                match = re.search(r'TX_(\d+)', blocks[i]['name'])
                if match:
                    payload = int(match.group(1))
                    if payload > 0:
                        results.append({'Protocol': protocol, 'Method': method, 'Payload': payload, 'mJ_B': energy_total / payload})
    except: pass
    return results

def apply_plot_formatting(fig, ax, plot_df, hue_val, title):
    ax.set_xscale('log', base=2)
    ax.set_yscale('log')
    ax.xaxis.set_major_formatter(ticker.ScalarFormatter())
    
    # Grid and Sub-lines
    ax.yaxis.set_minor_locator(ticker.LogLocator(base=10.0, subs=np.arange(2, 10) * 0.1, numticks=12))
    ax.grid(True, which='both', linestyle='--', alpha=0.3)
    
    # Legend as Suptitle
    handles, labels = ax.get_legend_handles_labels()
    if handles:
        ax.get_legend().remove()
        fig.legend(handles, labels, loc='upper center', bbox_to_anchor=(0.5, 0.92), 
                   ncol=3, frameon=True, fontsize=9)

    # Inset Window (Top Right)
    ax_ins = inset_axes(ax, width="35%", height="35%", loc='upper right', borderpad=3)
    zoom_df = plot_df[plot_df['Payload'] <= 16]
    if not zoom_df.empty:
        palette = METHOD_COLORS if hue_val == "Method" else PROTOCOL_COLORS
        sns.lineplot(
            data=zoom_df,
            x="Payload",
            y="mJ_B",
            hue=hue_val,
            palette=palette,
            legend=False,
            ax=ax_ins,
            marker='o',
            markersize=5
        )
        ax_ins.set_xscale('log', base=2)
        ax_ins.set_yscale('log')
        # Same axis titles as parent
        ax_ins.set_xlabel("Payload Size (Bytes)", fontsize=7)
        ax_ins.set_ylabel("mJ/Byte", fontsize=7)
        ax_ins.tick_params(labelsize=6)
        mark_inset(ax, ax_ins, loc1=2, loc2=4, fc="none", ec="0.5", ls="--", alpha=0.4)

    ax.set_title(title, fontsize=14, fontweight='bold', pad=60)
    ax.set_xlabel("Payload Size (Bytes)", fontweight='bold')
    ax.set_ylabel("Energy Efficiency (mJ per Byte)", fontweight='bold')

def run():
    files = [os.path.join(r, f) for r, d, fs in os.walk(BASE_PATH) for f in fs if f.endswith('.csv')]
    data = []
    for f in tqdm(files, desc="Parsing"): data.extend(process_file(f))
    df = pd.DataFrame(data)
    if df.empty: return

    sns.set_theme(style="whitegrid", font="serif")

    # Group 1: Methods per Protocol
    for p in df['Protocol'].unique():
        pdf = df[df['Protocol'] == p].sort_values('Payload')
        fig, ax = plt.subplots(figsize=(12, 9))
        sns.lineplot(
            data=pdf,
            x="Payload",
            y="mJ_B",
            hue="Method",
            palette=METHOD_COLORS,
            marker='o',
            markersize=8,
            ax=ax,
            errorbar=('ci', 95)
        )
        apply_plot_formatting(fig, ax, pdf, "Method", f"{p}: Efficiency Comparison by Transfer Method")

        png_path = os.path.join(SAVE_PATH, f"proto_{p.lower()}.png")
        svg_path = os.path.join(SAVE_PATH, f"proto_{p.lower()}.svg")

        plt.savefig(png_path, dpi=300, bbox_inches='tight')
        plt.savefig(svg_path, bbox_inches='tight')
        print(f"Saved: {png_path}")
        print(f"Saved: {svg_path}")
        plt.close()

    # Group 2: Protocols per Method
    for m in df['Method'].unique():
        mdf = df[df['Method'] == m].sort_values('Payload')
        fig, ax = plt.subplots(figsize=(12, 9))
        sns.lineplot(
            data=mdf,
            x="Payload",
            y="mJ_B",
            hue="Protocol",
            palette=PROTOCOL_COLORS,
            marker='o',
            markersize=8,
            ax=ax,
            errorbar=('ci', 95)
        )
        apply_plot_formatting(fig, ax, mdf, "Protocol", f"{m} Method: Protocol Efficiency Comparison")

        png_path = os.path.join(SAVE_PATH, f"meth_{m.lower()}.png")
        svg_path = os.path.join(SAVE_PATH, f"meth_{m.lower()}.svg")

        plt.savefig(png_path, dpi=300, bbox_inches='tight')
        plt.savefig(svg_path, bbox_inches='tight')
        print(f"Saved: {png_path}")
        print(f"Saved: {svg_path}")
        plt.close()

if __name__ == "__main__":
    run()