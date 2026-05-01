import os
import pandas as pd
import numpy as np
from decimal import Decimal, getcontext
import concurrent.futures
import math

getcontext().prec = 20

R_MEAN = 1.134584
R_STD = 0.001448
V_OFFSET = -0.002182e-3
U_OFFSET = 0.001699e-3
V_SOURCE = 5.020379
U_VSOURCE = 0.000356

HMC8012_READING_PCT = 0.00015
HMC8012_RANGE_PCT = 0.00002
HMC8012_RANGE_V = 0.400
RECT_TO_GAUSSIAN = math.sqrt(3)

BASE_PATH = "/Users/foml/coding/MSP/year_3/BTR/visualize/data"
SUMMARY_DIR = "/Users/foml/coding/MSP/year_3/BTR/visualize"
SUMMARY_PATH = os.path.join(SUMMARY_DIR, "summary_energy_comprehensive.csv")
PROTOCOLS = ["wifi", "BLE"]
EXPERIMENTS = ["chunk", "byte", "all"]
K_FACTOR = 2


def is_7_5_x_glitch(a, b):
    if a == 0 or b == 0:
        return False
    try:
        r = a / b
        return r >= 7.5 or r <= (1 / 7.5)
    except:
        return False


def effective_sample_size(s):
    n = len(s)
    if n < 3:
        return n
    try:
        rho = s.autocorr(lag=1)
        if np.isnan(rho) or abs(rho) >= 1:
            return n
        return max(1, n * (1 - rho) / (1 + rho))
    except:
        return n


def load_file(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.readlines()


def split_sections(lines):
    info_idx = next((i for i, l in enumerate(lines) if "# INFO" in l), -1)
    meter_idx = next((i for i, l in enumerate(lines) if "# METER" in l), -1)
    return info_idx, meter_idx


def parse_data(lines, meter_idx):
    raw = []
    overview = []

    for line in lines[meter_idx + 1:]:
        s = line.strip()
        if not s or "delay" in s:
            continue

        parts = [p.strip() for p in s.split(",")]

        if len(parts) >= 5 and parts[4]:
            overview.append(s + "\n")
            continue

        if len(parts) < 2:
            continue

        try:
            v = float(parts[1])
            v_norm = v / 1000.0 if v > 1.0 else v
            raw.append({
                "ts": parts[0],
                "v_raw": v,
                "v_norm": v_norm,
                "state": parts[2] if len(parts) > 2 else ""
            })
        except:
            continue

    return raw, overview


def glitch_correction(raw, file_name, glitch_log):
    v = [r["v_norm"] for r in raw]
    clean = list(v)
    noise_gate = 0.001

    for i in range(1, len(v) - 1):
        if abs(v[i]) > noise_gate:
            if is_7_5_x_glitch(v[i], v[i-1]) or is_7_5_x_glitch(v[i], v[i+1]):
                clean[i] = min(v[i-1], v[i+1])
                glitch_log.append(f"[{file_name}] glitch at {raw[i]['ts']}")

    return clean


def compute_stats(clean):
    s = pd.Series(clean)
    n = len(s)
    neff = effective_sample_size(s)

    uA = s.std() / math.sqrt(neff) if neff > 0 else 0
    uB = math.sqrt(
        ((HMC8012_READING_PCT * abs(s.mean())) / RECT_TO_GAUSSIAN) ** 2 +
        ((HMC8012_RANGE_PCT * HMC8012_RANGE_V) / RECT_TO_GAUSSIAN) ** 2
    )

    u = math.sqrt(uA**2 + uB**2 + U_OFFSET**2)

    current = (s - V_OFFSET) / R_MEAN

    return {
        "series": s,
        "current": current,
        "n": n,
        "neff": neff,
        "u": u
    }


def write_file(path, lines, info, overview, raw, clean):
    out = [
        f"{raw[i]['ts']},{clean[i]:.9f},{raw[i]['state']},{((clean[i]-V_OFFSET)/R_MEAN):.9f}\n"
        for i in range(len(clean))
    ]

    with open(path, "w", encoding="utf-8") as f:
        f.writelines(["# INFO\n"] + info + ["# OVERVIEW\n"] + overview + ["# METER\n"] + out)


def process_single_file(task):
    protocol, exp, name, path = task

    if not os.path.exists(path):
        return None

    try:
        lines = load_file(path)
        info_idx, meter_idx = split_sections(lines)
        if meter_idx == -1:
            return None

        info = []
        skip = False
        for l in lines[info_idx+1:meter_idx]:
            s = l.strip()
            if "# META" in s:
                skip = True
                continue
            if skip and s.startswith("#"):
                skip = False
                info.append(l)
                continue
            if not skip:
                info.append(l)

        raw, overview = parse_data(lines, meter_idx)
        if not raw:
            return None

        glitch_log = []
        clean = glitch_correction(raw, name, glitch_log)

        stats = compute_stats(clean)

        write_file(path, lines, info, overview, raw, clean)

        return {
    "stats": {
        "Protocol": protocol,
        "Experiment": exp,
        "Run": name,

        # sample structure
        "Samples_N": stats["n"],
        "Samples_N_eff": stats["neff"],

        # voltage (clean signal)
        "Vshunt_Mean_V": stats["series"].mean(),
        "Vshunt_Median_V": stats["series"].median(),
        "Vshunt_Std_V": stats["series"].std(),
        "Vshunt_Max_V": stats["series"].max(),
        "Vshunt_Min_V": stats["series"].min(),
        "Vshunt_Combined_Uncert_V": stats["u"],

        # current (derived)
        "Current_Mean_mA": stats["current"].mean() * 1000,
        "Current_Median_mA": stats["current"].median() * 1000,
        "Current_Std_mA": stats["current"].std() * 1000,
        "Current_Max_mA": stats["current"].max() * 1000,
        "Current_Min_mA": stats["current"].min() * 1000,

        # energy proxy (important missing piece)
        "Power_Mean_mW": (stats["current"].mean() * V_SOURCE) * 1000,
        "Power_Std_mW": (stats["current"].std() * V_SOURCE) * 1000,

        # relative uncertainty propagation
        "Power_Rel_Uncert_pct": math.sqrt(
            (stats["u"] / abs(stats["series"].mean()))**2 +
            (U_VSOURCE / V_SOURCE)**2
        ) * 100
    },
    "glitches": glitch_log
}

    except Exception as e:
        print(f"Error {name}: {e}")
        return None


def main():
    print("-" * 50)
    print("MASTER PROCESSOR RUN")
    print("-" * 50)

    os.makedirs(SUMMARY_DIR, exist_ok=True)

    tasks = []
    for p in PROTOCOLS:
        for e in EXPERIMENTS:
            folder = os.path.join(BASE_PATH, p, e)
            if not os.path.exists(folder):
                continue
            for f in os.listdir(folder):
                if f.endswith(".csv"):
                    tasks.append((p, e, f, os.path.join(folder, f)))

    results = []
    glitches = []

    with concurrent.futures.ProcessPoolExecutor() as ex:
        for r in ex.map(process_single_file, tasks):
            if r:
                results.append(r["stats"])
                glitches.extend(r["glitches"])

    if results:
    # float_format='%.10f' forces 10 decimal places and disables scientific notation
        pd.DataFrame(results).to_csv(SUMMARY_PATH, index=False, float_format='%.10f')
        print("DONE")
        print(len(glitches), "magnitude errors detected")


if __name__ == "__main__":
    main()