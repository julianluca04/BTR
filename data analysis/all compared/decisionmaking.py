import os
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt

# =========================================================
# CONFIG
# =========================================================

PROTOCOLS = {

    "WiFi": {
        "tx_dir": "/Users/jude/Documents/GitHub/BTR/data analysis/WiFi (all in one)/tx/final analysis/rephased data",
        "boot_dir": "/Users/jude/Documents/GitHub/BTR/data analysis/WiFi (all in one)/boot/trimmed/trimmed data",
        "v_supply_b": 5.013517,
        "v_supply_tx": 5.013517
    },

    "BLE": {
        "tx_dir": "/Users/jude/Documents/GitHub/BTR/data analysis/BLE (all in one)/tx/final analysis/rephased data",
        "boot_dir": "/Users/jude/Documents/GitHub/BTR/data analysis/BLE (all in one)/boot/trimmed/trimmed data",
        "v_supply_b": 5.013517,
        "v_supply_tx": 5.013517
    },

    "LoRa": {
        "tx_dir": "/Users/jude/Documents/GitHub/BTR/data analysis/LoRa (all in one)/tx/final analysis/rephased data",
        "boot_dir": "/Users/jude/Documents/GitHub/BTR/data analysis/LoRa (all in one)/boot/trimmed/trimmed data",
        "v_supply_b": 5.013517,
        "v_supply_tx": 5.011090
    }
}

MAX_PAYLOAD = 65536

# =========================================================
# HELPERS
# =========================================================

def load_meter_csv(path):

    with open(path) as f:
        lines = f.readlines()

    meter_idx = next(
        i for i, l in enumerate(lines)
        if "# METER" in l
    )

    df = pd.read_csv(path, skiprows=meter_idx + 1)

    df.columns = [c.strip() for c in df.columns]

    df["timestamp"] = pd.to_datetime(
        df["timestamp"],
        errors="coerce"
    )

    df["current"] = df["current"].astype(float)

    df = df.dropna(subset=["timestamp"])

    return df


def integrate_energy(df, v_supply):

    if len(df) < 2:
        return np.nan

    df = df.sort_values("timestamp")

    t0 = df["timestamp"].iloc[0]

    t = (
        df["timestamp"] - t0
    ).dt.total_seconds().values

    current = df["current"].values

    power = v_supply * current

    energy = np.trapz(power, t)

    return energy


def compute_duration(df):

    if len(df) < 2:
        return np.nan

    df = df.sort_values("timestamp")

    duration = (
        df["timestamp"].iloc[-1]
        - df["timestamp"].iloc[0]
    ).total_seconds()

    return duration


# =========================================================
# BOOT ENERGY + DURATION
# =========================================================

def compute_boot_stats(folder, v_supply):

    energies = []
    durations = []

    for f in os.listdir(folder):

        if not f.endswith(".csv"):
            continue

        path = os.path.join(folder, f)

        df = load_meter_csv(path)

        E = integrate_energy(df, v_supply)
        T = compute_duration(df)

        if not np.isnan(E):
            energies.append(E)

        if not np.isnan(T):
            durations.append(T)

    return (
        np.mean(energies),
        np.mean(durations)
    )


# =========================================================
# TX ENERGY + DURATION
# =========================================================

def compute_tx_stats(folder, v_supply):

    payload_energy = {}
    payload_duration = {}

    for f in os.listdir(folder):

        if not f.endswith(".csv"):
            continue

        path = os.path.join(folder, f)

        df = load_meter_csv(path)

        df["block"] = (
            df["phase"] != df["phase"].shift()
        ).cumsum()

        for _, group in df.groupby("block", sort=False):

            phase = group["phase"].iloc[0]

            if not str(phase).startswith("tx_"):
                continue

            try:
                payload = int(
                    phase.split("_")[1]
                )
            except:
                continue

            E = integrate_energy(
                group,
                v_supply
            )

            T = compute_duration(group)

            if np.isnan(E) or np.isnan(T):
                continue

            if payload not in payload_energy:
                payload_energy[payload] = []

            if payload not in payload_duration:
                payload_duration[payload] = []

            payload_energy[payload].append(E)
            payload_duration[payload].append(T)

    mean_energy = {
        p: np.mean(v)
        for p, v in payload_energy.items()
    }

    mean_duration = {
        p: np.mean(v)
        for p, v in payload_duration.items()
    }

    return mean_energy, mean_duration


# =========================================================
# IDLE POWER
# =========================================================

def compute_idle_power(folder, v_supply):

    powers = []

    for f in os.listdir(folder):

        if not f.endswith(".csv"):
            continue

        path = os.path.join(folder, f)

        df = load_meter_csv(path)

        idle_df = df[
            df["phase"].str.contains(
                "idle",
                case=False,
                na=False
            )
        ].copy()

        if len(idle_df) == 0:
            continue

        current = idle_df["current"].values

        power = v_supply * current

        powers.append(np.mean(power))

    return np.mean(powers)


# =========================================================
# INTERPOLATION MODEL
# =========================================================

def estimate_value(x, xs, ys):

    return np.interp(
        x,
        xs,
        ys
    )


# =========================================================
# FIT VISUALIZATION
# =========================================================

