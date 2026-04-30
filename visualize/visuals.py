import os
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns

# Path Configuration
SUMMARY_FILE = "summary_energy.csv"
PLOT_DIR = "/Users/foml/coding/MSP/year_3/BTR/visualize/plots"

# Create directory if it doesn't exist
if not os.path.exists(PLOT_DIR):
    os.makedirs(PLOT_DIR)
    print(f"📁 Created directory: {PLOT_DIR}")

def generate_final_plots():
    if not os.path.exists(SUMMARY_FILE):
        print(f"❌ Error: '{SUMMARY_FILE}' not found. Please run your data processor first.")
        return

    df = pd.read_csv(SUMMARY_FILE)
    
    # Setup Figure
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(18, 10), sharey=False)
    sns.set_style("whitegrid")

    def draw_detailed_violin(data, ax, palette, title):
        # Rounded Violin: The density of the run-means
        sns.violinplot(data=data, x='Experiment', y='Mean', ax=ax, 
                       palette=palette, inner=None, alpha=0.4, bw_adjust=0.6)
        
        # Raw Dots: Each run's mean (The 30 "votes")
        sns.stripplot(data=data, x='Experiment', y='Mean', ax=ax, 
                      color='black', alpha=0.7, size=5, jitter=True)
        
        # The Grand Mean (White Diamond)
        sns.pointplot(data=data, x='Experiment', y='Mean', ax=ax, 
                      color='white', markers='D', linestyles='', errorbar=None, scale=0.8)
        
        ax.set_title(title, fontsize=15, fontweight='bold')
        ax.set_ylabel("Mean Shunt Voltage (V)", fontsize=12)

    # Draw WiFi and BLE
    wifi_data = df[df['Protocol'].str.lower() == 'wifi']
    ble_data = df[df['Protocol'].str.lower() == 'ble']
    
    if not wifi_data.empty:
        draw_detailed_violin(wifi_data, ax1, "Blues", "WiFi Energy Profile")
    if not ble_data.empty:
        draw_detailed_violin(ble_data, ax2, "Greens", "BLE Energy Profile")

    plt.suptitle("Comparative Energy Analysis: WiFi vs BLE\n(Run-Averaged Distribution)", fontsize=20, fontweight='bold')
    plt.tight_layout(rect=[0, 0.03, 1, 0.93])

    # Save to the specific folder for Typst
    svg_path = os.path.join(PLOT_DIR, "energy_analysis.svg")
    png_path = os.path.join(PLOT_DIR, "energy_analysis.png")
    
    plt.savefig(svg_path, format='svg', bbox_inches='tight')
    plt.savefig(png_path, format='png', dpi=300, bbox_inches='tight')
    
    print(f"✅ Plots saved to: {PLOT_DIR}")
    plt.show()

if __name__ == "__main__":
    generate_final_plots()