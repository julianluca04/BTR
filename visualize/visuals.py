import os
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns

# Path Configuration
SUMMARY_DIR = "/Users/foml/coding/MSP/year_3/BTR/visualize"
SUMMARY_FILE = os.path.join(SUMMARY_DIR, "summary_energy_comprehensive.csv")
PLOT_DIR = os.path.join(SUMMARY_DIR, "plots")

if not os.path.exists(PLOT_DIR):
    os.makedirs(PLOT_DIR)

def generate_vshunt_and_current_plots():
    if not os.path.exists(SUMMARY_FILE):
        print(f"❌ Error: '{SUMMARY_FILE}' not found.")
        return

    df = pd.read_csv(SUMMARY_FILE)
    sns.set_style("whitegrid")
    
    # Create a 2x2 grid: Top row = Vshunt, Bottom row = Current
    fig, axes = plt.subplots(2, 2, figsize=(16, 12), sharex=True)
    (ax1, ax2), (ax3, ax4) = axes

    def draw_violin(data, ax, target_y, palette, ylabel, title):
        sns.violinplot(data=data, x='Experiment', y=target_y, ax=ax, 
                       palette=palette, inner=None, alpha=0.4, bw_adjust=0.6)
        sns.stripplot(data=data, x='Experiment', y=target_y, ax=ax, 
                      color='black', alpha=0.5, size=4, jitter=True)
        sns.pointplot(data=data, x='Experiment', y=target_y, ax=ax, 
                      color='white', markers='D', linestyles='', scale=0.7)
        ax.set_title(title, fontsize=14, fontweight='bold')
        ax.set_ylabel(ylabel)

    # Filter Data
    wifi = df[df['Protocol'].str.contains('wifi', case=False)]
    ble = df[df['Protocol'].str.contains('ble', case=False)]

    # --- ROW 1: VSHUNT (V) ---
    draw_violin(wifi, ax1, 'Vshunt_Mean_V', "Blues", "Vshunt (V)", "WiFi: Raw Voltage")
    draw_violin(ble, ax2, 'Vshunt_Mean_V', "Greens", "Vshunt (V)", "BLE: Raw Voltage")

    # --- ROW 2: CURRENT (mA) ---
    draw_violin(wifi, ax3, 'Current_Mean_mA', "Blues", "Current (mA)", "WiFi: Calculated Current")
    draw_violin(ble, ax4, 'Current_Mean_mA', "Greens", "Current (mA)", "BLE: Calculated Current")

    plt.suptitle("Energy Analysis: Vshunt vs. Calibrated Current\n(WiFi vs BLE Comparison)", fontsize=18, fontweight='bold')
    plt.tight_layout(rect=[0, 0.03, 1, 0.95])

    # Save outputs
    plt.savefig(os.path.join(PLOT_DIR, "vshunt_current_analysis.png"), dpi=300)
    plt.savefig(os.path.join(PLOT_DIR, "vshunt_current_analysis.svg"), format='svg')
    
    print(f"✅ Comparison plots saved to: {PLOT_DIR}")
    plt.show()

if __name__ == "__main__":
    generate_vshunt_and_current_plots()