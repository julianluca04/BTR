import os
import pandas as pd
import numpy as np
import concurrent.futures
import math
import warnings

# --- Constants & Instrument Calibration ---
R_MEAN = 1.134584
V_OFFSET = -0.002182e-3
U_OFFSET = 0.001699e-3 
HMC8012_READING_PCT = 0.00015  
HMC8012_RANGE_PCT = 0.00002    
HMC8012_RANGE_V = 0.400        
RECT_TO_GAUSSIAN = math.sqrt(3)

# Thresholds and limits are kept for structural compatibility but unused in shifting
V_DELTA_THRESHOLD = 0.001  
HUNT_LIMIT = 3000          

BASE_PATH = "/Users/foml/coding/MSP/year_3/BTR/visualize/data"

RESULTS_HEADER = "Index, Phase, Mean_V, Min_V, Max_V, Spread_V, Std_V, Uncertainty_V, Neff, Elapsed_ms, Sample_Count, True_Lag_ms\n"
METER_HEADER = "Timestamp, V_Shunt, Phase, Current\n"

warnings.filterwarnings("ignore", category=RuntimeWarning)

def effective_sample_size(s):
    n = len(s)
    if n < 3 or s.std() == 0: return float(n)
    try:
        rho = s.autocorr(lag=1)
        if np.isnan(rho) or abs(rho) >= 1: return float(n)
        return max(1.0, n * (1 - rho) / (1 + rho))
    except: return float(n)

def compute_comprehensive_uncertainty(s):
    n, neff, mean_v, std_v = len(s), effective_sample_size(s), s.mean(), s.std()
    u_A = std_v / math.sqrt(neff) if neff > 0 else 0
    u_B_reading = (HMC8012_READING_PCT * abs(mean_v)) / RECT_TO_GAUSSIAN
    u_B_range = (HMC8012_RANGE_PCT * HMC8012_RANGE_V) / RECT_TO_GAUSSIAN
    u_combined = math.sqrt(u_A**2 + u_B_reading**2 + u_B_range**2 + U_OFFSET**2)
    return u_combined, neff

def refine_phase_boundaries(df):
    """
    MODIFIED: Shifting logic removed. 
    Returns the dataframe and an empty lag dictionary to maintain original phase timing.
    """
    lags_ms = {} 
    # Logic that used to modify df['phase'] based on V_DELTA_THRESHOLD has been deleted.
    return df, lags_ms

def process_single_file(path):
    name = os.path.basename(path)
    try:
        with open(path, "r", encoding="utf-8") as f:
            lines = f.readlines()

        m_idx = next((i for i, l in enumerate(lines) if "# METER" in l), -1)
        if m_idx == -1: return f"Skipped (No # METER): {name}"

        valid_data = []
        for row in [l.strip().split(',') for l in lines[m_idx + 1:] if l.strip()]:
            if len(row) >= 3 and '-' in row[0] and ':' in row[0]:
                try:
                    v = float(row[1])
                    v = v / 1000.0 if v > 1.0 else v 
                    valid_data.append([pd.to_datetime(row[0], format='mixed'), v, row[2].strip()])
                except: continue

        if not valid_data: return f"No valid data: {name}"

        df = pd.DataFrame(valid_data, columns=['ts', 'v', 'phase'])
        
        # Call the modified refiner (does not shift)
        df, lag_dict = refine_phase_boundaries(df)
        
        df['block'] = (df['phase'] != df['phase'].shift()).cumsum()
        res_lines = []
        for i, (block_id, g) in enumerate(df.groupby('block', sort=False)):
            p_name = g['phase'].iloc[0]
            v_s = g['v']
            u, neff = compute_comprehensive_uncertainty(v_s) 
            ms = (g['ts'].max() - g['ts'].min()).total_seconds() * 1000
            
            # true_lag will now always be 0.0 since shifting is disabled
            true_lag = lag_dict.get(g.index[0], 0.0)
            
            res_lines.append(f"{i}, {p_name}, {v_s.mean():.9f}, {v_s.min():.9f}, {v_s.max():.9f}, "
                             f"{v_s.max()-v_s.min():.9f}, {v_s.std():.9f}, {u:.9f}, {neff:.2f}, {ms:.3f}, {len(v_s)}, {true_lag:.4f}\n")

        with open(path, "w", encoding="utf-8") as f:
            f.write("# RESULTS\n" + RESULTS_HEADER)
            f.writelines(res_lines)
            f.write("# METER\n" + METER_HEADER)
            for _, r in df.iterrows():
                curr = (r['v'] - V_OFFSET) / R_MEAN
                ts_str = r['ts'].strftime('%Y-%m-%dT%H:%M:%S.%f')
                f.write(f"{ts_str},{r['v']:.9f},{r['phase']},{curr:.9f}\n")
            
        return f"Cleaned & Processed (No Shifting): {name}"
    except Exception as e: return f"Error {name}: {str(e)}"

def main():
    tasks = []
    for root, _, files in os.walk(BASE_PATH):
        for f in files:
            if f.endswith(".csv"):
                tasks.append(os.path.join(root, f))
    
    print(f"Applying Logic to {len(tasks)} files (Phase Shifting Disabled)...")
    with concurrent.futures.ProcessPoolExecutor() as ex:
        reports = list(ex.map(process_single_file, tasks))
    
    for r in reports: print(r)

if __name__ == "__main__":
    main()