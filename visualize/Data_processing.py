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

def is_magnitude_glitch(val_curr, val_neighbor):
    """Detects if value jumped or dropped by more than 7.5x compared to neighbor."""
    if val_curr == 0 or val_neighbor == 0: return False
    try:
        ratio = float(val_curr) / float(val_neighbor)
        return ratio > 7.5 or ratio < (1 / 7.5)
    except:
        return False

def process_single_file(file_info):
    protocol, exp, file_name, path = file_info
    try:
        if not os.path.exists(path): return None
        with open(path, 'r', encoding='utf-8') as f:
            lines = f.readlines()

        # Section indexing
        info_idx = next((i for i, l in enumerate(lines) if "# INFO" in l), -1)
        meter_idx = next((i for i, l in enumerate(lines) if "# METER" in l), -1)
        if meter_idx == -1: return None

        # 1. CLEANING & SECTION PREP
        # Keep old info notes, but remove old Overview or Calibration headers
        existing_info = lines[info_idx+1 : meter_idx] if info_idx != -1 else []
        existing_info = [l for l in existing_info if "# OVERVIEW" not in l and "Calibration:" not in l]
        
        raw_data_rows = []
        overview_rows = []
        glitch_log = []
        
        for line in lines[meter_idx + 1:]:
            line_str = line.strip()
            # Explicitly delete marker/junk rows
            if not line_str or "delaystart500" in line_str or "start_delay_ms" in line_str:
                continue
                
            parts = [p.strip() for p in line_str.split(',')]
            
            # Extract Overview rows (Value in 5th column)
            if len(parts) >= 5 and parts[4]:
                overview_rows.append(line_str + "\n")
                continue

            if len(parts) < 2: continue

            try:
                v_raw = Decimal(parts[1])
                # Unit detection (mV vs V)
                v_v = v_raw / Decimal('1000') if v_raw > Decimal('1') else v_raw
                raw_data_rows.append({
                    'ts': parts[0], 
                    'v_val': v_v, 
                    'state': parts[2] if len(parts) > 2 else ''
                })
            except: continue

        if not raw_data_rows: return None

        # 2. MAGNITUDE CORRECTION (> 7.5x threshold)
        for i in range(1, len(raw_data_rows) - 1):
            curr_v = raw_data_rows[i]['v_val']
            prev_v = raw_data_rows[i-1]['v_val']
            next_v = raw_data_rows[i+1]['v_val']
            
            if is_magnitude_glitch(curr_v, prev_v) and is_magnitude_glitch(curr_v, next_v):
                glitch_log.append(f"[{file_name}] Spike at {raw_data_rows[i]['ts']}: {curr_v}V -> {min(prev_v, next_v)}V")
                raw_data_rows[i]['v_val'] = min(prev_v, next_v)

        # 3. RECONSTRUCTION & DATA PROCESSING
        final_csv_lines = []
        stats_i_list = []
        stats_v_list = []

        for d in raw_data_rows:
            v_v = d['v_val']
            v_mv = v_v * Decimal('1000')
            # I = (Vshunt_mv - Offset) / R
            i_ma = (v_mv - V_OFFSET_MV) / R_MEAN
            
            stats_v_list.append(float(v_v))
            stats_i_list.append(float(i_ma))
            
            v_str = format(v_v.normalize(), 'f')
            i_str = format(i_ma.normalize(), 'f')
            final_csv_lines.append(f"{d['ts']},{v_str},{d['state']},{i_str}\n")

        # Re-write file with headers
        cal_line = f"Calibration: R={R_MEAN}Ohm, Offset={V_OFFSET_MV}mV, Vsrc={V_SOURCE_V}V\n"
        new_content = (["# INFO\n", cal_line] + existing_info + 
                       ["# OVERVIEW\n"] + overview_rows + 
                       ["# METER\n"] + final_csv_lines)
        
        with open(path, 'w', encoding='utf-8') as f:
            f.writelines(new_content)

        # 4. FULL COMPREHENSIVE STATS
        ser_i = pd.Series(stats_i_list)
        ser_v = pd.Series(stats_v_list)
        mean_i = ser_i.mean()
        v_src = float(V_SOURCE_V)
        
        # Uncertainty
        rel_v_shunt = float(V_NOISE_MV) / (mean_i * float(R_MEAN)) if mean_i != 0 else 0
        total_rel_uncert = math.sqrt(rel_v_shunt**2 + (float(R_STD)/float(R_MEAN))**2 + (float(V_SOURCE_STD)/v_src)**2)

        return {
            'stats': {
                'Protocol': protocol, 
                'Experiment': exp, 
                'Run': file_name, 
                'Samples_N': len(ser_i),
                'Vshunt_Mean_V': ser_v.mean(),
                'Vshunt_Max_V': ser_v.max(),
                'Current_Mean_mA': mean_i,
                'Current_Median_mA': ser_i.median(),
                'Current_Mode_mA': ser_i.mode().iloc[0] if not ser_i.mode().empty else None,
                'Current_Max_mA': ser_i.max(),
                'Current_Std_mA': ser_i.std(),
                'Current_Skewness': ser_i.skew(),
                'Current_Kurtosis': ser_i.kurt(),
                'Power_Mean_mW': mean_i * v_src,
                'Power_Uncertainty_mW': abs(mean_i * v_src) * total_rel_uncert
            },
            'glitches': glitch_log
        }
    except Exception as e:
        print(f"Error in {file_name}: {e}")
        return None

def main():
    print("-" * 50)
    print("RUNNING FINAL MASTER SCRIPT (Full Summary + 7.5x Mag Fix)")
    if not os.path.exists(SUMMARY_DIR): os.makedirs(SUMMARY_DIR)

    tasks = []
    for protocol in PROTOCOLS:
        for exp in EXPERIMENTS:
            folder = os.path.join(BASE_PATH, protocol, exp)
            if os.path.exists(folder):
                for f in [f for f in os.listdir(folder) if f.endswith('.csv')]:
                    tasks.append((protocol, exp, f, os.path.join(folder, f)))

    all_glitches = []
    summary_results = []

    with concurrent.futures.ProcessPoolExecutor() as executor:
        for res in executor.map(process_single_file, tasks):
            if res:
                summary_results.append(res['stats'])
                all_glitches.extend(res['glitches'])

    # Report Glitches
    if all_glitches:
        print(f"\n--- {len(all_glitches)} GLITCHES DETECTED ---")
        for g in all_glitches: print(g)

    # Save Comprehensive CSV
    if summary_results:
        df = pd.DataFrame(summary_results)
        df.to_csv(SUMMARY_PATH, index=False)
        print(f"\nSUCCESS: Comprehensive summary saved to {SUMMARY_PATH}")
    
    print("-" * 50)

if __name__ == "__main__":
    main()