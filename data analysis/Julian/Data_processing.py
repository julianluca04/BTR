import os
import pandas as pd
import numpy as np
import concurrent.futures
import math
import warnings
import tempfile
import shutil

# --- Paths ---
BASE_PATH = '/Users/foml/coding/MSP/year_3/Thesis work/BTR_results/data'
PROTOCOLS = ["wifi", "BLE", "lora"]
EXPERIMENTS = ["chunk", "byte", "all"]

SHORT_CIRCUIT_PATH = '/Users/foml/coding/MSP/year_3/Thesis work/BTR_results/other/Setting_up_devices/multimeter testing/analyze_data/shortcircuit.csv'
RESISTANCE_PATH    = '/Users/foml/coding/MSP/year_3/Thesis work/BTR_results/other/Setting_up_devices/power & resistor testing/resistance_characterisation.csv'
VOLTAGE_PATH       = '/Users/foml/coding/MSP/year_3/Thesis work/BTR_results/other/Setting_up_devices/power & resistor testing/voltage_characterisation.csv'
SUMMARY_OUT        = '/Users/foml/coding/MSP/year_3/Thesis work/BTR_results/summary_energy_comprehensive.csv'

# --- HMC8012 DC spec, 5.5-digit mode ---
HMC8012_READING_PCT = 0.00015   # 0.015% of reading
HMC8012_RANGE_PCT   = 0.00002   # 0.002% of range
HMC8012_RANGE_V     = 0.400     # 400 mV range
RECT_TO_GAUSSIAN    = math.sqrt(3)

# --- Headers ---
RESULTS_HEADER = "Index, Phase, Mean_V, Min_V, Max_V, Spread_V, Std_V, Uncertainty_V, Neff, Elapsed_ms, Unique_Sample_Count\n"
METER_HEADER   = "Timestamp_Start, Timestamp_End, V_Shunt, Phase, Current\n"

SUMMARY_HEADER = (
    "Protocol,Experiment,Run,Unique_Samples_N,Samples_N_eff,"
    "Vshunt_Mean_V,Vshunt_Median_V,Vshunt_Std_V,Vshunt_Max_V,Vshunt_Min_V,"
    "Vshunt_Combined_Uncert_V,"
    "Current_Mean_mA,Current_Median_mA,Current_Std_mA,Current_Max_mA,Current_Min_mA,"
    "Power_Mean_mW,Power_Std_mW,Power_Rel_Uncert_pct"
)

warnings.filterwarnings("ignore", category=RuntimeWarning, message="invalid value encountered in divide")

# --- Characterisation loaders -------------------------------------------------

def load_short_circuit(path):
    mu_offset, sigma_noise, n_samples = None, None, None
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                s = line.strip()
                if s.startswith("mu_offset_V"): mu_offset = float(s.split(",", 1)[1])
                elif s.startswith("sigma_noise_V"): sigma_noise = float(s.split(",", 1)[1])
                elif s.startswith("n_samples"): n_samples = int(s.split(",", 1)[1])
    except FileNotFoundError: pass

    if mu_offset is None or sigma_noise is None or n_samples is None:
        df = pd.read_csv(path, comment="#", skip_blank_lines=True)
        col = next(c for c in df.columns if "shunt" in c.lower() or "v_" in c.lower())
        mu_offset, sigma_noise, n_samples = float(df[col].mean()), float(df[col].std(ddof=1)), int(len(df))

    sigma_offset = sigma_noise / math.sqrt(n_samples) if n_samples > 0 else sigma_noise
    return mu_offset, sigma_offset

def load_characterisation(path, keyword):
    rows = []
    with open(path, "r", encoding="utf-8") as f:
        header = None
        for line in f:
            s = line.strip()
            if not s or s.startswith("#"): continue
            parts = [p.strip() for p in s.split(",")]
            if header is None: header = parts; continue
            if len(parts) != len(header): continue
            rows.append(parts)
    df = pd.DataFrame(rows, columns=header)
    col = next(c for c in df.columns if keyword.lower() in c.lower())
    vals = pd.to_numeric(df[col], errors="coerce").dropna()
    return float(vals.mean()), float(vals.std(ddof=1)), int(len(vals))

# --- Statistics ---------------------------------------------------------------

def effective_sample_size(s):
    n = len(s)
    if n < 3: return float(n)
    if s.std() == 0: return 1.0
    try:
        rho = s.autocorr(lag=1)
        if np.isnan(rho) or abs(rho) >= 1: return 1.0
        return max(1.0, n * (1 - rho) / (1 + rho))
    except Exception: return float(n)

