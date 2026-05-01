import os
import pandas as pd
from decimal import Decimal, getcontext
import concurrent.futures
import math

# Set precision for high-accuracy energy math
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

def is_magnitude_glitch(val_a, val_b):
    if val_a == 0 or val_b == 0: return False
    try:
        ratio = float(val_a) / float(val_b)
        log_val = math.log10(ratio)
        return abs(log_val - round(log_val)) < 0.01 and round(log_val) != 0
    except:
        return False

def process_single_file(file_info):
    protocol, exp, file_name, path = file_info
    try:
        if not os.path.exists(path): return None
        with open(path, 'r', encoding='utf-8') as f:
            lines = f.readlines()

        # Find section markers
        info_idx = next((i for i, l in enumerate(lines) if "# INFO" in l), -1)
        meter_idx = next((i for i, l in enumerate(lines) if "# METER" in l), -1)
        
        if meter_idx == -1: return None

        # Capture existing # INFO block
        existing_info = lines[info_idx + 1 : meter_idx] if info_idx != -1 else []
        # Filter out old # OVERVIEW headers if they were already there to avoid nesting
        existing_info = [l for l in existing_info if "# OVERVIEW" not in l]
        
        meter_data = []
        overview_rows = []
        
        # --- 1. CLEANING, PARSING & OVERVIEW EXTRACTION ---
        # We ONLY look after the # METER tag for data and overview candidates
        for line in lines[meter_idx + 1:]:
            line_str = line.strip()
            if not line_str or "delaystart500" in line_str or "start_delay_ms" in line_str:
                continue
                
            parts = [p.strip() for p in line_str.split(',')]
            
            # CHECK FOR 5th COLUMN (Index 4)
            # If there's a value in the 5th column, move this entire row to Overview
            if len(parts) >= 5 and parts[4]:
                overview_rows.append(line_str + "\n")
                continue # Do not include this in the mathematical data area

            if len(parts) < 2 or parts[0] == "start_delay_ms": 
                continue

            try:
                v_raw = Decimal(parts[1])
                v_final_v = v_raw / Decimal('1000') if v_raw > Decimal('1') else v_raw
                v_final_mv = v_final_v * Decimal('1000')
                i_ma = (v_final_mv - V_OFFSET_MV) / R_MEAN
                
                meter_data.append({
                    'ts': parts[0],
                    'v_val': v_final_v,
                    'i_val': i_ma,
                    'state': parts[2] if len(parts) > 2 else ''
                })
            except: continue

        if not meter_data: return None

        # --- 2. MAGNITUDE ISSUE FIX (Only on pure data) ---
        for i in range(1, len(meter_data) - 1):
            curr_i = meter_data[i]['i_val']
            prev_i = meter_data[i-1]['i_val']
            next_i = meter_data[i+1]['i_val']
            if is_magnitude_glitch(curr_i, prev_i) or is_magnitude_glitch(curr_i, next_i):
                meter_data[i]['i_val'] = min(prev_i, next_i)

        # --- 3. RECONSTRUCT FILE: INFO -> OVERVIEW -> METER ---
        cal_header = f"Calibration: R={R_MEAN}Ohm, Offset={V_OFFSET_MV}mV, Vsrc={V_SOURCE_V}V\n"
        
        # Build the new file structure
        new_content = ["# INFO\n", cal_header]
        for line in existing_info:
            if "Calibration:" not in line: # Avoid double calibration lines
                new_content.append(line)
        
        new_content.append("# OVERVIEW\n")
        new_content.extend(overview_rows)
        
        new_content.append("# METER\n")
        for d in meter_data:
            v_str = format(d['v_val'].normalize(), 'f')
            i_str = format(d['i_val'].normalize(), 'f')
            new_content.append(f"{d['ts']},{v_str},{d['state']},{i_str}\n")

        with open(path, 'w', encoding='utf-8') as f:
            f.writelines(new_content)

        # --- 4. SUMMARY STATS ---
        i_series = pd.Series([float(d['i_val']) for d in meter_data])
        v_series = pd.Series([float(d['v_val']) for d in meter_data])
        mean_i = i_series.mean()
        v_src = float(V_SOURCE_V)
        
        rel_v_shunt = float(V_NOISE_MV) / (mean_i * float(R_MEAN)) if mean_i != 0 else 0
        total_rel_uncert = math.sqrt(rel_v_shunt**2 + (float(R_STD)/float(R_MEAN))**2 + (float(V_SOURCE_STD)/v_src)**2)

        return {
            'Protocol': protocol, 'Experiment': exp, 'Run': file_name, 
            'Samples_N': len(i_series),
            'Vshunt_Mean_V': v_series.mean(), 
            'Vshunt_Max_V': v_series.max(),
            'Current_Mean_mA': mean_i, 
            'Current_Max_mA': i_series.max(),
            'Current_Std_mA': i_series.std(),
            'Power_Mean_mW': mean_i * v_src, 
            'Power_Uncertainty_mW': abs(mean_i * v_src) * total_rel_uncert
        }
    except Exception as e:
        print(f"Error in {file_name}: {e}")
        return None

def main():
    print("-" * 50)
    print("STARTING MASTER PROCESSOR (Overview Extraction + Mag Fix)")
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

    with concurrent.futures.ProcessPoolExecutor() as executor:
        results = [r for r in list(executor.map(process_single_file, tasks)) if r]

    if results:
        pd.DataFrame(results).to_csv(SUMMARY_PATH, index=False)
        print(f"\nSUCCESS: Created {SUMMARY_PATH}")
        print("CSV sections updated: # INFO -> # OVERVIEW -> # METER")
    print("-" * 50)

if __name__ == "__main__":
    main()