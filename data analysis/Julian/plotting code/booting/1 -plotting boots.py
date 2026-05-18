import os
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt

# --- Paths ---
BTR_RESULTS_PATH = '/Users/foml/Library/Mobile Documents/com~apple~CloudDocs/important/coding/MSP/year_3/Thesis work/BTR_results'
BOOT_DATA_PATH = os.path.join(BTR_RESULTS_PATH, 'boot data')
BASE_PLOT_DIR = os.path.join(BTR_RESULTS_PATH, 'plots', 'boots')
PLOT_OUTPUT_DIR = os.path.join(BASE_PLOT_DIR, '1 - plotting boots')
CALIB_PATH = os.path.join(BTR_RESULTS_PATH, 'calibration_constants_summary.csv')
PROTOCOLS = ["wifi", "ble", "lora"]

HARDCODED_BOOT_DURATIONS = {
    "ble": 1500,
    "lora": 5500,
    "wifi": 4000,
}

# --- Configuration ---
THRESHOLD_PCT = 0.25   
LOOKAHEAD_SAMPLES = 5  
PLATEAU_WINDOW = 30    
PLATEAU_STD_THRESH = 0.0002 
POST_PLATEAU_WAIT_MS = 2000 

def load_calib_constants(path):
    """Loads characterized R and Offset for accurate mA conversion."""
    try:
        df = pd.read_csv(path)
        r_shunt = df.loc[df['Metric'] == 'Resistance', 'Mean'].values[0]
        v_offset = df.loc[df['Metric'] == 'Offset', 'Mean'].values[0]
        return r_shunt, v_offset
    except Exception as e:
        print(f"⚠️ Calibration file error: {e}. Using fallback 0.1 Ohm / 0 Offset.")
        return 0.1, 0.0

# Load constants globally
R_SHUNT, V_OFFSET = load_calib_constants(CALIB_PATH)

