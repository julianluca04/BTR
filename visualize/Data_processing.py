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

def is_magnitude_glitch(ratio):
    """Detects if ratio is a power of 10 (10, 100, 0.1, etc)."""
    if ratio <= 0: return False
    try:
        log_val = math.log10(float(ratio))
        # If it's very close to an integer (excluding 0), it's a magnitude jump
        return abs(log_val - round(log_val)) < 0.0001 and round(log_val) != 0
    except: return False

def process_single_file(file_info):
    protocol, exp, file_name, path = file_info
    try:
        if not os.path.exists(path): return None
        with open(path, 'r', encoding='utf-8') as f:
            lines = f.readlines()

        meter_idx = next((i for i, l in enumerate(lines) if "# METER" in l), -1)
        if meter_idx == -1: return None

        meter_data = []
        
        # --- 1. TARGETED PARSING ---
        for line in lines[meter_idx + 1:]:
            line_str = line.strip()
            # ONLY skip empty lines or the specific 'delaystart500' marker
            if not line_str or "delaystart500" in line_str:
                continue
                
            parts = [p.strip() for p in line_str.split(',')]
            if len(parts) < 2: continue

            try:
                v_raw = Decimal(parts[1])
                # Unit detection: >1 is mV, <=1 is V
                v_final_v = v_raw / Decimal('1000') if v_raw > Decimal('1') else v_raw
                v_final_mv = v_final_v * Decimal('1000')
                
                # I = (V_shunt_mv - Offset) / R
                i_ma = (v_final_mv - V_OFFSET_MV) / R_MEAN
                
                meter_data.append({
                    'ts': parts[0],
                    'v_val': float(v_final_v),
                    'i_val': float(i_ma),
                    'state': parts[2] if len(parts) > 2 else ''
                })
            except: continue

        if not meter_data: return None

        # --- 2. MAGNITUDE CORRECTION (SAME DIGITS, SMALLER VALUE) ---
        for i in range(1, len(meter_data) - 1):
            curr_i = meter_data[i]['i_val']
            prev_i = meter_data[i-1]['i_val']
            next_i = meter_data[i+1]['i_val']
            
            if curr_i == 0: continue
            
            # Check if current is a magnitude jump from either neighbor
            if is_magnitude_glitch(prev_i / curr_i) or is_magnitude_glitch(next_i / curr_i):
                # Take the smaller value of the two neighbors
                meter_data[i]['i_val'] = min(prev_i, next_i)

        # Extract for stats
        final_i = [d['i_val'] for d in meter_data]
        final_v = [d['v_val'] for d in meter_data]

        # --- 3. STATISTICAL CALCULATIONS ---
        series_i = pd.Series(final_i)
        series_v = pd.Series(final_v)
        mean_i = series_i.mean()
        v_src = float(V_SOURCE_V)
        
        # Uncertainty
        rel_v_shunt = float(V_NOISE_MV) / (mean_i * float(R_MEAN)) if mean_i != 0 else 0
        total_rel_uncert = math.sqrt(rel_v_shunt**2 + (float(R_STD)/float(R_MEAN))**2 + (float(V_SOURCE_STD)/v_src)**2)

        return {
            'Protocol': protocol, 'Experiment': exp, 'Run': file_name, 
            'Samples_N': len(series_i),
            'Vshunt_Mean_V': series_v.mean(), 
            'Vshunt_Min_V': series_v.min(), 
            'Vshunt_Max_V': series_v.max(),
            'Current_Mean_mA': mean_i, 
            'Current_Median_mA': series_i.median(),
            'Current_Mode_mA': series_i.mode().iloc[0] if not series_i.mode().empty else None,
            'Current_Std_mA': series_i.std(),
            'Current_Skewness': series_i.skew(),
            'Current_Kurtosis': series_i.kurt(),
            'Power_Mean_mW': mean_i * v_src, 
            'Power_Uncertainty_mW': abs(mean_i * v_src) * total_rel_uncert
        }
    except Exception:
        return None

def main():
    print("-" * 50)
    print("STARTING RESTORED ANALYSIS RUN...")
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
        df = pd.DataFrame(results)
        df.to_csv(SUMMARY_PATH, index=False)
        print(f"\nSUCCESS: Summary generated with {len(results)} runs.")
        print(f"Location: {SUMMARY_PATH}")
    else:
        print("\nERROR: No data processed. Check file paths and # METER tags.")
    print("-" * 50)

if __name__ == "__main__":
    main()