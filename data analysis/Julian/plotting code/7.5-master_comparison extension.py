import os
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
from tqdm import tqdm
from io import StringIO
import re
import matplotlib.ticker as ticker
from mpl_toolkits.axes_grid1.inset_locator import inset_axes, mark_inset
from scipy.optimize import curve_fit

# --- Configuration ---
BASE_PATH = r'/Users/foml/Library/Mobile Documents/com~apple~CloudDocs/important/coding/MSP/year_3/Thesis work/BTR_results/data'
SAVE_PATH = r'/Users/foml/Library/Mobile Documents/com~apple~CloudDocs/important/coding/MSP/year_3/Thesis work/BTR_results/plots/7.5-master_comparison_extension'
CALIB_PATH = r'/Users/foml/Library/Mobile Documents/com~apple~CloudDocs/important/coding/MSP/year_3/Thesis work/BTR_results/calibration_constants_summary.csv'


os.makedirs(SAVE_PATH, exist_ok=True)

# --- Colour Palettes ---
METHOD_PALETTE = {
    'CHUNK': '#1f77b4',   # blue
    'BYTE': '#ff7f0e',    # orange
    'ALL': '#2ca02c'      # green
}

PROTOCOL_PALETTE = {
    'WIFI': '#1f77b4',
    'BLE': '#ff7f0e',
    'LORA': '#2ca02c'
}

# --- Regression Fit Mode ---
USE_LOG_FIT = True

def load_calibration_values(path):
    try:
        df = pd.read_csv(path)
        return (df.loc[df['Metric'] == 'Voltage', 'Mean'].values[0],
                df.loc[df['Metric'] == 'Resistance', 'Mean'].values[0],
                df.loc[df['Metric'] == 'Offset', 'Mean'].values[0])
    except:
        return 5.0204, 1.1346, -0.000002

VOLTAGE_SUPPLY, R_SHUNT, V_OFFSET = load_calibration_values(CALIB_PATH)

# --- Regression helpers ---
def exponential_decay(x, a, b, c):
    return a * np.exp(-b * x) + c


def asymptotic_power_model(x, a, x0, k, c):
    return c + a / (1 + (x / x0) ** k)


def inverse_power_model(x, a, b, c):
    return a * (x ** (-b)) + c


def logarithmic_decay(x, a, b, c):
    return a - b * np.log(x + 1) + c


def stretched_exponential(x, a, b, d, c):
    return a * np.exp(-(b * x) ** d) + c


def rational_decay(x, a, b, c, d):
    return (a / (b + x ** c)) + d


def hill_decay(x, a, x0, k, c):
    return c + a / (1 + (x / x0) ** k)


def weibull_decay(x, a, b, d, c):
    return a * np.exp(-((x / b) ** d)) + c


def compute_metrics(y_true, y_pred):
    eps = 1e-12

    y_true = np.array(y_true, dtype=float)
    y_pred = np.array(y_pred, dtype=float)

    ss_res = np.sum((y_true - y_pred) ** 2)
    ss_tot = np.sum((y_true - np.mean(y_true)) ** 2)

    r2 = 1 - (ss_res / max(ss_tot, eps))
    rmse = np.sqrt(np.mean((y_true - y_pred) ** 2))

    return {
        'r2': r2,
        'rmse': rmse
    }

def detect_plateau(x, y):
    """
    Detect whether the signal shows plateau behaviour at high payloads.
    Returns True if tail slope is sufficiently flat.
    """
    x = np.array(x, dtype=float)
    y = np.array(y, dtype=float)

    if len(x) < 6:
        return False

    # sort by x
    idx = np.argsort(x)
    x = x[idx]
    y = y[idx]

    # take last 30% of points
    cut = max(3, int(0.3 * len(y)))
    y_tail = y[-cut:]

    # compute relative variation in tail
    dy = np.abs(np.diff(y_tail))
    mean_tail_var = np.mean(dy)

    global_range = np.max(y) - np.min(y)

    if global_range < 1e-12:
        return False

    # plateau if tail variation is small relative to overall range
    return mean_tail_var < 0.02 * global_range

