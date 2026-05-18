import os
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
import numpy as np
import scipy.stats as stats
from scipy.stats import skew, gaussian_kde
import matplotlib.ticker as ticker
from matplotlib.lines import Line2D

# --- Configuration ---
BASE_DATA_PATH = r'/Users/foml/Library/Mobile Documents/com~apple~CloudDocs/important/coding/MSP/year_3/Thesis work/BTR_results/data'
SUMMARY_FILE_PATH = r'/Users/foml/Library/Mobile Documents/com~apple~CloudDocs/important/coding/MSP/year_3/Thesis work/BTR_results/summary_per_phase.csv'
OUTPUT_DIR = r'/Users/foml/Library/Mobile Documents/com~apple~CloudDocs/important/coding/MSP/year_3/Thesis work/BTR_results/plots/3-plotting_skewness_comparison'
os.makedirs(OUTPUT_DIR, exist_ok=True)

EXP_COLORS = {"chunk": "#e67e22", "byte": "#1abc9c", "all": "#34495e"}
DISPLAY_MAP = {'chunk': 'Chunked Transfer', 'byte': 'Single Byte', 'all': 'Full Payload'}

def calculate_95_ci(data):
    if len(data) < 2: return 0.0
    std_err = stats.sem(data)
    return std_err * stats.t.ppf((1 + 0.95) / 2, len(data) - 1)

def get_kde_peak(data):
    if len(data) < 2: return 0.0, 0.0
    try:
        kde = gaussian_kde(data)
        x_range = np.linspace(min(data), max(data), 2000)
        y_values = kde(x_range)
        idx = np.argmax(y_values)
        return x_range[idx], y_values[idx]
    except:
        return 0.0, 0.0

def get_raw_samples_by_phase_logic(protocol, experiment, mode):
    all_points = []
    p_folder = "BLE" if protocol.lower() == "ble" else protocol.lower()
    folder = os.path.join(BASE_DATA_PATH, p_folder, experiment)
    
    if not os.path.exists(folder):
        return np.array([])

    for fname in os.listdir(folder):
        if not fname.endswith(".csv"): continue
        path = os.path.join(folder, fname)
        
        try:
            with open(path, 'r', encoding='utf-8') as f:
                lines = f.readlines()
            
            m_idx = next((i for i, l in enumerate(lines) if "# METER" in l), -1)
            if m_idx == -1: continue

            df_raw = pd.read_csv(path, skiprows=m_idx + 1)
            df_raw.columns = df_raw.columns.str.strip()
            
            df_raw['Current_mA'] = df_raw['Current'].astype(float) * 1000.0
            df_raw['Phase'] = df_raw['Phase'].astype(str).str.strip().str.lower()
            
            if mode == "Integrated":
                mask = df_raw['Phase'].str.contains('tx|idle|payload|baseline', na=False)
            else:
                mask = (df_raw['Phase'].str.contains('tx', na=False)) & (~df_raw['Phase'].str.contains('idle', na=False))
            
            all_points.extend(df_raw.loc[mask, 'Current_mA'].tolist())
            
        except Exception:
            continue

    return np.array(all_points)

def run_final_thesis_analysis():
    if not os.path.exists(SUMMARY_FILE_PATH):
        print(f"❌ Error: {SUMMARY_FILE_PATH} not found.")
        return

    stats_results = []
    protocols = ['wifi', 'ble', 'lora']
    experiments = ['chunk', 'byte', 'all']

    for protocol in protocols:
        print(f"📊 Processing {protocol.upper()}...")
        plt.style.use('seaborn-v0_8-whitegrid')
        fig, ax = plt.subplots(figsize=(14, 8))
        
        peak_proxies = []
        peak_labels = []
        max_y_val = 0

        for exp in experiments:
            for mode in ["Integrated", "Pure TX"]:
                target_data = get_raw_samples_by_phase_logic(protocol, exp, mode)
                
                if len(target_data) < 50: continue

                # Calculate metrics
                mu = target_data.mean()
                med = np.median(target_data)
                sk = skew(target_data)
                ci = calculate_95_ci(target_data)
                data_range = target_data.max() - target_data.min()
                
                # Plotting
                color = EXP_COLORS[exp]
                if mode == "Integrated":
                    sns.kdeplot(target_data, ax=ax, color=color, linewidth=2.5, linestyle='-', 
                                fill=True, alpha=0.1, label=f"{('full payload' if exp == 'all' else DISPLAY_MAP[exp])} Unified ($Sk={sk:.2f}$)")
                else:
                    sns.kdeplot(target_data, ax=ax, color=color, linewidth=2, linestyle='--', 
                                fill=False, alpha=1.0, label=f"{('full payload' if exp == 'all' else DISPLAY_MAP[exp])} Isolated ($Sk={sk:.2f}$)")
                
                px, py = get_kde_peak(target_data)
                max_y_val = max(max_y_val, py)
                
                marker = 's' if mode == "Integrated" else 'o'
                peak_proxies.append(Line2D([0], [0], color=color, marker=marker, linestyle='None', markersize=6))
                peak_labels.append(f"{'Unified' if mode == 'Integrated' else 'Isolated'} {('full' if exp == 'all' else exp.capitalize())}: {py:.4f} at {px:.1f} mA")
                
                # Append to table results including Range
                stats_results.append([
                    protocol.upper(), exp.capitalize(), mode, len(target_data),
                    f"{mu:.2f}", f"±{ci:.3f}", f"{med:.2f}", f"{sk:.2f}", f"{data_range:.1f}"
                ])

        plt.suptitle(f"{protocol.upper()} Protocol: Energy Distribution Analysis", fontsize=22, fontweight='bold', y=0.96)
        ax.set_xlabel("Current Consumption (mA)", fontsize=14, fontweight='bold')
        ax.set_ylabel("Probability Density", fontsize=14, fontweight='bold')

        leg1 = ax.legend(title="Methodology", loc='upper right', fontsize=12, ncol=2)
        leg2 = ax.legend(peak_proxies, peak_labels, loc='upper left', title="Peak Density (KDE)",
                         frameon=True, labelcolor='linecolor', prop={'size': 12, 'weight': 'semibold'})
        ax.add_artist(leg1)

        ax.set_ylim(0, max_y_val * 1.5)
        sns.despine()
        plt.tight_layout(rect=[0, 0, 1, 0.94])
        base_path = os.path.join(OUTPUT_DIR, f"impact_analysis_{protocol.lower()}")
        plt.savefig(base_path + ".png", dpi=400, bbox_inches='tight')
        plt.savefig(base_path + ".svg", format='svg', bbox_inches='tight')
        plt.close()

    # Updated Typst Table Output with Range Column
    table_path = os.path.join(OUTPUT_DIR, 'statistical_analysis_typst.txt')
    with open(table_path, 'w') as f:
        f.write("#table(\n  columns: (1fr, 1fr, 1.2fr, 1.2fr, 1fr, 1.2fr, 1fr, 1fr, 1.4fr),\n")
        f.write("  [*Protocol*], [*Experiment*], [*Type*], [*N*], [*Mean*], [*95% CI*], [*Median*], [*Skew*], [*Range ($Delta$ mA)*],\n")
        for row in stats_results:
            f.write("  " + ", ".join([f"[{val}]" for val in row]) + ",\n")
        f.write(")\n")

    print(f"✅ Analysis complete. Files saved to: {OUTPUT_DIR}")

if __name__ == "__main__":
    run_final_thesis_analysis()