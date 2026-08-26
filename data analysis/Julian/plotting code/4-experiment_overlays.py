import os
import pandas as pd
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.lines import Line2D
from matplotlib.patches import Patch

# --- Path Configuration ---
BASE_PATH = '/Users/foml/Library/Mobile Documents/com~apple~CloudDocs/important/coding/MSP/year_3/Thesis work/BTR_results/data'
SAVE_PATH = '/Users/foml/Library/Mobile Documents/com~apple~CloudDocs/important/coding/MSP/year_3/Thesis work/BTR_results/plots/4-experiment_overlays'

if not os.path.exists(SAVE_PATH):
    os.makedirs(SAVE_PATH, exist_ok=True)

def find_col(columns, keyword):
    matches = [c for c in columns if keyword.lower() in c.lower().strip()]
    return matches[0] if matches else None

def plot_experiment_overlay_raw(experiment_path, file_list):
    lower_path = experiment_path.lower()
    if any(x in lower_path for x in ["esp32", "wifi"]):
        wireless_type, module_name = "Wi-Fi", "ESP32-C3"
    elif "lora" in lower_path:
        wireless_type, module_name = "LoRa", "RN2903"
    else:
        wireless_type, module_name = "BLE", "nRF52840"

    try:
        sample_file = file_list[0]
        with open(sample_file, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        
        results_start = next((i for i, line in enumerate(lines) if '# RESULTS' in line), -1)
        meter_start = next((i for i, line in enumerate(lines) if '# METER' in line), -1)
        
        if results_start == -1 or meter_start == -1: return

        # Metadata extraction
        sample_results = pd.read_csv(sample_file, skiprows=results_start + 1, nrows=(meter_start - results_start - 2))
        sample_results.columns = sample_results.columns.str.strip()
        p_col_header = find_col(sample_results.columns, 'phase')
        phase_names = sample_results[p_col_header].str.strip().str.upper().tolist()
        
        if wireless_type == "LoRa" and "all" in lower_path:
            tx_indices = [i for i, name in enumerate(phase_names) if 'TX_' in name]
            if tx_indices:
                last_tx_idx = tx_indices[-1]
                phase_names[last_tx_idx] = f"{phase_names[last_tx_idx]} + IDLE"

        num_phases = len(phase_names)
        fig, ax1 = plt.subplots(figsize=(24, 14))
        
        phase_data_store = {i: [] for i in range(num_phases)}
        durations_accumulator = np.zeros(num_phases)
        valid_runs = 0

        for file_path in file_list:
            try:
                df = pd.read_csv(file_path, skiprows=meter_start + 1, low_memory=False)
                df.columns = df.columns.str.strip()
                
                # --- USE PRE-CALCULATED CURRENT FROM PROCESSING STEP ---
                # Your big script saves 'Current' as the 5th column (Index 4)
                i_col = find_col(df.columns, 'current') or df.columns[4]
                p_col = find_col(df.columns, 'phase')
                
                # Convert Amperes (from file) to mA for plotting
                current_ma = pd.to_numeric(df[i_col], errors='coerce').fillna(0).values * 1000.0
                
                df['block'] = (df[p_col].astype(str).str.strip() != df[p_col].astype(str).str.strip().shift()).cumsum()
                
                for i in range(num_phases):
                    block_data = current_ma[df['block'] == (i + 1)]
                    if len(block_data) > 0:
                        # Resample to 500 points to ensure temporal alignment for CI calculation
                        resampled = np.interp(np.linspace(0, 1, 500), np.linspace(0, 1, len(block_data)), block_data)
                        phase_data_store[i].append(resampled)

                res_df = pd.read_csv(file_path, skiprows=results_start + 1, nrows=num_phases)
                res_df.columns = res_df.columns.str.strip()
                dur_col = find_col(res_df.columns, 'elapsed') or find_col(res_df.columns, 'ms')
                
                file_durs = res_df[dur_col].fillna(0).values
                for idx in range(min(len(file_durs), num_phases)):
                    durations_accumulator[idx] += file_durs[idx]

                valid_runs += 1
            except: continue

        if valid_runs == 0: return

        # --- Plotting ---
        all_ci_values = []
        COLORS = plt.get_cmap('Pastel1').colors
        
        for i in range(num_phases):
            ax1.axvspan(i, i + 1, color=COLORS[i % len(COLORS)], alpha=0.15, zorder=1)
            
            if phase_data_store[i]:
                arr = np.array(phase_data_store[i])
                mean_signal = np.mean(arr, axis=0) 
                sem_signal = np.std(arr, axis=0) / np.sqrt(valid_runs)
                ci_95 = 1.96 * sem_signal
                all_ci_values.extend(ci_95)

                x = np.linspace(0, 1, 500) + i
                ax1.fill_between(x, mean_signal - ci_95, mean_signal + ci_95, color='#cb4335', alpha=0.35, zorder=5)
                ax1.plot(x, mean_signal, color='#1a5276', lw=2.5, zorder=10)

        # --- Layout & Header ---
        plt.suptitle(f"{wireless_type.upper()} ({module_name}) Averaged Consumption Profile", 
                     fontsize=28, fontweight='bold', y=0.94)

        exp_name = os.path.basename(experiment_path).replace('_', ' ').title()
        ax1.set_title(f"Experiment: {exp_name} | Reading Pre-Processed Calibration Data", 
                      fontsize=16, color='grey', pad=60)

        avg_ci_val = np.mean(all_ci_values) if all_ci_values else 0
        legend_elements = [
            Line2D([0], [0], color='#1a5276', lw=2.5, label='Mean Current (mA)'),
            Patch(facecolor='#cb4335', alpha=0.35, label=f'95% Confidence Interval (Mean Width: {avg_ci_val:.2f} mA)')
        ]
        ax1.legend(handles=legend_elements, loc='lower center', 
                   bbox_to_anchor=(0.5, 1.12), ncol=2, fontsize=13, frameon=False)

        # Axis Formatting
        ax1.set_ylabel("Current Consumption (mA)", fontsize=16, fontweight='bold')
        ax1.set_xlabel("Normalized Phase Sequence", fontsize=16, fontweight='bold', labelpad=20)
        ax1.set_xticks(np.arange(num_phases) + 0.5)
        ax1.set_xticklabels(phase_names, rotation=45, ha='right', fontsize=10)
        ax1.set_xlim(0, num_phases)
        ax1.grid(True, axis='y', linestyle=':', alpha=0.4)

        # Secondary X-axis for duration
        ax2 = ax1.twiny()
        ax2.set_xlim(ax1.get_xlim())
        ax2.set_xticks(ax1.get_xticks())
        ax2.set_xticklabels([f"{(d/valid_runs)/1000:.3f}s" for d in durations_accumulator], 
                             rotation=45, ha='left', color='#c0392b', fontsize=10)
        ax2.set_xlabel("Mean Phase Duration (Seconds)", fontsize=13, color='#c0392b', labelpad=15)

        plt.subplots_adjust(top=0.75, bottom=0.18, left=0.08, right=0.92)
        
        file_base = f"current_overlay_{wireless_type.lower()}_{os.path.basename(experiment_path)}"
        plt.savefig(os.path.join(SAVE_PATH, f"{file_base}.png"), dpi=300, bbox_inches='tight')
        plt.savefig(os.path.join(SAVE_PATH, f"{file_base}.svg"), format='svg', bbox_inches='tight')
        plt.close()

    except Exception as e:
        print(f"  ❌ Error in {experiment_path}: {e}")

if __name__ == "__main__":
    def get_all_runs_per_experiment(base_path):
        experiments = {}
        for root, dirs, files in os.walk(base_path):
            csv_files = sorted([f for f in files if f.endswith('.csv')])
            if csv_files: 
                experiments[root] = [os.path.join(root, f) for f in csv_files]
        return experiments

    print("🚀 Generating overlays from pre-processed data...")
    groups = get_all_runs_per_experiment(BASE_PATH)
    for path, files in groups.items():
        print(f"Processing: {os.path.basename(path)}")
        plot_experiment_overlay_raw(path, files)
    print("\n✅ All overlays completed.")