import os
import pandas as pd
import matplotlib.pyplot as plt
import numpy as np

# --- Path Configuration ---
BASE_PATH = '/Users/foml/Library/Mobile Documents/com~apple~CloudDocs/important/coding/MSP/year_3/Thesis work/BTR_results/data'
SAVE_PATH = '/Users/foml/Library/Mobile Documents/com~apple~CloudDocs/important/coding/MSP/year_3/Thesis work/BTR_results/plots/1.5-experiment_overlays'

if not os.path.exists(SAVE_PATH):
    os.makedirs(SAVE_PATH, exist_ok=True)

def get_all_runs_per_experiment(base_path):
    experiments = {}
    for root, dirs, files in os.walk(base_path):
        csv_files = sorted([f for f in files if f.endswith('.csv')])
        if csv_files:
            experiments[root] = [os.path.join(root, f) for f in csv_files]
    return experiments

def plot_experiment_overlay_raw(experiment_path, file_list):
    try:
        sample_file = file_list[0]
        with open(sample_file, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        
        results_start = next((i for i, line in enumerate(lines) if '# RESULTS' in line), -1)
        meter_start = next((i for i, line in enumerate(lines) if '# METER' in line), -1)
        
        if results_start == -1 or meter_start == -1:
            return

        sample_results = pd.read_csv(sample_file, skiprows=results_start + 1, 
                                     nrows=(meter_start - results_start - 2))
        sample_results.columns = sample_results.columns.str.strip()
        phase_names = sample_results['Phase'].str.strip().str.upper().tolist()
        num_phases = len(phase_names)

        # Large figure size to allow for sprawling labels
        fig, ax1 = plt.subplots(figsize=(26, 14))
        RAINBOW_COLORS = plt.colormaps.get_cmap('tab20').colors
        
        for i in range(num_phases):
            ax1.axvspan(i, i + 1, color=RAINBOW_COLORS[i % len(RAINBOW_COLORS)], alpha=0.12, zorder=1)

        durations_accumulator = np.zeros(num_phases)
        
        # Tracking for Peak/Floor points
        peak_val, peak_coords = float('-inf'), (0, 0)
        floor_val, floor_coords = float('inf'), (0, 0)
        
        total_data_points = 0 

        for file_path in file_list:
            with open(file_path, 'r', encoding='utf-8') as f:
                f_lines = f.readlines()
            
            m_start = next((i for i, line in enumerate(f_lines) if '# METER' in line), -1)
            r_start = next((i for i, line in enumerate(f_lines) if '# RESULTS' in line), -1)
            
            df = pd.read_csv(file_path, skiprows=m_start + 1)
            df.columns = df.columns.str.strip()
            total_data_points += len(df)

            current_col = 'Current' if 'Current' in df.columns else df.columns[4]
            current_raw = pd.to_numeric(df[current_col], errors='coerce')
            current_ma = current_raw * 1000.0

            phase_col = 'Phase' if 'Phase' in df.columns else 'phase'
            df['block'] = (df[phase_col] != df[phase_col].shift()).cumsum()
            
            for i in range(num_phases):
                block_data = df[df['block'] == (i + 1)]
                if block_data.empty: continue
                n = len(block_data)
                x_vals = np.linspace(0, 1, n) + i
                y_vals = current_ma.iloc[block_data.index].values
                
                ax1.plot(x_vals, y_vals, color='black', lw=0.3, alpha=0.08, zorder=5)

                # Check for global peak/floor in this block
                local_max_idx = np.argmax(y_vals)
                if y_vals[local_max_idx] > peak_val:
                    peak_val = y_vals[local_max_idx]
                    peak_coords = (x_vals[local_max_idx], peak_val)
                
                local_min_idx = np.argmin(y_vals)
                if y_vals[local_min_idx] < floor_val:
                    floor_val = y_vals[local_min_idx]
                    floor_coords = (x_vals[local_min_idx], floor_val)

            res_df = pd.read_csv(file_path, skiprows=r_start + 1, nrows=(m_start - r_start - 2))
            res_df.columns = res_df.columns.str.strip()
            for idx, row in res_df.iterrows():
                if idx < num_phases:
                    durations_accumulator[idx] += row['Elapsed_ms']

        # --- Dynamic Y-Axis with generous padding ---
        y_range = peak_val - floor_val
        padding = y_range * 0.25 if y_range > 0 else 10
        ax1.set_ylim(floor_val - padding, peak_val + padding)

        # --- Horizontal Lines ---
        ax1.axhline(peak_val, color='blue', ls='--', lw=1.5, alpha=0.5, zorder=10)
        ax1.axhline(floor_val, color='green', ls='--', lw=1.5, alpha=0.5, zorder=10)

        # --- Point Markers for Extreme Values ---
        ax1.scatter(*peak_coords, color='blue', s=180, marker='^', zorder=20, edgecolors='white')
        ax1.annotate(f" {peak_val:.2f} mA", xy=peak_coords, xytext=(8, 8), 
                     textcoords='offset points', color='blue', fontweight='bold', fontsize=13)

        ax1.scatter(*floor_coords, color='green', s=180, marker='v', zorder=20, edgecolors='white')
        ax1.annotate(f" {floor_val:.2f} mA", xy=floor_coords, xytext=(8, -18), 
                     textcoords='offset points', color='green', fontweight='bold', fontsize=13)

        # Right-side boundary labels
        ax1.text(num_phases * 1.01, peak_val, f' Peak: {peak_val:.2f} mA', va='center', ha='left', color='blue', fontweight='bold')
        ax1.text(num_phases * 1.01, floor_val, f' Floor: {floor_val:.2f} mA', va='center', ha='left', color='green', fontweight='bold')

        ax1.yaxis.set_major_locator(plt.MaxNLocator(nbins=14))

        # Metadata extraction
        path_parts = experiment_path.split(os.sep)
        method_map = {"all": "Full Payload", "byte": "Byte-By-Byte", "chunk": "Chunk-By-Chunk"}
        raw_method = path_parts[-1].lower()
        method_name = method_map.get(raw_method, raw_method)
        path_lower = experiment_path.lower()
        is_wifi = "esp32" in path_lower or "wifi" in path_lower
        is_lora = "lora" in path_lower or "rn2903" in path_lower

        wireless_type, module_name = ("Wi-Fi", "ESP32-C3") if is_wifi else (("LoRa", "RN2903") if is_lora else ("BLE", "nRF52840"))

        full_title_string = (f"{wireless_type} ({module_name}) Current Profile Overlay - Method: {method_name}\n"
                             f"N={len(file_list)} Runs | Total Samples: {total_data_points:,}")
        
        # y=0.97 pushes title higher to avoid overlapping with top axis
        plt.suptitle(full_title_string, fontsize=26, fontweight='bold', y=0.97, va='top')
        
        ax1.set_xlim(0, num_phases)
        ax1.set_ylabel("Current Consumption (mA)", fontsize=18, fontweight='bold', labelpad=20)
        ax1.set_xlabel("Phase Sequence", fontsize=18, fontweight='bold', labelpad=25)
        ax1.set_xticks(np.arange(num_phases) + 0.5)

        display_labels = phase_names.copy()
        if is_lora and raw_method == "all" and len(display_labels) > 0:
            if not str(display_labels[-1]).strip().lower().endswith("idle"):
                display_labels[-1] = f"{display_labels[-1]} + IDLE"
        
        ax1.set_xticklabels(display_labels, rotation=45, ha='right', fontsize=11, fontweight='bold')
        ax1.grid(True, axis='y', linestyle='--', alpha=0.3)

        # Secondary Axis (Average Durations)
        avg_durations = [f"{ (d/len(file_list))/1000 :.3f}s" for d in durations_accumulator]
        ax2 = ax1.twiny()
        ax2.set_xlim(ax1.get_xlim())
        ax2.set_xticks(ax1.get_xticks())
        ax2.set_xticklabels(avg_durations, rotation=45, ha='left', fontsize=11, fontweight='bold', color='#c0392b')
        ax2.set_xlabel("Average Hardware-Measured Duration (Seconds)", 
                       fontsize=16, fontweight='bold', color='#c0392b', labelpad=35)

        # subplots_adjust is configured for "open" space
        plt.subplots_adjust(top=0.78, bottom=0.18, right=0.85, left=0.08) 
        
        save_name = f"current_overlay_{wireless_type.lower()}_{raw_method}"
        plt.savefig(os.path.join(SAVE_PATH, f"{save_name}.png"), dpi=300)
        plt.savefig(os.path.join(SAVE_PATH, f"{save_name}.svg"), format='svg', bbox_inches='tight')
        
        plt.close()
        print(f"✅ Exported: {save_name}")

    except Exception as e:
        print(f"❌ Error processing {experiment_path}: {e}")

if __name__ == "__main__":
    groups = get_all_runs_per_experiment(BASE_PATH)
    for path, files in groups.items():
        plot_experiment_overlay_raw(path, files)