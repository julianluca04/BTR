import os
import pandas as pd
import numpy as np
import re
from io import StringIO
from tqdm import tqdm

# --- Configuration ---
BASE_PATH = r'/Users/foml/Library/Mobile Documents/com~apple~CloudDocs/important/coding/MSP/year_3/Thesis work/BTR_results/data'

def get_time_per_byte_data(file_path):
    results = []
    p_lower = file_path.lower()
    protocol = "WIFI" if "wifi" in p_lower else ("LORA" if "lora" in p_lower else "BLE")
    method = "Byte" if "byte" in p_lower else ("Chunk" if "chunk" in p_lower else "Full")
    
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        parts = content.split("# METER")
        if len(parts) < 2: return []
        
        df_raw = pd.read_csv(StringIO(parts[1].strip()))
        df_raw.columns = [c.strip() for c in df_raw.columns]
        
        time_col = next((c for c in df_raw.columns if 'time' in c.lower()), 'Timestamp')
        phase_col = 'Phase' if 'Phase' in df_raw.columns else 'Phase'
        
        df_raw[time_col] = pd.to_datetime(df_raw[time_col], errors='coerce')
        time_sec = (df_raw[time_col] - df_raw[time_col].iloc[0]).dt.total_seconds().values
        df_raw['RelTime'] = time_sec
        
        df_raw['block'] = df_raw[phase_col].ne(df_raw[phase_col].shift()).cumsum()
        grouped = df_raw.groupby('block')
        
        blocks = []
        for _, g in grouped:
            blocks.append({
                'name': str(g[phase_col].iloc[0]).strip().upper(),
                'start': g['RelTime'].iloc[0],
                'end': g['RelTime'].iloc[-1]
            })

        for i in range(len(blocks)):
            if 'TX_' in blocks[i]['name']:
                duration = blocks[i]['end'] - blocks[i]['start']
                if i + 1 < len(blocks) and 'TX_' not in blocks[i+1]['name']:
                    duration += (blocks[i+1]['end'] - blocks[i+1]['start'])
                
                match = re.search(r'TX_(\d+)', blocks[i]['name'])
                if match:
                    payload = int(match.group(1))
                    if payload > 0:
                        results.append({
                            'Protocol': protocol, 
                            'Method': method, 
                            'Payload': payload, 
                            'Time_S_B': duration / payload
                        })
    except: pass
    return results

def generate_typst_table(df):
    # Pivot logic
    summary = df.groupby(['Payload', 'Protocol', 'Method'])['Time_S_B'].mean().unstack(level=[1, 2])
    summary = summary.sort_index()
    
    tp = []
    tp.append("#table(")
    # Define 11 columns total: Payload, Mag, and 9 data columns
    tp.append("  columns: (auto, auto, ..(1fr,) * 9),")
    tp.append("  inset: 5pt,")
    tp.append("  align: center + horizon,")
    tp.append("  stroke: 0.5pt + gray.lighten(30%),")
    tp.append("  fill: (x, y) => if y <= 1 { luma(240) },")
    
    # --- FIXED HEADER SECTION ---
    tp.append("  table.header(")
    tp.append("    table.cell(rowspan: 2)[*Payload* \n (B)],")
    tp.append("    table.cell(rowspan: 2)[*Mag.* \n ($10^x$)],")
    tp.append("    table.cell(colspan: 3)[*WIFI*],")
    tp.append("    table.cell(colspan: 3)[*BLE*],")
    tp.append("    table.cell(colspan: 3)[*LORA*],")
    tp.append("  ),")
    
    # Repeat methods for each protocol to align correctly
    tp.append("  table.header(")
    tp.append("    [Full], [Chunk], [Byte], [Full], [Chunk], [Byte], [Full], [Chunk], [Byte]")
    tp.append("  ),")

    # --- DATA ROWS ---
    for payload, row in summary.iterrows():
        valid_vals = [v for v in row.values if not pd.isna(v) and v > 0]
        mag = int(np.floor(np.log10(min(valid_vals)))) if valid_vals else 0
        
        row_cells = [f"[{payload}]", f"[{mag}]"]
        
        for proto in ['WIFI', 'BLE', 'LORA']:
            for meth in ['Full', 'Chunk', 'Byte']:
                val = row.get((proto, meth), None)
                if val is None or np.isnan(val):
                    row_cells.append("[-]")
                else:
                    normalized_val = val / (10**mag)
                    row_cells.append(f"[{normalized_val:.2f}]")
                    
        tp.append("  " + ", ".join(row_cells) + ",")
    
    tp.append(")")
    return "\n".join(tp)

# Execution logic
files = [os.path.join(r, f) for r, d, fs in os.walk(BASE_PATH) for f in fs if f.endswith('.csv')]
data_list = []
for f in tqdm(files, desc="Processing"):
    data_list.extend(get_time_per_byte_data(f))

if data_list:
    final_df = pd.DataFrame(data_list)
    print(generate_typst_table(final_df))