def add_regression_extension(ax, plot_df, hue_col, palette):
    """
    Fit exponential decay regression per category and extend x-axis.
    Plots:
    - fitted curve over measured data
    - extrapolated extension to larger payloads
    """

    max_payload = plot_df['Payload'].max()
    x_extended = np.logspace(
        np.log2(max_payload),
        np.log2(max_payload * 8),
        300,
        base=2
    )

    for category in plot_df[hue_col].unique():
        subset = plot_df[plot_df[hue_col] == category]

        grouped = (
            subset.groupby('Payload', as_index=False)['mJ_B']
            .mean()
            .sort_values('Payload')
        )

        if len(grouped) < 4:
            continue

        x = grouped['Payload'].values.astype(float)
        y = grouped['mJ_B'].values.astype(float)

        plateau = detect_plateau(x, y)

        # Convert to log space for regression stability
        x_fit = np.log2(x)
        y_fit = np.log(y)

        # Strongly prioritise middle and end payloads during fitting
        # Small payloads are easy to fit and distort extrapolation.
        x_norm = x / np.max(x)

        try:
            if plateau:
                model_candidates = {
                    'Exponential Plateau': {
                        'func': lambda x, a, b, c: c + a * np.exp(-b * x),
                        'p0': [1.0, 0.1, np.min(y)],
                        'bounds': ([-np.inf, 0, -np.inf], [np.inf, np.inf, np.inf])
                    },
                    'Hill Saturation': {
                        'func': lambda x, a, x0, k, c: c + a / (1 + (x / x0) ** k),
                        'p0': [1.0, np.median(x), 2.0, np.min(y)],
                        'bounds': ([-np.inf, 0, 0, -np.inf], [np.inf, np.inf, np.inf, np.inf])
                    },
                    'Weibull Plateau': {
                        'func': lambda x, a, b, d, c: c + a * np.exp(-((x / b) ** d)),
                        'p0': [1.0, np.median(x), 1.0, np.min(y)],
                        'bounds': ([-np.inf, 0, 0, -np.inf], [np.inf, np.inf, np.inf, np.inf])
                    }
                }
            else:
                model_candidates = {
                    'Linear (log-log)': {
                        'func': lambda x, a, b: a * x + b,
                        'p0': [1.0, 0.0],
                        'bounds': ([-10, -10], [10, 10])
                    },
                    'Quadratic (log-log)': {
                        'func': lambda x, a, b, c: a * x**2 + b * x + c,
                        'p0': [0.1, 0.1, 0.1],
                        'bounds': ([-10, -10, -10], [10, 10, 10])
                    },
                    'Cubic (log-log)': {
                        'func': lambda x, a, b, c, d: a * x**3 + b * x**2 + c * x + d,
                        'p0': [0.01, 0.01, 0.01, 0.01],
                        'bounds': ([-10]*4, [10]*4)
                    },
                    'Power Law': {
                        'func': lambda x, a, b: a - b * x,
                        'p0': [1.0, 1.0],
                        'bounds': ([-10, -10], [10, 10])
                    }
                }

            print(f'\n{"=" * 80}')
            print(f'Regression comparison for: {category}')
            print(f'{"=" * 80}')

            best_model_name = None
            best_model_func = None
            best_params = None
            best_metrics = None
            best_score = -np.inf

            for model_name, config in model_candidates.items():
                try:
                    params, _ = curve_fit(
                        config['func'],
                        x_fit,
                        y_fit,
                        p0=config['p0'],
                        bounds=config['bounds'],
                        method='trf',
                        loss='soft_l1',
                        f_scale=0.25,
                        maxfev=50000
                    )

                    log_y_pred = config['func'](x_fit, *params)
                    y_pred = np.exp(log_y_pred)

                    # Reject physically impossible fits
                    if np.any(y_pred <= 0):
                        raise ValueError('negative prediction')

                    # Enforce monotonic decrease
                    dense_x = np.logspace(np.log2(min(x)), np.log2(max(x)), 200, base=2)
                    dense_x_log = np.log2(dense_x)
                    dense_y_log = config['func'](dense_x_log, *params)
                    dense_y = np.exp(dense_y_log)

                    # Reject unrealistic plateau behaviour
                    tail_gradient = np.mean(np.abs(np.diff(dense_y[-40:])))
                    if tail_gradient > (0.08 * np.mean(dense_y[-40:])):
                        raise ValueError('poor plateau behaviour')

                    if np.any(np.diff(dense_y) > 0):
                        raise ValueError('non-monotonic fit')

                    metrics = compute_metrics(y, y_pred)

                    print(
                        f'{model_name:<25} | '
                        f'R²={metrics["r2"]:.5f} | '
                        f'RMSE={metrics["rmse"]:.5f}'
                    )
                    print(f"Equation [{model_name}] params: {params}")

                    # Selection logic: just R2
                    score = metrics['r2']

                    if score > best_score:
                        best_score = score
                        best_model_name = model_name
                        best_model_func = config['func']
                        best_params = params
                        best_metrics = metrics

                except Exception as model_err:
                    print(f'{model_name:<25} | FAILED ({model_err})')

            print(f'BEST MODEL: {best_model_name}')
            print('=' * 80)
            print("\nFINAL SELECTED MODEL EQUATION:")
            print(f"{best_model_name} with params {best_params}")

            # Store regression result globally
            REGRESSION_RESULTS.append({
                'category': category,
                'model': best_model_name,
                'r2': best_metrics['r2'],
                'params': best_params.tolist() if hasattr(best_params, 'tolist') else best_params
            })

            x_fit_full = np.logspace(
                np.log2(min(x)),
                np.log2(max_payload * 8),
                800,
                base=2
            )
            x_fit_log = np.log2(x_fit_full)
            y_fit = np.exp(best_model_func(x_fit_log, *best_params))

            ax.plot(
                x_fit_full,
                y_fit,
                linestyle='--',
                linewidth=3,
                alpha=0.95,
                color=palette.get(category, None),
                zorder=10,
                label=f'{category} best fit ({best_model_name}, R2={best_metrics["r2"]:.3f})'
            )

            ax.axvline(
                max_payload,
                color='gray',
                linestyle=':',
                alpha=0.4
            )

        except Exception as e:
            print(f'Regression failed for {category}: {e}')
