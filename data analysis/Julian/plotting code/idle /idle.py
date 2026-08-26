import os
import glob
import pandas as pd
import numpy as np

# --- Path Configuration ---
BASE_PATH = '/Users/foml/Library/Mobile Documents/com~apple~CloudDocs/important/coding/MSP/year_3/Thesis work/BTR_results/data'

def extract_labeled_phase_5s_baselines(base_path):
    """
    Screens data directories, parses the raw # METER data streams, 
    isolates rows where Phase == 'baseline', limits to the first 5 seconds 
    of that specific phase, and calculates terminal metrics.
    """
    print("=" * 115)
    print("  🔍 SCREENING ONLY THE FIRST 5 SECONDS OF EXPLICIT 'baseline' LABELED PHASES")
    print("=" * 115)
    
    csv_pattern = os.path.join(base_path, "**", "*.csv")
    csv_files = glob.glob(csv_pattern, recursive=True)
    
    if not csv_files:
        print(f"❌ No CSV files detected at path: {base_path}")
        return

    # Structure to hold raw baseline readings grouped by Module -> Method Type
    structured_data = {
        "Wi-Fi (ESP32-C3)": {"Full Payload": [], "Chunk-By-Chunk": [], "Byte-By-Byte": []},
        "BLE (nRF52840)": {"Full Payload": [], "Chunk-By-Chunk": [], "Byte-By-Byte": []},
        "LoRa (RN2903)": {"Full Payload": [], "Chunk-By-Chunk": [], "Byte-By-Byte": []}
    }

    method_map = {"all": "Full Payload", "byte": "Byte-By-Byte", "chunk": "Chunk-By-Chunk"}
    processed_count = 0

    for file_path in csv_files:
        try:
            path_lower = file_path.lower()
            path_parts = os.path.normpath(file_path).split(os.sep)
            
            # Identify the hardware profile module group
            if "esp32" in path_lower or "wifi" in path_lower:
                mod_key = "Wi-Fi (ESP32-C3)"
            elif "lora" in path_lower or "rn2903" in path_lower:
                mod_key = "LoRa (RN2903)"
            else:
                mod_key = "BLE (nRF52840)"

            # Identify the operational method (experiment type) from directory path structure
            raw_method = "all"
            for chunk in path_parts:
                if any(m in chunk.lower() for m in method_map.keys()):
                    if "all" in chunk.lower(): raw_method = "all"
                    elif "chunk" in chunk.lower(): raw_method = "chunk"
                    elif "byte" in chunk.lower(): raw_method = "byte"

            method_key = method_map.get(raw_method, "Full Payload")

            # Parse structural layout down to # METER matrix tracking (ignoring # RESULTS completely)
            with open(file_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()
            meter_start = next((i for i, line in enumerate(lines) if '# METER' in line), -1)
            
            if meter_start == -1:
                continue
                
            df = pd.read_csv(file_path, skiprows=meter_start + 1)
            df.columns = df.columns.str.strip()

            phase_col = 'Phase' if 'Phase' in df.columns else 'phase'
            current_col = 'Current' if 'Current' in df.columns else df.columns[4]
            time_col = 'Timestamp_Start' if 'Timestamp_Start' in df.columns else df.columns[0]

            # Filter rows where the phase is strictly 'baseline'
            if phase_col in df.columns:
                baseline_df = df[df[phase_col].astype(str).str.strip().str.lower() == 'baseline'].copy()
            else:
                continue

            if baseline_df.empty:
                continue

            # Convert Time to datetime to safely extract a delta
            baseline_df[time_col] = pd.to_datetime(baseline_df[time_col], errors='coerce')
            baseline_df = baseline_df.dropna(subset=[time_col])
            
            if baseline_df.empty:
                continue
                
            # Get the exact timestamp when the baseline phase began
            phase_start_time = baseline_df[time_col].iloc[0]
            
            # Keep only the rows within 5.0 seconds of that starting point
            baseline_5s_df = baseline_df[(baseline_df[time_col] - phase_start_time).dt.total_seconds() <= 5.0]

            if baseline_5s_df.empty:
                continue

            # Convert to numeric arrays safely
            current_raw = pd.to_numeric(baseline_5s_df[current_col], errors='coerce').dropna()
            current_ma = current_raw * 1000.0

            if not current_ma.empty:
                structured_data[mod_key][method_key].extend(current_ma.values)
                processed_count += 1

        except Exception:
            continue

    print(f"📊 Successfully parsed 5-second baseline blocks from {processed_count} files.\n")

    # --- Print Structured Terminal Outputs ---
    for mod_name, methods in structured_data.items():
        has_data = any(len(samples) > 0 for samples in methods.values())
        if not has_data:
            continue
            
        print(f"\n📦 HARDWARE PROTOCOL: {mod_name}")
        print("-" * 115)
        print(f"{'Experiment Type (Methodology)':<35} | {'Mean Baseline':<16} | {'Std Dev (σ)':<14} | {'Min Value':<14} | {'Max Value':<14}")
        print("-" * 115)
        
        all_module_samples = []
        
        for method_type in ["Full Payload", "Chunk-By-Chunk", "Byte-By-Byte"]:
            samples = methods[method_type]
            if len(samples) == 0:
                print(f"{method_type:<35} | {'No Data Found':>14} | {'-':>14} | {'-':>14} | {'-':>14}")
                continue
                
            exp_type_mean = np.mean(samples)
            exp_type_std = np.std(samples)
            exp_type_min = np.min(samples)
            exp_type_max = np.max(samples)
            all_module_samples.extend(samples)
            
            print(f"{method_type:<35} | {exp_type_mean:>11.4f} mA | {exp_type_std:>12.4f} mA | {exp_type_min:>10.4f} mA | {exp_type_max:>10.4f} mA")
            
        if all_module_samples:
            total_mean = np.mean(all_module_samples)
            total_std = np.std(all_module_samples)
            total_min = np.min(all_module_samples)
            total_max = np.max(all_module_samples)
            
            print("-" * 115)
            print(f"🌟 OVERALL MEAN {mod_name.split(' ')[0].upper()} BASELINE TOTALS ( capped at 5s ):")
            print(f"   -> Mean: {total_mean:.4f} mA | σ: {total_std:.4f} mA | Min: {total_min:.4f} mA | Max: {total_max:.4f} mA")
            print("=" * 115)

if __name__ == "__main__":
    extract_labeled_phase_5s_baselines(BASE_PATH)