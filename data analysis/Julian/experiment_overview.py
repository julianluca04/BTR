import os
import pandas as pd
import numpy as np
import re

# --- Path ---
BASE_PATH = '/Users/foml/Library/Mobile Documents/com~apple~CloudDocs/important/coding/MSP/year_3/Thesis work/BTR_results/data'

def analyze_run_stats(file_path):
    """Calculates stats strictly using rows found after the # METER header."""
    try:
        payload_bytes = 0
        duration = 0
        sample_count = 0
        
        with open(file_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
            
        res_idx = -1
        met_idx = -1
        for i, line in enumerate(lines):
            if "# RESULTS" in line: res_idx = i
            if "# METER" in line: met_idx = i
            
        if res_idx != -1:
            search_limit = met_idx if met_idx != -1 else len(lines)
            for i in range(search_limit - 1, res_idx, -1):
                match = re.search(r'tx_(\d+)', lines[i])
                if match:
                    payload_bytes = int(match.group(1))
                    break

        if met_idx != -1:
            data_lines = [l for l in lines[met_idx + 2:] if l.strip() and ',' in l]
            sample_count = len(data_lines)
            
            if sample_count >= 1:
                start_ts_str = data_lines[0].split(',')[0].strip()
                end_ts_str = data_lines[-1].split(',')[1].strip()

                start_dt = pd.to_datetime(start_ts_str, format='%Y-%m-%dT%H:%M:%S.%f', errors='coerce')
                end_dt = pd.to_datetime(end_ts_str, format='%Y-%m-%dT%H:%M:%S.%f', errors='coerce')
                
                if start_dt and end_dt:
                    duration = (end_dt - start_dt).total_seconds()

        return {"Duration": duration, "Payload_B": payload_bytes, "Samples": sample_count}
    except Exception:
        return None

def main():
    stats = []
    if not os.path.exists(BASE_PATH):
        print(f"ERROR: Path does not exist:\n{BASE_PATH}")
        return

    print(f"Auditing results in: {BASE_PATH}...")
    
    for root, dirs, files in os.walk(BASE_PATH):
        rel_path = os.path.relpath(root, BASE_PATH)
        path_parts = rel_path.split(os.sep)
        if rel_path == "." or len(path_parts) < 2: continue
            
        protocol, experiment = path_parts[0], path_parts[1]

        for file in files:
            if file.endswith(".csv") and not file.startswith("."):
                res = analyze_run_stats(os.path.join(root, file))
                if res:
                    res.update({"Protocol": protocol, "Experiment": experiment})
                    stats.append(res)

    if not stats: return

    df = pd.DataFrame(stats)
    summary = df.groupby(['Protocol', 'Experiment']).agg(
        Avg_Dur=('Duration', 'mean'),
        Max_Payload_B=('Payload_B', 'max'),
        Avg_Samples=('Samples', 'mean'),
        Total_Samples=('Samples', 'sum'),
        Runs=('Duration', 'count')
    ).reset_index()

    print("\n" + "="*115)
    print(f"{'EXPERIMENT AUDIT: DATA POINT RESOLUTION & TOTALS (AFTER # METER)':^115}")
    print("="*115)
    print(summary.to_string(index=False))
    print("="*115)

if __name__ == "__main__":
    main()