# --- Regression Export Storage ---
REGRESSION_RESULTS = []

def process_file(file_path):
    results = []
    p_lower = file_path.lower()
    protocol = "WIFI" if "wifi" in p_lower else ("LORA" if "lora" in p_lower else "BLE")
    method = "BYTE" if "byte" in p_lower else ("CHUNK" if "chunk" in p_lower else "ALL")
    
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        parts = content.split("# METER")
        if len(parts) < 2: return []
        
        df_raw = pd.read_csv(StringIO(parts[1].strip()))
        df_raw.columns = [c.strip() for c in df_raw.columns]
        
        time_col = next((c for c in df_raw.columns if 'time' in c.lower()), 'Timestamp')
        v_col = 'V_Shunt' if 'V_Shunt' in df_raw.columns else df_raw.columns[1]
        phase_col = 'Phase' if 'Phase' in df_raw.columns else 'Phase'

        v_shunt_v = pd.to_numeric(df_raw[v_col], errors='coerce').apply(lambda x: x/1000.0 if abs(x) > 2.0 else x)
        current_a = (v_shunt_v - V_OFFSET) / R_SHUNT
        # P = I * (Vs - Vshunt)
        power_mw = current_a * (VOLTAGE_SUPPLY - (v_shunt_v - V_OFFSET)) * 1000

        df_raw[time_col] = pd.to_datetime(df_raw[time_col], errors='coerce')
        time_sec = (df_raw[time_col] - df_raw[time_col].iloc[0]).dt.total_seconds().values
        
        dt = np.diff(time_sec)
        p_avg = (power_mw.values[:-1] + power_mw.values[1:]) / 2.0
        df_raw['Sample_mJ'] = np.append(p_avg * dt, 0)
        
        df_raw['block'] = df_raw[phase_col].ne(df_raw[phase_col].shift()).cumsum()
        grouped = df_raw.groupby('block')
        blocks = [{'name': str(g[phase_col].iloc[0]).strip().upper(), 'energy': g['Sample_mJ'].sum()} for _, g in grouped]

        for i in range(len(blocks)):
            if 'TX_' in blocks[i]['name']:
                energy_total = blocks[i]['energy']
                # Correctly include the "tail" energy of the radio shutting down
                if i + 1 < len(blocks) and 'TX_' not in blocks[i+1]['name']:
                    energy_total += blocks[i+1]['energy']
                
                match = re.search(r'TX_(\d+)', blocks[i]['name'])
                if match:
                    payload = int(match.group(1))
                    if payload > 0:
                        results.append({'Protocol': protocol, 'Method': method, 'Payload': payload, 'mJ_B': energy_total / payload})
    except: pass
    return results

