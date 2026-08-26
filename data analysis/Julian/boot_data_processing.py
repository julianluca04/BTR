import os
import pandas as pd
import numpy as np
import concurrent.futures
import math
import tempfile
import shutil
import re

# --- Paths ---
BOOT_DATA_PATH = '/Users/foml/coding/MSP/year_3/Thesis work/BTR_results/boot data'
PROTOCOLS = ["wifi", "ble", "lora"]

SHORT_CIRCUIT_PATH = '/Users/foml/coding/MSP/year_3/Thesis work/BTR_results/other/Setting_up_devices/multimeter testing/analyze_data/shortcircuit.csv'
RESISTANCE_PATH    = '/Users/foml/coding/MSP/year_3/Thesis work/BTR_results/other/Setting_up_devices/power & resistor testing/resistance_characterisation.csv'

# --- Calibration Constants ---
HMC8012_READING_PCT = 0.00015
HMC8012_RANGE_PCT   = 0.00002
HMC8012_RANGE_V     = 0.400
RECT_TO_GAUSSIAN    = math.sqrt(3)

# --- Standardized Headers (No Meta) ---
RESULTS_HEADER = "Index, Phase, Mean_V, Min_V, Max_V, Spread_V, Std_V, Uncertainty_V, Neff, Elapsed_ms, Unique_Sample_Count\n"
METER_HEADER   = "Timestamp_Start, Timestamp_End, V_Shunt, Phase, Current\n"

def load_calibration():
    mu_offset, sigma_noise, n_samples = 0.0, 0.0, 1
    try:
        with open(SHORT_CIRCUIT_PATH, "r") as f:
            for line in f:
                if "mu_offset_V" in line: mu_offset = float(line.split(",")[1])
                elif "sigma_noise_V" in line: sigma_noise = float(line.split(",")[1])
                elif "n_samples" in line: n_samples = int(line.split(",")[1])
    except:
        df = pd.read_csv(SHORT_CIRCUIT_PATH, comment="#", on_bad_lines='skip')
        mu_offset = df.iloc[:, 1].mean()
        sigma_noise = df.iloc[:, 1].std()
        n_samples = len(df)
    
    sigma_offset = sigma_noise / math.sqrt(n_samples)
    df_res = pd.read_csv(RESISTANCE_PATH, comment="#")
    r_mean = df_res.iloc[:, 0].mean()
    
    return {"v_offset": mu_offset, "sigma_offset": sigma_offset, "R_mean": r_mean}

def compute_uncertainty(s, sigma_offset):
    neff = len(s)
    if neff > 3:
        try:
            rho = s.autocorr(lag=1)
            if not np.isnan(rho) and abs(rho) < 1:
                neff = max(1.0, neff * (1 - rho) / (1 + rho))
        except: pass
    u_A = s.std() / math.sqrt(neff) if neff > 0 else 0.0
    u_B = math.sqrt(((HMC8012_READING_PCT * abs(s.mean())) / RECT_TO_GAUSSIAN)**2 + 
                    ((HMC8012_RANGE_PCT * HMC8012_RANGE_V) / RECT_TO_GAUSSIAN)**2)
    return math.sqrt(u_A**2 + u_B**2 + sigma_offset**2), neff

def process_boot_file(task):
    path, calib = task
    R_MEAN, V_OFFSET, sigma_offset = calib["R_mean"], calib["v_offset"], calib["sigma_offset"]
    fname = os.path.basename(path)

    try:
        with open(path, "r", encoding="utf-8") as f:
            lines = f.readlines()

        raw_rows = []
        for line in lines:
            clean = line.strip()
            if not clean or clean.startswith("#") or "timestamp" in clean.lower():
                continue

            parts = re.split(r'[,\s\t]+', clean)
            
            # Identify data columns
            if parts[0] == "METER" and len(parts) >= 3:
                raw_rows.append([parts[1], float(parts[2]), "BOOT"])
            elif len(parts) >= 2:
                if "T" in parts[0] or ":" in parts[0]:
                    try:
                        v_val = float(parts[1])
                        ph = parts[2] if len(parts) > 2 else "BOOT"
                        raw_rows.append([parts[0], v_val, ph])
                    except ValueError: continue

        if not raw_rows:
            return f"Skipped: {fname} (No data rows found)"

        # --- Consolidation & Hardware Offset Subtraction ---
        consolidated = []
        # Start with the first available row (no trimming)
        curr_s, curr_e, curr_v, curr_p = raw_rows[0][0], raw_rows[0][0], raw_rows[0][1], raw_rows[0][2]
        
        for i in range(1, len(raw_rows)):
            ts, v, p = raw_rows[i]
            if v == curr_v and p == curr_p:
                curr_e = ts
            else:
                # Calculate Current with offset subtraction
                curr_i = (curr_v - V_OFFSET) / R_MEAN
                consolidated.append([curr_s, curr_e, f"{curr_v:.9e}", curr_p, f"{curr_i:.9e}"])
                curr_s, curr_e, curr_v, curr_p = ts, ts, v, p
        
        # Final row
        curr_i = (curr_v - V_OFFSET) / R_MEAN
        consolidated.append([curr_s, curr_e, f"{curr_v:.9e}", curr_p, f"{curr_i:.9e}"])

        # --- Statistics ---
        df = pd.DataFrame(consolidated, columns=['s', 'e', 'v', 'p', 'i'])
        df['v'] = df['v'].astype(float)
        df['s_dt'] = pd.to_datetime(df['s'], format='ISO8601', errors='coerce')
        df['e_dt'] = pd.to_datetime(df['e'], format='ISO8601', errors='coerce')
        df['blk'] = (df['p'] != df['p'].shift()).cumsum()

        res_lines = []
        for idx, ((_, p_name), group) in enumerate(df.groupby(['blk', 'p'], sort=False)):
            v_s = group['v']
            u, neff = compute_uncertainty(v_s, sigma_offset)
            dur = (group['e_dt'].max() - group['s_dt'].min()).total_seconds() * 1000
            res_lines.append(f"{idx}, {p_name}, {v_s.mean():.9e}, {v_s.min():.9e}, {v_s.max():.9e}, "
                            f"{v_s.max()-v_s.min():.9e}, {v_s.std():.9e}, {u:.9e}, {neff:.2f}, {dur:.3f}, {len(v_s)}\n")

        # --- Atomic Write (Full Data) ---
        fd, t_path = tempfile.mkstemp(dir=os.path.dirname(path), text=True)
        with os.fdopen(fd, 'w', encoding="utf-8") as f:
            f.write("# RESULTS\n")
            f.write(RESULTS_HEADER)
            f.writelines(res_lines)
            f.write("# METER\n")
            f.write(METER_HEADER)
            for row in consolidated:
                f.write(",".join(row) + "\n")
        
        shutil.move(t_path, path)
        return f"Standardized (Full Duration): {fname}"

    except Exception as e:
        return f"Error {fname}: {str(e)}"

def main():
    print("Starting Full-Duration Processing (Consolidated + Offset Correction)...")
    calib = load_calibration()
    
    tasks = []
    for proto in PROTOCOLS:
        folder = os.path.join(BOOT_DATA_PATH, proto)
        if os.path.isdir(folder):
            for f in sorted(os.listdir(folder)):
                if f.endswith(".csv"):
                    tasks.append((os.path.join(folder, f), calib))

    print(f"Processing {len(tasks)} files...")
    with concurrent.futures.ProcessPoolExecutor() as executor:
        for result in executor.map(process_boot_file, tasks):
            print(result)

if __name__ == "__main__":
    main()