def compute_comprehensive_uncertainty(s, sigma_offset):
    n = len(s)
    neff = effective_sample_size(s)
    mean_v = s.mean()
    std_v  = s.std(ddof=1) if n > 1 else 0.0
    u_A         = std_v / math.sqrt(neff) if neff > 0 else 0.0
    u_B_reading = (HMC8012_READING_PCT * abs(mean_v)) / RECT_TO_GAUSSIAN
    u_B_range   = (HMC8012_RANGE_PCT  * HMC8012_RANGE_V) / RECT_TO_GAUSSIAN
    u_combined  = math.sqrt(u_A**2 + u_B_reading**2 + u_B_range**2 + sigma_offset**2)
    return u_combined, neff

# --- Per-file processing (In-place rewrite with consolidation) ---------------

def process_single_file(task):
    protocol, exp, name, path, calib = task
    R_MEAN, V_OFFSET, sigma_offset = calib["R_mean"], calib["v_offset"], calib["sigma_offset"]

    try:
        with open(path, "r", encoding="utf-8") as f:
            lines = f.readlines()

        m_idx = next((i for i, l in enumerate(lines) if "# METER" in l), -1)
        r_idx = next((i for i, l in enumerate(lines) if "# RESULTS" in l), -1)
        if m_idx == -1: return f"Skipped (No METER): {name}"

        boundary = min([i for i in [r_idx, m_idx] if i != -1])
        header_raw = lines[:boundary]
        
        # Clean header metadata
        cleaned_header, in_meta = [], False
        for line in header_raw:
            stripped = line.strip()
            if stripped.startswith("# META"): in_meta = True; continue
            if in_meta:
                if stripped.startswith("#"): in_meta = False; cleaned_header.append(line)
                continue
            cleaned_header.append(line)

        data_rows_raw = [l.strip().split(',') for l in lines[m_idx + 1:] if l.strip()]

        # 1. Bottom-up filter (TRUE flag)
        cut_index = None
        for i in range(len(data_rows_raw) - 1, -1, -1):
            if len(data_rows_raw[i]) >= 8 and data_rows_raw[i][7].strip().upper() == "TRUE":
                cut_index = i; break
        filtered = data_rows_raw[:cut_index + 1] if cut_index is not None else data_rows_raw

        # 2. Protocol Trimming (Trailing Idles)
        if protocol.lower() != "lora":
            while filtered and len(filtered[-1]) >= 3 and filtered[-1][2].strip().lower() == "idle":
                filtered.pop()

        # 3. LoRa Logic (Rename trailing idle / Byte experiment cut)
        if protocol.lower() == "lora" and filtered:
            last_tx_idx = next((i for i in range(len(filtered)-1, -1, -1) if filtered[i][2].strip().lower() != "idle"), None)
            if last_tx_idx is not None:
                last_tx_phase = filtered[last_tx_idx][2].strip()
                for j in range(last_tx_idx + 1, len(filtered)):
                    if filtered[j][2].strip().lower() == "idle": filtered[j][2] = last_tx_phase
            
            if exp.strip().lower() == "byte":
                tx_32_idx = next((i for i, r in enumerate(filtered) if r[2].strip().lower() == "tx_32768"), None)
                if tx_32_idx is not None:
                    s_idx = tx_32_idx
                    while s_idx > 0 and filtered[s_idx-1][2].strip().lower() == "idle": s_idx -= 1
                    filtered = filtered[:s_idx]

        # 4. Consolidate Repeated Readings
        consolidated, overview_rows = [], []
        if filtered:
            # Pre-process numeric values
            valid_prep = []
            for r in filtered:
                if len(r) >= 8 and r[7].strip(): overview_rows.append(",".join(r) + "\n"); continue
                try:
                    v = float(r[1])
                    v_fixed = v / 1000.0 if abs(v) > 1.0 else v
                    valid_prep.append([r[0], v_fixed, r[2].strip()])
                except: continue

            if valid_prep:
                c_start, c_end, c_v, c_p = valid_prep[0][0], valid_prep[0][0], valid_prep[0][1], valid_prep[0][2]
                for i in range(1, len(valid_prep)):
                    r_ts, r_v, r_p = valid_prep[i]
                    if r_v == c_v and r_p == c_p:
                        c_end = r_ts
                    else:
                        curr_ma = (c_v - V_OFFSET) / R_MEAN * 1000.0
                        consolidated.append([c_start, c_end, f"{c_v:.9f}", c_p, f"{curr_ma/1000.0:.9f}"])
                        c_start, c_end, c_v, c_p = r_ts, r_ts, r_v, r_p
                consolidated.append([c_start, c_end, f"{c_v:.9f}", c_p, f"{(c_v - V_OFFSET) / R_MEAN:.9f}"])

        # 5. Generate Phase Results (from unique samples)
        res_rows = []
        if consolidated:
            df = pd.DataFrame(consolidated, columns=['s', 'e', 'v', 'p', 'i'])
            df['v'] = df['v'].astype(float)
            df['s_dt'] = pd.to_datetime(df['s'], format='%Y-%m-%dT%H:%M:%S.%f')
            df['e_dt'] = pd.to_datetime(df['e'], format='%Y-%m-%dT%H:%M:%S.%f')
            df['blk'] = (df['p'] != df['p'].shift()).cumsum()

            for i, ((_, p_name), group) in enumerate(df.groupby(['blk', 'p'], sort=False)):
                v_s = group['v']
                u, neff = compute_comprehensive_uncertainty(v_s, sigma_offset)
                elap = (group['e_dt'].max() - group['s_dt'].min()).total_seconds() * 1000
                res_rows.append(f"{i}, {p_name}, {v_s.mean():.9f}, {v_s.min():.9f}, {v_s.max():.9f}, "
                               f"{v_s.max()-v_s.min():.9f}, {v_s.std():.9f}, {u:.9f}, {neff:.2f}, {elap:.3f}, {len(v_s)}\n")

        fd, t_path = tempfile.mkstemp(dir=os.path.dirname(path), text=True)
        with os.fdopen(fd, 'w', encoding="utf-8") as f:
            f.writelines(cleaned_header)
            if overview_rows: f.write("# OVERVIEW\n"); f.writelines(overview_rows)
            f.write("# RESULTS\n"); f.write(RESULTS_HEADER); f.writelines(res_rows)
            f.write("# METER\n"); f.write(METER_HEADER)
            for r in consolidated: f.write(",".join(r) + "\n")
        shutil.move(t_path, path)
        return f"Processed (Unique N={len(consolidated)}): {name}"
    except Exception as e: return f"Error {name}: {e}"

