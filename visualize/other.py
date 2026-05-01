import os
import pandas as pd

BASE_PATH = "/Users/foml/coding/MSP/year_3/BTR/visualize/data"
THRESHOLD = 7.5

def debug_glitch_neighborhoods():
    found_count = 0
    print(f"{'FILE':<20} | {'LINE':<8} | {'PREV':<10} | {'CURR (GLITCH)':<12} | {'NEXT':<10} | {'RATIO'}")
    print("-" * 80)

    for root, dirs, files in os.walk(BASE_PATH):
        for file in files:
            if not file.endswith(".csv"): continue
            path = os.path.join(root, file)
            
            try:
                with open(path, 'r') as f:
                    lines = f.readlines()
                
                m_idx = next(i for i, l in enumerate(lines) if "# METER" in l)
                data = []
                # Read the raw strings to see exactly what is in the file
                for idx, l in enumerate(lines[m_idx+1:]):
                    p = l.split(',')
                    if len(p) < 2: continue
                    try:
                        val = float(p[1])
                        # store raw value first, normalization happens later
                        data.append({'line': m_idx + idx + 2, 'v_raw': val})
                    except:
                        continue

                # magnitude correction applied after data is organized
                for d in data:
                    v = d['v_raw']
                    d['v'] = v / 1000.0 if v > 1.0 else v

                for i in range(1, len(data) - 1):
                    v_prev = data[i-1]['v']
                    v_curr = data[i]['v']
                    v_next = data[i+1]['v']

                    if v_prev == 0: continue
                    ratio = v_curr / v_prev

                    if ratio > THRESHOLD or ratio < (1/THRESHOLD):
                        found_count += 1
                        if found_count <= 20: # Only print first 20 to avoid flooding
                            print(f"{file[:20]:<20} | {data[i]['line']:<8} | {v_prev:<10.6f} | {v_curr:<12.6f} | {v_next:<10.6f} | {ratio:.2f}x")
            except Exception as e:
                continue
    
    print("-" * 80)
    print(f"TOTAL GLITCHES DETECTED BY THIS SCAN: {found_count}")

if __name__ == "__main__":
    debug_glitch_neighborhoods()