def apply_plot_formatting(fig, ax, plot_df, hue_val, title):
    ax.set_xscale('log', base=2)
    ax.set_yscale('log')
    ax.xaxis.set_major_formatter(ticker.ScalarFormatter())
    ax.set_xlim(left=max(1, plot_df['Payload'].min() * 0.8),
                right=plot_df['Payload'].max() * 8)
    
    # Grid and Sub-lines
    ax.yaxis.set_minor_locator(ticker.LogLocator(base=10.0, subs=np.arange(2, 10) * 0.1, numticks=12))
    ax.grid(True, which='both', linestyle='--', alpha=0.3)
    
    # Legend as Suptitle
    handles, labels = ax.get_legend_handles_labels()
    if handles:
        ax.get_legend().remove()
        fig.legend(handles, labels, loc='upper center', bbox_to_anchor=(0.5, 0.92), 
                   ncol=3, frameon=True, fontsize=13)

    # Inset Window (Top Right)
    ax_ins = inset_axes(ax, width="35%", height="35%", loc='upper right', borderpad=3)
    zoom_df = plot_df[plot_df['Payload'] <= 16]
    if not zoom_df.empty:
        sns.lineplot(data=zoom_df, x="Payload", y="mJ_B", hue=hue_val, legend=False, ax=ax_ins, marker='o', markersize=5)
        ax_ins.set_xscale('log', base=2)
        ax_ins.set_yscale('log')
        # Same axis titles as parent
        ax_ins.set_xlabel("Payload Size (Bytes)", fontsize=7)
        ax_ins.set_ylabel("mJ/Byte", fontsize=7)
        ax_ins.tick_params(labelsize=6)
        mark_inset(ax, ax_ins, loc1=2, loc2=4, fc="none", ec="0.5", ls="--", alpha=0.4)

    ax.set_title(title, fontsize=18, fontweight='bold', pad=60)
    ax.set_xlabel("Payload Size (Bytes)", fontweight='bold', fontsize=14)
    ax.set_ylabel("Energy Efficiency (mJ per Byte)", fontweight='bold', fontsize=14)
    ax.tick_params(axis='both', which='major', labelsize=12)

def run():
    files = [os.path.join(r, f) for r, d, fs in os.walk(BASE_PATH) for f in fs if f.endswith('.csv')]
    data = []
    for f in tqdm(files, desc="Parsing"): data.extend(process_file(f))
    df = pd.DataFrame(data)
    if df.empty: return

    sns.set_theme(style="whitegrid", font="serif")

    # Group 1: Methods per Protocol
    for p in df['Protocol'].unique():
        pdf = df[df['Protocol'] == p].sort_values('Payload')
        fig, ax = plt.subplots(figsize=(12, 9))
        sns.lineplot(
            data=pdf,
            x="Payload",
            y="mJ_B",
            hue="Method",
            palette=METHOD_PALETTE,
            marker='o',
            markersize=8,
            ax=ax,
            errorbar=('ci', 95)
        )

        add_regression_extension(ax, pdf, "Method", METHOD_PALETTE)
        apply_plot_formatting(fig, ax, pdf, "Method", f"{p}: Efficiency Comparison by Transfer Method")

        fig.savefig(os.path.join(SAVE_PATH, f"proto_{p.lower()}.png"), dpi=300, bbox_inches='tight')
        fig.savefig(os.path.join(SAVE_PATH, f"proto_{p.lower()}.svg"), format='svg', bbox_inches='tight')
        plt.close(fig)

    # Group 2: Protocols per Method
    for m in df['Method'].unique():
        mdf = df[df['Method'] == m].sort_values('Payload')
        fig, ax = plt.subplots(figsize=(12, 9))
        sns.lineplot(
            data=mdf,
            x="Payload",
            y="mJ_B",
            hue="Protocol",
            palette=PROTOCOL_PALETTE,
            marker='o',
            markersize=8,
            ax=ax,
            errorbar=('ci', 95)
        )

        add_regression_extension(ax, mdf, "Protocol", PROTOCOL_PALETTE)
        apply_plot_formatting(fig, ax, mdf, "Protocol", f"{m} Method: Protocol Efficiency Comparison")

        fig.savefig(os.path.join(SAVE_PATH, f"meth_{m.lower()}.png"), dpi=300, bbox_inches='tight')
        fig.savefig(os.path.join(SAVE_PATH, f"meth_{m.lower()}.svg"), format='svg', bbox_inches='tight')
        plt.close(fig)

    # Save regression results to CSV
    pd.DataFrame(REGRESSION_RESULTS).to_csv(
        os.path.join(SAVE_PATH, "regression_equations.csv"),
        index=False
    )

if __name__ == "__main__":
    run()