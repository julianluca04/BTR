import os
import pandas as pd
import numpy as np
from decimal import Decimal, getcontext
import concurrent.futures
import math

# Set precision for high-accuracy energy math
getcontext().prec = 20

# --- MEASURED PHYSICAL CONSTANTS (SI base units: V, A, Ω) ---
R_MEAN = 1.134584      # Ω
R_STD = 0.001448       # Ω (Type B, resistor tolerance)
V_OFFSET = -0.002182e-3  # V (converted from mV)
U_OFFSET = 0.001699e-3   # V (Type B, systematic offset uncertainty)
V_SOURCE = 5.020379    # V
U_VSOURCE = 0.000356   # V (Type B, source stability)

# --- HMC8012 SYSTEMATIC UNCERTAINTY (Type B) ---
HMC8012_READING_PCT = 0.00015  # 0.015%
HMC8012_RANGE_PCT = 0.00002    # 0.002%
HMC8012_RANGE_V = 0.400        # V (400mV range)
RECT_TO_GAUSSIAN = math.sqrt(3)  # k=1 conversion

# --- CONFIGURATION ---
BASE_PATH = "/Users/foml/coding/MSP/year_3/BTR/visualize/data"
SUMMARY_DIR = "/Users/foml/coding/MSP/year_3/BTR/visualize"
SUMMARY_PATH = os.path.join(SUMMARY_DIR, "summary_energy_comprehensive.csv")
PROTOCOLS = ["wifi", "BLE"]
EXPERIMENTS = ["chunk", "byte", "all"]
K_FACTOR = 2  # Coverage factor for 95% CI (Expanded Uncertainty)

def is_7_5_x_glitch(val_curr, val_neighbor):
    """Detects if value jumped/dropped by >= 7.5x compared to neighbor."""
    if val_curr == 0 or val_neighbor == 0: 
        return False
    try:
        ratio = val_curr / val_neighbor
        return ratio >= 7.5 or ratio <= (1 / 7.5)
    except:
        return False

def effective_sample_size(data_series):
    """Compute effective sample size accounting for autocorrelation."""
    N = len(data_series)
    if N < 3: return N
    try:
        rho = data_series.autocorr(lag=1)
        if np.isnan(rho) or abs(rho) >= 1: return N
        return max(1, N * (1 - rho) / (1 + rho))
    except:
        return N

