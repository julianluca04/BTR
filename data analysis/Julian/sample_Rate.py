import os
import pandas as pd
import numpy as np

# --- Path ---
BASE_PATH = '/Users/foml/coding/MSP/year_3/Thesis work/BTR_results/data'

def analyze_file_sampling(file_path):
    """Parses the # METER section to calculate actual hardware vs USB rates."""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
            
        # Find the start of the meter data
        meter_idx = -1
        for i, line in enumerate(lines):
            if "# METER" in line:
                meter_idx = i
                break
        
        if meter_idx == -1:
            return None

        # Extract data lines after the header (header is meter_idx + 1)
        raw_data = []
        for line in lines[meter_idx + 2:]:
            if not line.strip():
                continue
            # Split by comma and strip whitespace/tabs
            parts = [p.strip() for p in line.split(',')]
            # Take the first 4 columns (Timestamp, V_Shunt, Phase, Current)
            if len(parts) >= 2:
                raw_data.append(parts[:4])

        if not raw_data:
            return None

        df = pd.DataFrame(raw_data, columns=["timestamp", "v_shunt", "phase", "current"][:len(raw_data[0])])
        
        # Convert types with explicit format to avoid UserWarning and increase speed
        # Format matching: 2026-04-13T15:40:12.770
        df['timestamp'] = pd.to_datetime(df['timestamp'], format='%Y-%m-%dT%H:%M:%S.%f', errors='coerce')
        df['v_shunt'] = pd.to_numeric(df['v_shunt'], errors='coerce')
        
        df = df.dropna(subset=['v_shunt', 'timestamp'])

        if df.empty:
            return None

        # Calculate time duration
        duration = (df['timestamp'].max() - df['timestamp'].min()).total_seconds()
        if duration <= 0:
            return None

        # Hardware transitions: count rows where voltage changes from previous row
        unique_changes = (df['v_shunt'] != df['v_shunt'].shift()).sum()
        
        hw_rate = unique_changes / duration
        usb_rate = len(df) / duration
        
        return {
            "File": os.path.basename(file_path),
            "HW_Rate": round(hw_rate, 2),
            "USB_Rate": round(usb_rate, 2),
            "Efficiency_%": round((hw_rate / usb_rate) * 100, 1),
            "Samples": unique_changes,
            "Secs": round(duration, 2)
        }
    except Exception:
        return None

def main():
    report_data = []
    print(f"Auditing sample rates in: {BASE_PATH}...")
    
    for root, dirs, files in os.walk(BASE_PATH):
        for file in files:
            if file.endswith(".csv") and not file.startswith("."):
                full_path = os.path.join(root, file)
                result = analyze_file_sampling(full_path)
                if result:
                    result["Folder"] = os.path.relpath(root, BASE_PATH)
                    report_data.append(result)

    if not report_data:
        print("No valid CSV data found in # METER sections.")
        return

    df_report = pd.DataFrame(report_data).sort_values(["Folder", "File"])
    
    display_cols = ["Folder", "File", "HW_Rate", "USB_Rate", "Efficiency_%", "Samples"]
    
    print("\n" + "="*100)
    print(f"{'SAMPLING PERFORMANCE REPORT':^100}")
    print("="*100)
    print(df_report[display_cols].to_string(index=False))
    print("="*100)
    
    print(f"Total Files: {len(df_report)}")
    print(f"Avg HW Rate: {df_report['HW_Rate'].mean():.2f} Hz")
    print(f"Avg USB Rate: {df_report['USB_Rate'].mean():.2f} Hz")

if __name__ == "__main__":
    main()