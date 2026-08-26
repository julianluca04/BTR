import pandas as pd
import matplotlib.pyplot as plt
import matplotlib as mpl
import os
import numpy as np

# --- Path Configuration ---
BASE_PATH = '/Users/foml/coding/MSP/year_3/Thesis work/BTR_results/data'
SAVE_PATH = '/Users/foml/coding/MSP/year_3/Thesis work/BTR_results/plots/1 -initial plotting data phases'

if not os.path.exists(SAVE_PATH):
    os.makedirs(SAVE_PATH)

def find_one_run_per_type(base_path):
    representative_runs = []
    for root, dirs, files in os.walk(base_path):
        csv_files = sorted([f for f in files if f.endswith('.csv')])
        if csv_files:
            representative_runs.append(os.path.join(root, csv_files[0]))
    return representative_runs

def plot_and_save_final(file_path):
    try:
        # --- 1. Load Data & Parse Results Section ---
        with open(file_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        
        results_start = next((i for i, line in enumerate(lines) if '# RESULTS' in line), -1)
        meter_start = next((i for i, line in enumerate(lines) if '# METER' in line), -1)
        
        if meter_start == -1 or results_start == -1:
            return

        results_df = pd.read_csv(file_path, skiprows=results_start + 1, 
                                 nrows=(meter_start - results_start - 2))
        results_df.columns = results_df.columns.str.strip()
        
        df = pd.read_csv(file_path, skiprows=meter_start + 1)
        df.columns = df.columns.str.strip()
        
        # 2. Metadata & Mapping
        path_parts = file_path.split(os.sep)
        method_map = {"all": "Full Payload", "byte": "Byte-By-Byte Payload", "chunk": "Chunk-By-Chunk payload"}
        raw_method = path_parts[-2].lower()
        method_type_name = method_map.get(raw_method, raw_method)
        
        file_path_lower = file_path.lower()

        is_wifi = "esp32" in file_path_lower or "wifi" in file_path_lower
        is_lora = "lora" in file_path_lower or "sx127" in file_path_lower

        if is_wifi:
            wireless_type = "Wi-Fi"
            module_name = "ESP32-C3"
        elif is_lora:
            wireless_type = "LoRa"
            module_name = "RN2903"
        else:
            wireless_type = "BLE"
            module_name = "nRF52840"
        
        file_name_only = os.path.basename(file_path)
        v_col = 'V_Shunt' if 'V_Shunt' in df.columns else df.columns[1]
        phase_col = 'Phase' if 'Phase' in df.columns else 'phase'

        # Normalize phase column to avoid split issues
        df[phase_col] = df[phase_col].astype(str).str.strip().str.upper()


        v_mv = df[v_col].apply(lambda v: v if v > 1.0 else v * 1000.0)

        # 3. Style Constants
        RAINBOW_COLORS = mpl.colormaps['tab20'].colors
        LINE_PARAMS = {'color': 'black', 'lw': 0.8, 'alpha': 0.9, 'zorder': 10}
        FIXED_ALPHA = 0.25 

        # 4. Y-Axis Bounds
        y_min, y_max = np.percentile(v_mv, [0.01, 99.99])
        y_range = y_max - y_min
        y_limit_low = y_min - (y_range * 0.05) 
        y_limit_high = y_max + (y_range * 0.05)

        # 5. Segmentation and Plotting
        df['block'] = (df[phase_col] != df[phase_col].shift()).cumsum()
        unique_blocks = df['block'].unique()

        print(f"DEBUG unique phases: {df[phase_col].unique().tolist()}")
        print(f"DEBUG results rows vs blocks: {len(results_df)} vs {len(unique_blocks)}")

        # DEBUG: check last phases to ensure no truncation
        last_phases = df[phase_col].tail(10).tolist()
        print(f"DEBUG last phases in file: {last_phases}")

        print(f"DEBUG total blocks detected: {len(unique_blocks)}")
        print(f"DEBUG total rows in df: {len(df)}")

        fig, ax1 = plt.subplots(figsize=(20, 10))

        tick_positions = []
        tick_labels_phase = []
        tick_labels_time = []

        for i, block_id in enumerate(unique_blocks):
            block_data = df[df['block'] == block_id]
            raw_phase = str(block_data[phase_col].iloc[0]).strip().upper()
            
            # LoRa full payload adjustment: merge idle into last TX label
            if is_lora and raw_method == "all" and i == len(unique_blocks) - 1 and raw_phase.startswith("TX"):
                raw_phase = f"{raw_phase} + idle"
            
            try:
                duration_ms = results_df.iloc[i]['Elapsed_ms']
                duration_text = f"{duration_ms/1000:.2f}s"
            except:
                duration_text = "N/A"

            n = len(block_data)
            x = np.linspace(0, 1, n) + i if n > 1 else np.array([0.5]) + i
            ax1.plot(x, v_mv.iloc[block_data.index], **LINE_PARAMS)
            
            ax1.axvspan(i, i + 1, color=RAINBOW_COLORS[i % len(RAINBOW_COLORS)], 
                        alpha=FIXED_ALPHA, zorder=1)
            
            tick_positions.append(i + 0.5)
            tick_labels_phase.append(raw_phase)
            tick_labels_time.append(duration_text)

        # 6. Global Formatting
        main_title = f"{wireless_type.upper()} ({module_name}) Profile - Method: {method_type_name}"
        
        # Tighter Heading/Subheading distance
        plt.suptitle(main_title, fontsize=22, fontweight='bold', y=0.90)
        ax1.set_title(f"{len(df)} Data Entries | Phase duration normalized for visualization | File: {file_name_only}", 
                      fontsize=12, color='#444444', pad=15, fontfamily='monospace')
        
        # Baseline starts at origin (0)
        ax1.set_xlim(0, len(unique_blocks))
        
        ax1.set_ylim(y_limit_low, y_limit_high)
        ax1.set_ylabel("Voltage Potential (mV)", fontsize=14, labelpad=15)
        ax1.set_xlabel("Phase Sequence", fontsize=14, labelpad=20)
        
        ax1.set_xticks(tick_positions)
        ax1.set_xticklabels(tick_labels_phase, rotation=45, ha='right', fontsize=9, fontweight='bold')
        ax1.grid(True, axis='y', linestyle='--', alpha=0.3)

        # --- TOP AXIS ---
        ax2 = ax1.twiny()
        ax2.set_xlim(ax1.get_xlim())
        ax2.set_xticks(tick_positions)
        ax2.set_xticklabels(tick_labels_time, rotation=45, ha='left', 
                            fontsize=9, fontweight='bold', color='#c0392b')
        ax2.set_xlabel("Hardware-Measured Duration (Seconds)", fontsize=12, labelpad=10, fontweight='bold')

        plt.tight_layout(rect=[0, 0, 1, 0.92])

        clean_method = method_type_name.replace(' ', '_')
        base_filename = f"plot_{wireless_type.lower()}_{clean_method}_{file_name_only.replace('.csv', '')}"
        
        plt.savefig(os.path.join(SAVE_PATH, f"png-{base_filename}.png"), dpi=300, bbox_inches='tight')
        plt.savefig(os.path.join(SAVE_PATH, f"svg-{base_filename}.svg"), format='svg', bbox_inches='tight')
        
        
        plt.close()
        print(f"✅ Exported: {base_filename}")

    except Exception as e:
        print(f"⚠️ Error: {e}")

if __name__ == "__main__":
    runs = find_one_run_per_type(BASE_PATH)
    for r in runs:
        plot_and_save_final(r)