# --- Summaries ----------------------------------------------------------------

def read_consolidated_meter(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            lines = f.readlines()
        m_idx = next((i for i, l in enumerate(lines) if "# METER" in l), -1)
        if m_idx == -1: return None
        data = [l.strip().split(',') for l in lines[m_idx + 2:] if l.strip()]
        df = pd.DataFrame(data, columns=['s', 'e', 'v_shunt', 'phase', 'i'])
        df[['v_shunt', 'i']] = df[['v_shunt', 'i']].astype(float)
        df['s'] = pd.to_datetime(df['s'], format='%Y-%m-%dT%H:%M:%S.%f')
        df['e'] = pd.to_datetime(df['e'], format='%Y-%m-%dT%H:%M:%S.%f')
        return df
    except: return None

def process_run(task):
    protocol, experiment, fname, path, calib = task
    df = read_consolidated_meter(path)
    if df is None or df.empty: return None, f"Skipped: {fname}"
    
    v = df['v_shunt']
    u_v, n_eff = compute_comprehensive_uncertainty(v, calib["sigma_offset"])
    R, Vs = calib["R_mean"], calib["v_supply"]
    
    i_mA = ((v - calib["v_offset"]) / R) * 1000.0
    p_mW = i_mA * Vs

    # Uncertainty propagation
    rel_v = u_v / abs(v.mean() - calib["v_offset"]) if abs(v.mean() - calib["v_offset"]) > 0 else 0
    rel_p = math.sqrt(rel_v**2 + (calib["R_std"]/R)**2 + (calib["v_supply_std"]/Vs)**2)

    row = (f"{protocol},{experiment},{fname},{len(v)},{n_eff:.6f},"
           f"{v.mean():.10f},{v.median():.10f},{v.std():.10f},{v.max():.10f},{v.min():.10f},{u_v:.10f},"
           f"{i_mA.mean():.10f},{i_mA.median():.10f},{i_mA.std():.10f},{i_mA.max():.10f},{i_mA.min():.10f},"
           f"{p_mW.mean():.10f},{p_mW.std():.10f},{rel_p*100:.10f}")
    return row, f"OK: {fname}"

def run_summary(calib):
    print("\nBuilding summary files...")
    tasks = gather_files(calib)
    
    # 1. Calibration Constants Summary
    c_out = SUMMARY_OUT.replace("summary_energy_comprehensive.csv", "calibration_constants_summary.csv")
    with open(c_out, "w") as f:
        f.write("Metric,Mean,Std,Uncertainty\n")
        f.write(f"Resistance,{calib['R_mean']:.6f},{calib['R_std']:.6f},{calib['R_std']:.6f}\n")
        f.write(f"Voltage,{calib['v_supply']:.6f},{calib['v_supply_std']:.6f},{calib['v_supply_std']:.6f}\n")
        f.write(f"Offset,{calib['v_offset']:.10f},0,{calib['sigma_offset']:.10f}\n")

    # 2. Run Summary
    run_rows = []
    with concurrent.futures.ProcessPoolExecutor() as ex:
        for row, msg in ex.map(process_run, tasks):
            if row: run_rows.append(row)
    
    with open(SUMMARY_OUT, "w") as f:
        f.write(SUMMARY_HEADER + "\n"); f.write("\n".join(run_rows) + "\n")

    # 3. Per-Phase Summary (including TX+IDLE hybrids)
    p_out = SUMMARY_OUT.replace("summary_energy_comprehensive.csv", "summary_per_phase.csv")
    p_rows = []
    p_header = "Protocol,Experiment,Run,Phase,Samples_N,Samples_N_eff,Elapsed_ms,Vshunt_Mean_V,Current_Mean_mA,Power_Mean_mW"
    
    for (proto, exp, fname, path, _) in tasks:
        df = read_consolidated_meter(path)
        if df is None: continue
        df['blk'] = (df['phase'] != df['phase'].shift()).cumsum()
        groups = list(df.groupby(['blk', 'phase'], sort=False))

        for i, ((_, p_name), g) in enumerate(groups):
            v = g['v_shunt']
            elap = (g['e'].max() - g['s'].min()).total_seconds() * 1000
            i_m = ((v.mean() - calib["v_offset"]) / calib["R_mean"]) * 1000.0
            p_rows.append(f"{proto},{exp},{fname},{p_name},{len(v)},{effective_sample_size(v):.2f},{elap:.3f},{v.mean():.9f},{i_m:.9f},{i_m*calib['v_supply']:.9f}")

            # Hybrid TX+IDLE logic
            if i > 0 and "tx" in groups[i-1][0][1].lower() and "idle" in p_name.lower():
                comb = pd.concat([groups[i-1][1], g])
                v_c = comb['v_shunt']
                el_c = (comb['e'].max() - comb['s'].min()).total_seconds() * 1000
                i_c = ((v_c.mean() - calib["v_offset"]) / calib["R_mean"]) * 1000.0
                p_rows.append(f"{proto},{exp},{fname},{groups[i-1][0][1]}+idle,{len(v_c)},{effective_sample_size(v_c):.2f},{el_c:.3f},{v_c.mean():.9f},{i_c:.9f},{i_c*calib['v_supply']:.9f}")

    with open(p_out, "w") as f:
        f.write(p_header + "\n"); f.write("\n".join(p_rows) + "\n")

# --- Main Logic ---

def load_calibration():
    v_off, s_off = load_short_circuit(SHORT_CIRCUIT_PATH)
    r_m, r_s, _ = load_characterisation(RESISTANCE_PATH, "Resistance")
    v_s, v_ss, _ = load_characterisation(VOLTAGE_PATH, "Voltage")
    return {"v_offset": v_off, "sigma_offset": s_off, "R_mean": r_m, "R_std": r_s, "v_supply": v_s, "v_supply_std": v_ss}

def gather_files(calib):
    t = []
    for p in PROTOCOLS:
        for e in EXPERIMENTS:
            folder = os.path.join(BASE_PATH, p, e)
            if os.path.isdir(folder):
                for f in sorted(os.listdir(folder)):
                    if f.endswith(".csv"): t.append((p, e, f, os.path.join(folder, f), calib))
    return t

def main():
    calib = load_calibration()
    tasks = gather_files(calib)
    print(f"Updating {len(tasks)} files with unique-sample consolidation...")
    with concurrent.futures.ProcessPoolExecutor() as ex:
        for res in ex.map(process_single_file, tasks): print(res)
    run_summary(calib)
    print("\nDone.")

if __name__ == "__main__":
    main()