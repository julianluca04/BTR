import os
import pandas as pd
import numpy as np
import concurrent.futures
import math
import warnings

# --- Physical & Instrument Constants ---
R_MEAN = 1.134584
V_OFFSET = -0.002182e-3
U_OFFSET = 0.001699e-3 
HMC8012_READING_PCT = 0.00015
HMC8012_RANGE_PCT = 0.00002
HMC8012_RANGE_V = 0.400
RECT_TO_GAUSSIAN = math.sqrt(3)

BASE_PATH = "/Users/foml/coding/MSP/year_3/BTR/visualize/data"
PROTOCOLS = ["wifi", "BLE"]
EXPERIMENTS = ["chunk", "byte", "all"]

RESULTS_HEADER = "Index, Phase, Mean_V, Min_V, Max_V, Spread_V, Std_V, Uncertainty_V, Neff, Elapsed_ms, Sample_Count\n"
METER_HEADER = "Timestamp, V_Shunt, Phase, Current\n"

# SUPPRESS NUMPY DIVIDE WARNINGS
warnings.filterwarnings("ignore", category=RuntimeWarning, message="invalid value encountered in divide")

def effective_sample_size(s):
    n = len(s)
    if n < 3: return float(n)
    
    # Check for zero variance to avoid mathematical singularity
    if s.std() == 0:
        return float(n)
        
    try:
        rho = s.autocorr(lag=1)
        if np.isnan(rho) or abs(rho) >= 1: 
            return float(n)
        neff = n * (1 - rho) / (1 + rho)
        return max(1.0, neff)
    except:
        return float(n)

def compute_comprehensive_uncertainty(s):
    n = len(s)
    neff = effective_sample_size(s)
    
    # Type A: Repeatability
    uA = s.std() / math.sqrt(neff) if neff > 0 else 0
    
    # Type B: Instrument Accuracy
    uB = math.sqrt(
        ((HMC8012_READING_PCT * abs(s.mean())) / RECT_TO_GAUSSIAN) ** 2 +
        ((HMC8012_RANGE_PCT * HMC8012_RANGE_V) / RECT_TO_GAUSSIAN) ** 2
    )
    
    u_combined = math.sqrt(uA**2 + uB**2 + U_OFFSET**2)
    return u_combined, neff

def process_single_file(task):
    protocol, exp, name, path = task
    try:
        with open(path, "r", encoding="utf-8") as f:
            lines = f.readlines()

        # Identify existing sections
        meter_idx = next((i for i, l in enumerate(lines) if "# METER" in l), -1)
        results_idx = next((i for i, l in enumerate(lines) if "# RESULTS" in l), -1)
        
        if meter_idx == -1: return f"Skipped: {name}"

        # 1. Capture Header/Metadata (Wipe out old # RESULTS if it existed)
        # We take everything before the earliest occurrence of # RESULTS or # METER
        boundary = min([i for i in [results_idx, meter_idx] if i != -1])
        header_raw = lines[:boundary]
        
        # Scrub # META block
        cleaned_header, in_meta_block = [], False
        for line in header_raw:
            stripped = line.strip()
            if stripped.startswith("# META"):
                in_meta_block = True
                continue 
            if in_meta_block:
                if stripped.startswith("#"):
                    in_meta_block = False
                    cleaned_header.append(line)
                continue 
            cleaned_header.append(line)

        # 2. Filter Data (Bottom-Up FALSE Gate)
        data_rows_raw = [l.strip().split(',') for l in lines[meter_idx + 1:] if l.strip()]
        filtered_rows, keep_gate = [], True 
        for row in reversed(data_rows_raw):
            if len(row) >= 8:
                flag = row[7].strip().upper()
                if flag == "FALSE": keep_gate = False
                elif flag == "TRUE": keep_gate = True
            if keep_gate: filtered_rows.append(row)
        filtered_rows.reverse()

        # 3. Unit Normalization
        overview_rows, valid_data = [], []
        for row in filtered_rows:
            if len(row) >= 8 and row[7].strip():
                overview_rows.append(",".join(row) + "\n")
                continue
            if len(row) < 3 or not row[2].strip(): continue 

            try:
                v_val = float(row[1])
                v_fixed = v_val / 1000.0 if v_val > 1.0 else v_val
                row[1] = f"{v_fixed:.9f}"
                current = (v_fixed - V_OFFSET) / R_MEAN
                if len(row) > 3: row[3] = f"{current:.9f}"
                else: row.append(f"{current:.9f}")
                valid_data.append(row)
            except: pass

        # 4. Generate # RESULTS
        res_rows = []
        if valid_data:
            df = pd.DataFrame(valid_data)
            df[0] = pd.to_datetime(df[0]) 
            df[1] = df[1].astype(float)   
            df[2] = df[2].astype(str)     
            df['block'] = (df[2] != df[2].shift()).cumsum()
            
            for i, ((block_id, phase_name), group) in enumerate(df.groupby(['block', 2], sort=False)):
                v_series = group[1]
                u_val, neff = compute_comprehensive_uncertainty(v_series)
                elapsed_ms = (group[0].max() - group[0].min()).total_seconds() * 1000
                
                res_line = (f"{i}, {phase_name}, {v_series.mean():.9f}, {v_series.min():.9f}, "
                            f"{v_series.max():.9f}, {v_series.max()-v_series.min():.9f}, "
                            f"{v_series.std():.9f}, {u_val:.9f}, {neff:.2f}, {elapsed_ms:.3f}, {len(v_series)}\n")
                res_rows.append(res_line)

        # 5. Save with Clean Structure (Section Replacement)
        with open(path, "w", encoding="utf-8") as f:
            f.writelines(cleaned_header)
            if overview_rows:
                f.write("# OVERVIEW\n")
                f.writelines(overview_rows)
            f.write("# RESULTS\n")
            f.write(RESULTS_HEADER)
            f.writelines(res_rows)
            f.write("# METER\n")
            f.write(METER_HEADER)
            for row in valid_data:
                f.write(",".join(row) + "\n")

        return f"Processed: {name}"

    except Exception as e:
        return f"Error {name}: {e}"

def main():
    tasks = []
    for p in PROTOCOLS:
        for e in EXPERIMENTS:
            folder = os.path.join(BASE_PATH, p, e)
            if not os.path.exists(folder): continue
            for f in os.listdir(folder):
                if f.endswith(".csv"):
                    tasks.append((p, e, f, os.path.join(folder, f)))

    print(f"Executing Clean Replacement on {len(tasks)} files...")
    with concurrent.futures.ProcessPoolExecutor() as executor:
        results = list(executor.map(process_single_file, tasks))
    print("Done. Sections replaced and math warnings hidden.")

if __name__ == "__main__":
    main()