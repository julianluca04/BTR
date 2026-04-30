import os
import pandas as pd
from decimal import Decimal, getcontext
import concurrent.futures
import math

# Set precision for Decimal math
getcontext().prec = 20

# --- MEASURED PHYSICAL CONSTANTS ---
R_MEAN = Decimal('1.134584')
R_STD = Decimal('0.001448')
V_OFFSET_MV = Decimal('-0.002182')
V_NOISE_MV = Decimal('0.001699')
V_SOURCE_V = Decimal('5.020379')
V_SOURCE_STD = Decimal('0.000356')

# --- PATH CONFIGURATION ---
BASE_PATH = "/Users/foml/coding/MSP/year_3/BTR/visualize/data"
SUMMARY_DIR = "/Users/foml/coding/MSP/year_3/BTR/visualize"
SUMMARY_PATH = os.path.join(SUMMARY_DIR, "summary_energy_comprehensive.csv")

PROTOCOLS = ["wifi", "BLE"]
EXPERIMENTS = ["chunk", "byte", "all"]

def is_power_of_ten(ratio):
    """Detects magnitude jumps (spikes) caused by logging errors."""
    if ratio <= 0: return False
    try:
        log_val = math.log10(float(ratio))
        return abs(log_val - round(log_val)) < 0.0001 and round(log_val) != 0
    except: return False

def process_single_file(file_info):
    protocol, exp, file_name, path = file_info
    try:
        if not os.path.exists(path): return None
        with open(path, 'r', encoding='utf-8') as f:
            lines = f.readlines()

        info_idx = next((i for i, l in enumerate(lines) if "# INFO" in l), -1)
        meter_idx = next((i for i, l in enumerate(lines) if "# METER" in l), -1)
        if meter_idx == -1: return None

        existing_info = lines[info_idx + 1 : meter_idx] if (info_idx != -1 and info_idx < meter_idx) else []
        new_info_rows, meter_data, raw_v_normalized = [], [], []

        # --- 1. PARSING WITH 500 SAMPLE DELAY ---
        data_counter = 0
        for line in lines[meter_idx + 1:]:
            line_str = line.strip()
            if not line_str or ',' not in line_str: continue
            parts = [p.strip() for p in line_str.split(',')]

            is_info_row = (len(parts) >= 4 and parts[3]) 
            if not is_info_row:
                try:
                    v_raw = Decimal(parts[1])
                except:
                    is_info_row = True

            if is_info_row:
                formatted_line = line_str + "\n"
                if formatted_line not in existing_info: 
                    new_info_rows.append(formatted_line)
            else:
                data_counter += 1
                # SKIP THE FIRST 500 SAMPLES
                if data_counter <= 500:
                    continue

                v_raw = Decimal(parts[1])
                v_final_v = v_raw / Decimal('1000') if v_raw > Decimal('1') else v_raw
                v_final_mv = v_final_v * Decimal('1000')
                raw_v_normalized.append(float(v_final_v))
                i_ma = (v_final_mv - V_OFFSET_MV) / R_MEAN

                meter_data.append({
                    'ts': parts[0],
                    'v_val': v_final_v,
                    'i_val': i_ma,
                    'state': parts[2] if len(parts) > 2 else ''
                })

        if not meter_data: return None

        # --- 2. MAGNITUDE SPIKE CORRECTION ---
        for i in range(1, len(meter_data) - 1):
            curr, abv, bel = meter_data[i], meter_data[i-1], meter_data[i+1]
            if curr['i_val'] == 0: continue
            if is_power_of_ten(abv['i_val']/curr['i_val']) or is_power_of_ten(bel['i_val']/curr['i_val']):
                curr['i_val'] = min(abv['i_val'], bel['i_val'])

        # --- 3. RECONSTRUCT RAW FILE ---
        final_info = existing_info + new_info_rows
        cal_log = f"Calibration: R={R_MEAN}Ohm, Offset={V_OFFSET_MV}mV, Src={V_SOURCE_V}V\n"
        if cal_log not in final_info: final_info.insert(0, cal_log)

        new_content = ["# INFO\n"] + final_info + ["# METER\n"]
        processed_ma = []
        for r in meter_data:
            processed_ma.append(float(r['i_val']))
            v_str = format(r['v_val'].normalize(), 'f')
            i_str = format(r['i_val'].normalize(), 'f')
            new_content.append(f"{r['ts']},{v_str},{r['state']},{i_str}\n")

        with open(path, 'w', encoding='utf-8') as f:
            f.writelines(new_content)

        # --- 4. COMPREHENSIVE STATS ---
        series_i = pd.Series(processed_ma)
        series_v = pd.Series(raw_v_normalized)
        mean_i = series_i.mean()
        v_src = float(V_SOURCE_V)
        
        # Uncertainty calculation
        rel_v_shunt = float(V_NOISE_MV) / (mean_i * float(R_MEAN)) if mean_i != 0 else 0
        rel_r = float(R_STD) / float(R_MEAN)
        rel_v_src = float(V_SOURCE_STD) / v_src
        total_rel_uncert = math.sqrt(rel_v_shunt**2 + rel_r**2 + rel_v_src**2)

        return {
            'Protocol': protocol, 'Experiment': exp, 'Run': file_name, 'Samples_N': len(series_i),
            'Vshunt_Mean_V': series_v.mean(), 'Vshunt_Min_V': series_v.min(), 'Vshunt_Max_V': series_v.max(),
            'Current_Mean_mA': mean_i, 
            'Current_Median_mA': series_i.median(),
            'Current_Mode_mA': series_i.mode().iloc[0] if not series_i.mode().empty else None,
            'Current_Min_mA': series_i.min(), 'Current_Max_mA': series_i.max(),
            'Current_Std_mA': series_i.std(), 
            'Current_Skewness': series_i.skew(), 
            'Current_Kurtosis': series_i.kurt(),
            'Power_Mean_mW': mean_i * v_src, 
            'Power_Uncertainty_mW': abs(mean_i * v_src) * total_rel_uncert,
            'Power_CV': (series_i.std() / mean_i) if mean_i != 0 else 0
        }
    except Exception as e:
        return f"Error in {file_name}: {e}"

def main():
    print("-" * 50)
    print("STARTING FULL ANALYSIS (Spike Correction + 500 Sample Delay)...")
    if not os.path.exists(SUMMARY_DIR): os.makedirs(SUMMARY_DIR)

    tasks = []
    for protocol in PROTOCOLS:
        for exp in EXPERIMENTS:
            folder = os.path.join(BASE_PATH, protocol, exp)
            if os.path.exists(folder):
                files = [f for f in os.listdir(folder) if f.endswith('.csv')]
                print(f"Found {len(files)} files in {protocol}/{exp}")
                for f in files:
                    tasks.append((protocol, exp, f, os.path.join(folder, f)))

    if not tasks:
        print("ERROR: No CSV files found. Check BASE_PATH.")
        return

    print(f"Processing {len(tasks)} files...")
    with concurrent.futures.ProcessPoolExecutor() as executor:
        results = list(executor.map(process_single_file, tasks))

    all_summary = [r for r in results if isinstance(r, dict)]
    if all_summary:
        df = pd.DataFrame(all_summary)
        df.to_csv(SUMMARY_PATH, index=False)
        print(f"\nSUCCESS: Summary with full statistics saved to:\n{SUMMARY_PATH}")
    else:
        print("\nFATAL ERROR: No valid data extracted.")
    print("-" * 50)

if __name__ == "__main__":
    main()