def plot_fit(protocol, payloads, energies):

    plt.figure(figsize=(8, 5))

    plt.scatter(
        payloads,
        energies,
        color="deeppink",
        s=70,
        label="Measured"
    )

    x_fit = np.linspace(
        payloads.min(),
        payloads.max(),
        1000
    )

    y_fit = np.interp(
        x_fit,
        payloads,
        energies
    )

    plt.plot(
        x_fit,
        y_fit,
        color="crimson",
        linewidth=2,
        label="Interpolated"
    )

    plt.xscale("log", base=2)

    plt.xlabel("Payload Size (bytes)")
    plt.ylabel("TX Energy (J)")

    plt.title(f"{protocol} TX Energy Model")

    plt.grid(True, alpha=0.3)

    plt.legend()

    plt.tight_layout()
    plt.show()


# =========================================================
# DATABASE BUILD
# =========================================================

def build_database():

    db = {}

    for protocol, cfg in PROTOCOLS.items():

        print(f"\nProcessing {protocol}...")

        # ---------------- BOOT ----------------

        boot_E, boot_T = compute_boot_stats(
            cfg["boot_dir"],
            cfg["v_supply_b"]
        )

        # ---------------- TX ----------------

        tx_E, tx_T = compute_tx_stats(
            cfg["tx_dir"],
            cfg["v_supply_tx"]
        )

        # ---------------- IDLE ----------------

        idle_P = compute_idle_power(
            cfg["tx_dir"],
            cfg["v_supply_tx"]
        )

        payloads = np.array(
            sorted(tx_E.keys())
        )

        energies = np.array([
            tx_E[p]
            for p in payloads
        ])

        durations = np.array([
            tx_T[p]
            for p in payloads
        ])

        # ---------------- STORE ----------------

        db[protocol] = {

            "boot_energy": boot_E,
            "boot_duration": boot_T,

            "idle_power": idle_P,

            "tx_energies": tx_E,
            "tx_durations": tx_T,

            "payloads": payloads,
            "energies": energies,
            "durations": durations
        }

        # ---------------- PRINT SUMMARY ----------------

        print(f"\n{protocol}")
        print("-" * 40)

        print(f"Mean boot energy   : {boot_E:.6e} J")
        print(f"Mean boot duration : {boot_T:.6e} s")
        print(f"Mean idle power    : {idle_P:.6e} W")

        print("\nMean TX energies:")

        for p in payloads:

            print(
                f"  {p:6d} B : "
                f"{tx_E[p]:.6e} J"
            )

        # ---------------- PLOT ----------------

        plot_fit(
            protocol,
            payloads,
            energies
        )

    return db


# =========================================================
# ENERGY ESTIMATOR
# =========================================================

def run_energy_estimator(db):

    print("\n=================================================")
    print("ENERGY ESTIMATOR")
    print("=================================================")

    # -------------------------------------------------
    # USER INPUT
    # -------------------------------------------------

    while True:

        payload = int(input(
            "\nPayload size (bytes): "
        ))

        if payload <= 0:
            print("Must be > 0")
            continue

        if payload > MAX_PAYLOAD:
            print(f"Max payload = {MAX_PAYLOAD}")
            continue

        break

    total_on_time = float(input(
        "\nTotal ON time (seconds): "
    ))

    # =================================================
    # CALCULATE ALL PROTOCOLS
    # =================================================

    results = {}

    print("\n=================================================")
    print("RESULTS")
    print("=================================================")

    for protocol in db:

        protocol_db = db[protocol]

        # ---------------- BOOT ----------------

        boot_energy = protocol_db["boot_energy"]
        boot_duration = protocol_db["boot_duration"]

        # ---------------- TX ----------------

        payloads = protocol_db["payloads"]

        tx_energy = estimate_value(
            payload,
            payloads,
            protocol_db["energies"]
        )

        tx_duration = estimate_value(
            payload,
            payloads,
            protocol_db["durations"]
        )

        # ---------------- IDLE ----------------

        idle_power = protocol_db["idle_power"]

        idle_time = max(
            0,
            total_on_time
            - tx_duration
            - boot_duration
        )

        idle_energy = (
            idle_power
            * idle_time
        )

        # ---------------- TOTAL ----------------

        total_energy = (
            boot_energy
            + tx_energy
            + idle_energy
        )

        results[protocol] = total_energy

        # -------------------------------------------------

        print(f"\n{protocol}")
        print("-" * 40)

        print(f"Boot energy   : {boot_energy:.6e} J")
        print(f"Boot duration : {boot_duration:.6e} s")

        print(f"\nTX energy     : {tx_energy:.6e} J")
        print(f"TX duration   : {tx_duration:.6e} s")

        print(f"\nIdle power    : {idle_power:.6e} W")
        print(f"Idle time     : {idle_time:.6e} s")
        print(f"Idle energy   : {idle_energy:.6e} J")

        print(f"\nTOTAL ENERGY  : {total_energy:.6e} J")

    # =================================================
    # BEST PROTOCOL
    # =================================================

    best_protocol = min(
        results,
        key=results.get
    )

    best_energy = results[best_protocol]

    print("\n=================================================")
    print("BEST PROTOCOL")
    print("=================================================")

    print(
        f"{best_protocol} "
        f"({best_energy:.6e} J)"
    )

    print("\n=================================================")


# =========================================================
# RUN
# =========================================================

def main():

    db = build_database()

    while True:

        run_energy_estimator(db)

        again = input(
            "\nAnother calculation? (y/n): "
        ).strip().lower()

        if again != "y":
            break


if __name__ == "__main__":
    main()