def process_single_file(file_info):
    protocol, exp, file_name, path = file_info
    try:
        if not os.path.exists(path): return None
        with open(path, 'r', encoding='utf-8') as f:
            lines = f.readlines()

        info_idx = next((i for i, l in enumerate(lines) if "# INFO" in l), -1)
        meter_idx = next((i for i, l in enumerate(lines) if "# METER" in l), -1)
        if meter_idx == -1: return None

        # 1. SECTION PREP (Preserving Existing INFO)
        existing_info = []
        skip_meta = False
        for l in lines[info_idx+1 : meter_idx]:
            s = l.strip()
            if "# OVERVIEW" in l or "Calibration:" in l:
                continue
            if s == "# META":
                skip_meta = True
                continue
            if skip_meta:
                if s.startswith("#") and s != "# META":
                    skip_meta = False
                    existing_info.append(l)
                continue
            existing_info.append(l)
            
        raw_data_rows, overview_rows, glitch_log = [], [], []
        
        for line in lines[meter_idx + 1:]:
            line_str = line.strip()
            if not line_str or "delay" in line_str: continue
            parts = [p.strip() for p in line_str.split(',')]
            
            if len(parts) >= 5 and parts[4]:
                overview_rows.append(line_str + "\n")
                continue
            if len(parts) < 2: continue
            try:
                v_raw = float(parts[1])
                # Magnitude Normalization
                v_norm = v_raw / 1000.0 if v_raw > 1.0 else v_raw 
                raw_data_rows.append({
                    'ts': parts[0],
                    'v_norm': v_norm,
                    'state': parts[2] if len(parts) > 2 else ''
                })
            except: continue

        if not raw_data_rows: return None

        # 2. GLITCH CORRECTION (7.5x logic: Check Above/Below, take smaller of neighbors)
        v_orig = [row['v_norm'] for row in raw_data_rows]
        v_clean = list(v_orig)
        NOISE_GATE = 0.001 

        for i in range(1, len(v_orig) - 1):
            v_curr = v_orig[i]
            v_prev = v_orig[i-1]
            v_next = v_orig[i+1]

            # Gate: ignore microvolt background noise
            if abs(v_curr) > NOISE_GATE:
                # Trigger if 7.5x difference with either neighbor
                if is_7_5_x_glitch(v_curr, v_prev) or is_7_5_x_glitch(v_curr, v_next):
                    # Correction: Use the smaller value of the two neighbors
                    v_fixed = min(v_prev, v_next)
                    v_clean[i] = v_fixed
                    glitch_log.append(f"[{file_name}] 7.5x glitch corrected at {raw_data_rows[i]['ts']}")

        # 3. STATISTICAL CALCULATIONS
        vshunt_series = pd.Series(v_clean)
        current_series = (vshunt_series - V_OFFSET) / R_MEAN # Amps
        
        N = len(vshunt_series)
        N_eff = effective_sample_size(vshunt_series)
        
        # Uncertainty Propagation
        u_typeA = vshunt_series.std() / math.sqrt(N_eff) if N_eff > 0 else 0
        u_typeB_hmc = math.sqrt(((HMC8012_READING_PCT * abs(vshunt_series.mean()))/RECT_TO_GAUSSIAN)**2 + 
                                ((HMC8012_RANGE_PCT * HMC8012_RANGE_V)/RECT_TO_GAUSSIAN)**2)
        u_vshunt = math.sqrt(u_typeA**2 + u_typeB_hmc**2 + U_OFFSET**2)
        
        mean_v = vshunt_series.mean()
        rel_u_current = math.sqrt((u_vshunt/mean_v)**2 + (R_STD/R_MEAN)**2) if mean_v != 0 else 0
        rel_u_power = math.sqrt(rel_u_current**2 + (U_VSOURCE/V_SOURCE)**2)
        
        mean_p_mw = (current_series.mean() * V_SOURCE) * 1000

        # 4. REWRITE FILE
        final_csv_lines = [
            f"{raw_data_rows[i]['ts']},{v_clean[i]:.9f},{raw_data_rows[i]['state']},{((v_clean[i]-V_OFFSET)/R_MEAN):.9f}\n"
            for i in range(len(v_clean))
        ]
        cal_line = f"Calibration: R={R_MEAN}Ohm, Offset={V_OFFSET*1000:.4f}mV, Vsrc={V_SOURCE}V, Logic=7.5xAboveBelowMinNeighbor\n"
        with open(path, 'w', encoding='utf-8') as f:
            f.writelines(["# INFO\n", cal_line] + existing_info + ["# OVERVIEW\n"] + overview_rows + ["# METER\n"] + final_csv_lines)

        # 5. COMPREHENSIVE SUMMARY
        return {
            'stats': {
                'Protocol': protocol, 'Experiment': exp, 'Run': file_name,
                'Samples_N': N, 'Samples_N_eff': N_eff,
                'Vshunt_Mean_V': vshunt_series.mean(),
                'Vshunt_Median_V': vshunt_series.median(),
                'Vshunt_Max_V': vshunt_series.max(),
                'Vshunt_Min_V': vshunt_series.min(),
                'Vshunt_Combined_Uncert_V': u_vshunt,
                'Current_Mean_mA': current_series.mean() * 1000,
                'Current_Median_mA': current_series.median() * 1000,
                'Current_Mode_mA': (current_series.mode().iloc[0] * 1000) if not current_series.mode().empty else None,
                'Current_Max_mA': current_series.max() * 1000,
                'Current_Min_mA': current_series.min() * 1000,
                'Current_Std_mA': current_series.std() * 1000,
                'Current_Skewness': current_series.skew(),
                'Current_Kurtosis': current_series.kurt(),
                'Current_Spread_mA': (current_series.max() - current_series.min()) * 1000,
                'Power_Mean_mW': mean_p_mw,
                'Power_Median_mW': (current_series.median() * V_SOURCE) * 1000,
                'Power_Uncert_mW_k2_95CI': (abs(mean_p_mw) * rel_u_power) * K_FACTOR,
                'Power_Rel_Uncert_pct': rel_u_power * 100
            },
            'glitches': glitch_log
        }
    except Exception as e:
        print(f"Error {file_name}: {e}"); return None

def main():
    print("-" * 50 + "\nRUNNING MASTER PROCESSOR: 7.5x ABOVE/BELOW LOGIC\n" + "-" * 50)
    if not os.path.exists(SUMMARY_DIR): os.makedirs(SUMMARY_DIR)
    
    tasks = []
    for p in PROTOCOLS:
        for e in EXPERIMENTS:
            folder = os.path.join(BASE_PATH, p, e)
            if os.path.exists(folder):
                for f in [f for f in os.listdir(folder) if f.endswith('.csv')]:
                    tasks.append((p, e, f, os.path.join(folder, f)))

    summary_results, all_glitches = [], []
    with concurrent.futures.ProcessPoolExecutor() as executor:
        for res in executor.map(process_single_file, tasks):
            if res:
                summary_results.append(res['stats'])
                all_glitches.extend(res['glitches'])

    if summary_results:
        pd.DataFrame(summary_results).to_csv(SUMMARY_PATH, index=False)
        print(f"✅ Success! Comprehensive summary saved to: {SUMMARY_PATH}")
        print(f"📊 Total true glitches detected (7.5x vs neighbors): {len(all_glitches)}")

if __name__ == "__main__":
    main()