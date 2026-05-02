import pandas as pd
import matplotlib.pyplot as plt
import os
import numpy as np

# --- Path Configuration ---
BASE_PATH = "/Users/foml/coding/MSP/year_3/BTR/visualize/data"
SAVE_PATH = "/Users/foml/coding/MSP/year_3/BTR/visualize/plots/graphing_readings"

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
    """
    Standardized 'Rainbow' plotting function. 
    Unique colors per phase, but identical opacities/styles across protocols.
    """
    try:
        # 1. Load Data
        with open(file_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        
        meter_start = next((i for i, line in enumerate(lines) if '# METER' in line), -1)
        if meter_start == -1: return

        df = pd.read_csv(file_path, skiprows=meter_start + 1)
        df.columns = df.columns.str.strip()
        
        # 2. Metadata
        path_parts = file_path.split(os.sep)
        method_name = path_parts[-2].replace('_', ' ').title()
        is_wifi = "esp32" in file_path.lower() or "wifi" in file_path.lower()
        protocol_label = "Wi-Fi (ESP32)" if is_wifi else "BLE (nRF52)"
        
        v_col = 'V_Shunt' if 'V_Shunt' in df.columns else df.columns[1]
        phase_col = 'Phase' if 'Phase' in df.columns else 'phase'
        v_mv = df[v_col].apply(lambda v: v if v > 1.0 else v * 1000.0)

        # 3. GLOBAL STYLE CONSTANTS
        RAINBOW_COLORS = plt.cm.get_cmap('tab20').colors
        TX_ALPHA = 0.35        # Pop for active phases
        IDLE_ALPHA = 0.15      # Subdued for baseline/idle
        LINE_PARAMS = {'color': 'black', 'lw': 0.8, 'alpha': 0.8, 'zorder': 3}

        # 4. Universal Y-Axis Scaling
        y_min, y_max = np.percentile(v_mv, [0.01, 99.99])
        y_range = y_max - y_min
        y_limit_low = y_min - (y_range * 0.05)
        y_limit_high = y_max + (y_range * 0.05)

        # 5. Phase Segmentation
        df['block'] = (df[phase_col] != df[phase_col].shift()).cumsum()
        unique_blocks = df['block'].unique()
        
        plt.figure(figsize=(20, 10))
        
        for i, block_id in enumerate(unique_blocks):
            block_data = df[df['block'] == block_id]
            raw_phase = str(block_data[phase_col].iloc[0]).strip().lower()
            n = len(block_data)
            
            # Normalize X within each block to keep phase widths comparable
            x = np.linspace(0, 1, n) + i if n > 1 else np.array([0.5]) + i
            plt.plot(x, v_mv.iloc[block_data.index], **LINE_PARAMS)
            
            # RAINBOW LOGIC: Unique color per index, synced alpha per designation
            is_active = any(kw in raw_phase for kw in ['tx_', 's'])
            current_alpha = TX_ALPHA if is_active else IDLE_ALPHA
            current_color = RAINBOW_COLORS[i % len(RAINBOW_COLORS)]
            
            plt.axvspan(i, i + 1, color=current_color, alpha=current_alpha, zorder=1)
            
            # Standardized Labels
            plt.text(i + 0.5, y_limit_low + (y_range * 0.02), raw_phase.upper(), 
                     rotation=90, va='bottom', ha='center', fontsize=10, 
                     alpha=0.7, fontweight='bold')

        # 6. Global Formatting
        plt.ylim(y_limit_low, y_limit_high)
        plt.title(f"{protocol_label} Profile: {method_name}", fontsize=20, fontweight='bold', pad=25)
        plt.ylabel("Voltage Potential (mV)", fontsize=14)
        plt.xlabel("Phase Sequence Index", fontsize=14)
        plt.grid(True, axis='y', linestyle='--', alpha=0.3)
        plt.tight_layout()

        # 7. Final Export
        save_name = f"rainbow_sync_{protocol_label.split()[0].lower()}_{method_name.replace(' ', '_')}.png"
        plt.savefig(os.path.join(SAVE_PATH, save_name), dpi=300)
        plt.close()
        print(f"✅ Rainbow Synced: {save_name}")

    except Exception as e:
        print(f"⚠️ Error: {e}")

if __name__ == "__main__":
    runs = find_one_run_per_type(BASE_PATH)
    if runs:
        for r in runs:
            plot_and_save_final(r)