def plot_sustained_25pct_breakaway(protocol, files):
    protocol_names = {"wifi": "Wi-Fi (ESP32-C3)", "ble": "BLE (nRF52840)", "lora": "LoRa (RN2903)"}
    formal_name = protocol_names.get(protocol, protocol.upper())

    plt.figure(figsize=(14, 7))
    plotted_count = 0
    failed_files = []
    
    anchor_times = []
    max_relevant_time = 0
    plot_data_list = []

    for file_path in files:
        fname = os.path.basename(file_path)
        try:
            with open(file_path, 'r') as f:
                lines = f.readlines()
            
            res_idx = next((i for i, l in enumerate(lines) if "# RESULTS" in l), None)
            met_idx = next((i for i, l in enumerate(lines) if "# METER" in l), None)
            if res_idx is None or met_idx is None:
                failed_files.append(f"{fname} (Missing Headers)")
                continue

            # 1. Load Data
            df = pd.read_csv(file_path, skiprows=met_idx + 1)
            df.columns = df.columns.str.strip()
            
            # 2. Boot Start Trigger (T0) based on Voltage
            local_min = df['V_Shunt'].min()
            threshold = local_min * (1.0 + THRESHOLD_PCT)
            if local_min <= 0: threshold = 0.0005 
            
            potential_hits = df.index[df['V_Shunt'] > threshold].tolist()
            trigger_idx = None
            for idx in potential_hits:
                if idx + LOOKAHEAD_SAMPLES < len(df):
                    if df['V_Shunt'].iloc[idx : idx + LOOKAHEAD_SAMPLES].min() > threshold:
                        trigger_idx = idx
                        break
            
            if trigger_idx is None:
                failed_files.append(f"{fname} (No 25% rise found)")
                continue 

            # 3. Time Alignment
            df['Timestamp_Start'] = pd.to_datetime(df['Timestamp_Start'], format='ISO8601')
            t_zero = df.loc[trigger_idx, 'Timestamp_Start']
            df['rel_ms'] = (df['Timestamp_Start'] - t_zero).dt.total_seconds() * 1000
            
            # --- CALCULATION LOGIC: Convert Voltage to mA ---
            # Using the characterized R and V_offset
            # (V_measured - V_offset) / R * 1000 = mA
            df['Current_ma'] = ((df['V_Shunt'] - V_OFFSET) / R_SHUNT) * 1000.0
            
            # 4. Uncertainty Scaling (mV uncertainty converted to mA uncertainty)
            df_res = pd.read_csv(file_path, skiprows=res_idx + 1, nrows=1)
            df_res.columns = df_res.columns.str.strip()
            u_col = [c for c in df_res.columns if 'Uncertainty_V' in c][0]
            v_uncert_v = df_res[u_col].iloc[0]
            curr_uncert_ma = (v_uncert_v / R_SHUNT) * 1000.0
            
            # 5. Global Plateau Detection
            search_df = df.loc[trigger_idx:].copy()
            found_plateau_idx = None
            for i in range(len(search_df) - PLATEAU_WINDOW, 0, -1):
                window = search_df['V_Shunt'].iloc[i : i + PLATEAU_WINDOW]
                if window.std() < PLATEAU_STD_THRESH:
                    p_level = window.mean()
                    remaining_max = search_df['V_Shunt'].iloc[i + PLATEAU_WINDOW:].max()
                    if pd.isna(remaining_max) or remaining_max < (p_level * 1.15):
                        found_plateau_idx = search_df.index[i]
                        break
            
            anchor_ms = df.loc[found_plateau_idx, 'rel_ms'] if found_plateau_idx is not None else df['rel_ms'].max()
            anchor_times.append(anchor_ms)
            
            end_ms = anchor_ms + POST_PLATEAU_WAIT_MS
            df_plot = df[(df['rel_ms'] >= -1000) & (df['rel_ms'] <= end_ms)].copy()
            max_relevant_time = max(max_relevant_time, end_ms)
            
            plot_data_list.append((df_plot, curr_uncert_ma))
            plotted_count += 1

        except Exception as e:
            failed_files.append(f"{fname} (Error: {str(e)})")

    # 6. Final Rendering
    for df_p, c_u in plot_data_list:
        plt.step(df_p['rel_ms'], df_p['Current_ma'], where='post', alpha=0.15, lw=1, color='tab:blue')
        plt.fill_between(df_p['rel_ms'], df_p['Current_ma'] - c_u, df_p['Current_ma'] + c_u, 
                         alpha=0.01, step='post', color='gray')

    if plotted_count > 0:
        plt.suptitle(f"Power-On Consumption Profile: {formal_name}", fontsize=38, fontweight='bold')
        boot_duration = HARDCODED_BOOT_DURATIONS.get(protocol, np.mean(anchor_times) if anchor_times else 0)
        plt.title(f"Aligned at $T_0$ | {plotted_count} Runs | Calculated via $R_{{shunt}}$={R_SHUNT:.3f}$\Omega$", fontsize=32, pad=24)
        
        plt.xlabel("Time relative to boot trigger [ms]", fontsize=28)
        plt.ylabel("Current Consumption [mA]", fontsize=28)
        plt.xticks(fontsize=24)
        plt.yticks(fontsize=24)
        
        plt.axvline(x=0, color='red', linestyle='--', linewidth=1.5, label='Boot Start ($T_0$)')
        if boot_duration > 0:
            plt.axvline(x=boot_duration, color='tab:green', linestyle=':', linewidth=2.5, label=f'Boot End ({boot_duration:.0f} ms)')
        
        plt.legend(loc='lower right', fontsize=28)
        plt.xlim(-1000, max_relevant_time) 
        plt.grid(True, linestyle=':', alpha=0.6)
        plt.tight_layout(rect=[0, 0.03, 1, 0.95])

        plt.savefig(os.path.join(PLOT_OUTPUT_DIR, f"png-{protocol}_current_boot_plot.png"), dpi=300, bbox_inches='tight')
        plt.savefig(os.path.join(PLOT_OUTPUT_DIR, f"svg-{protocol}_current_boot_plot.svg"), format='svg', bbox_inches='tight')
        print(f"✅ Exported mA plots for {protocol}.")
    
    plt.close()

def main():
    if not os.path.exists(PLOT_OUTPUT_DIR): os.makedirs(PLOT_OUTPUT_DIR)
    for proto in PROTOCOLS:
        proto_dir = os.path.join(BOOT_DATA_PATH, proto)
        if os.path.isdir(proto_dir):
            csv_files = sorted([os.path.join(proto_dir, f) for f in os.listdir(proto_dir) if f.endswith('.csv')])
            if csv_files: plot_sustained_25pct_breakaway(proto, csv_files)

if __name__ == "__main__":
    main()