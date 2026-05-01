import os
import pandas as pd
import concurrent.futures
from datetime import datetime

# --- Configuration ---
R_MEAN = 1.134584
V_OFFSET = -0.002182e-3
BASE_PATH = "/Users/foml/coding/MSP/year_3/BTR/visualize/data"
PROTOCOLS = ["wifi", "BLE"]
EXPERIMENTS = ["chunk", "byte", "all"]

# Define our headers
RESULTS_HEADER = "Index, Phase, Mean_V, Min_V, Max_V, Spread_V, Std_V, Elapsed_ms\n"
METER_HEADER = "Timestamp, V_Shunt, Phase, Current\n"

def process_single_file(task):
    protocol, exp, name, path = task
    try:
        with open(path, "r", encoding="utf-8") as f:
            lines = f.readlines()

        meter_idx = next((i for i, l in enumerate(lines) if "# METER" in l), -1)
        if meter_idx == -1: return f"Skipped: {name}"

        # 1. Clean Metadata (Scrub # META block)
        meta_raw = lines[:meter_idx]
        cleaned_meta, in_meta_block = [], False
        for line in meta_raw:
            stripped = line.strip()
            if stripped.startswith("# META"):
                in_meta_block = True
                continue 
            if in_meta_block:
                if stripped.startswith("#"):
                    in_meta_block = False
                    cleaned_meta.append(line)
                continue 
            cleaned_meta.append(line)

        # 2. Filter Data Rows (Bottom-Up FALSE Gate)
        data_rows_raw = [l.strip().split(',') for l in lines[meter_idx + 1:] if l.strip()]
        filtered_rows, keep_gate = [], True 
        for row in reversed(data_rows_raw):
            if len(row) >= 8:
                flag = row[7].strip().upper()
                if flag == "FALSE": keep_gate = False
                elif flag == "TRUE": keep_gate = True
            if keep_gate: filtered_rows.append(row)
        filtered_rows.reverse()

        # 3. Separation & State Processing
        overview_rows, valid_data = [], []
        for row in filtered_rows:
            if len(row) >= 8 and row[7].strip():
                overview_rows.append(",".join(row) + "\n")
                continue
            if len(row) < 3 or not row[2].strip():
                continue 

            try:
                v_val = float(row[1])
                v_fixed = v_val / 1000.0 if v_val > 1.0 else v_val
                row[1] = f"{v_fixed:.9f}"
                current = (v_fixed - V_OFFSET) / R_MEAN
                if len(row) > 3: row[3] = f"{current:.9f}"
                else: row.append(f"{current:.9f}")
                valid_data.append(row)
            except (ValueError, IndexError):
                pass

        # 4. Generate # RESULTS (Sequential Blocks)
        res_rows = []
        if valid_data:
            df = pd.DataFrame(valid_data)
            df[0] = pd.to_datetime(df[0]) 
            df[1] = df[1].astype(float)   
            df[2] = df[2].astype(str)     
            df['block'] = (df[2] != df[2].shift()).cumsum()
            
            for i, ((block_id, phase_name), group) in enumerate(df.groupby(['block', 2], sort=False)):
                v_group = group[1]
                elapsed_ms = (group[0].max() - group[0].min()).total_seconds() * 1000
                
                res_line = (f"{i}, {phase_name}, {v_group.mean():.9f}, {v_group.min():.9f}, "
                            f"{v_group.max():.9f}, {v_group.max()-v_group.min():.9f}, "
                            f"{v_group.std():.9f}, {elapsed_ms:.3f}\n")
                res_rows.append(res_line)

        # 5. Final Assembly
        with open(path, "w", encoding="utf-8") as f:
            f.writelines(cleaned_meta)
            if overview_rows:
                f.write("# OVERVIEW\n")
                f.writelines(overview_rows)
            if res_rows:
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

    print(f"Executing on {len(tasks)} files...")
    with concurrent.futures.ProcessPoolExecutor() as executor:
        results = list(executor.map(process_single_file, tasks))
    print("Success. Headers and sequential results integrated.")

if __name__ == "__main__":
    main()