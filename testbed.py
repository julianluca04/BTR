import pyvisa
import csv
from datetime import datetime

# --- Config ---
OUTPUT_FILE = "hmc8012_log.csv"

# --- Connect ---
rm = pyvisa.ResourceManager('@py')
resources = rm.list_resources()
hmc_resource = next((r for r in resources if 'USB' in r), None)
if not hmc_resource:
    raise RuntimeError("HMC8012 not found.")

meter = rm.open_resource(hmc_resource)
meter.timeout = 5000
print(f"Connected: {meter.query('*IDN?').strip()}")
print(f"Logging to {OUTPUT_FILE} — press Ctrl+C to stop.\n")

with open(OUTPUT_FILE, 'w', newline='') as f:
    writer = csv.writer(f)
    writer.writerow(["timestamp", "raw"])

    i = 1
    while True:
        raw = meter.query("READ?").strip()
        ts  = datetime.now().isoformat()
        writer.writerow([ts, raw])
        f.flush()
        print(f"[{i:04d}] {ts}  →  {raw}")
        i += 1

meter.close()
rm.close()