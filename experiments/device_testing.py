import pyvisa
import time

def measure():
    rm = pyvisa.ResourceManager('@py')

    def reopen_meter(retries=5, delay=1.0):
        for attempt in range(retries):
            try:
                resources = rm.list_resources()
                print(f"[Meter] Found: {resources}")
                hmc = next((r for r in resources if r.startswith("USB")), None)
                if not hmc:
                    raise RuntimeError(f"HMC8012 not found. Available: {resources}")
                m = rm.open_resource(hmc)
                m.timeout = 10000
                print(f"[Meter] {m.query('*IDN?').strip()}")
                return m
            except Exception as e:
                print(f"[Meter] Connect attempt {attempt+1}/{retries} failed: {e}")
                time.sleep(delay)
        raise RuntimeError("[Meter] Could not connect after retries.")

    # ── Shunt resistance ──────────────────────────────────────────────────────
    input("\n[Shunt] Connect probes across shunt resistor then press ENTER...")
    meter = reopen_meter()
    meter.write("CONF:RES")
    meter.write("SENS:RES:RANG:AUTO ON")
    meter.write("SENS:RES:NPLC 0.1")
    time.sleep(0.2)
    shunt_samples = []
    for i in range(20):
        try:
            shunt_samples.append(float(meter.query("READ?").strip()))
        except Exception as e:
            print(f"[Shunt] Read error: {e}")
        time.sleep(0.05)
    avg_shunt = sum(shunt_samples) / len(shunt_samples) if shunt_samples else 0.0
    print(f"[Shunt] {len(shunt_samples)} samples → avg: {avg_shunt:.6f} Ω")

    # ── VBUS ──────────────────────────────────────────────────────────────────
    try:
        meter.close()
    except Exception:
        pass
    time.sleep(0.5)

    input("\n[VBUS] Connect probes to supply voltage then press ENTER...")
    meter = reopen_meter()
    meter.write("CONF:VOLT:DC")
    meter.write("SENS:VOLT:DC:RANG:AUTO ON")
    meter.write("SENS:VOLT:DC:NPLC 0.1")
    time.sleep(0.2)
    vbus_samples = []
    for i in range(20):
        try:
            vbus_samples.append(float(meter.query("READ?").strip()))
        except Exception as e:
            print(f"[VBUS] Read error: {e}")
        time.sleep(0.05)
    avg_vbus = sum(vbus_samples) / len(vbus_samples) if vbus_samples else 0.0
    print(f"[VBUS]  {len(vbus_samples)} samples → avg: {avg_vbus:.6f} V")

    try:
        meter.close()
    except Exception:
        pass

    # ── Summary ───────────────────────────────────────────────────────────────
    print("\n─── Results ───────────────────────────────")
    print(f"  SHUNT_OHMS = {avg_shunt:.6f}")
    print(f"  V_SUPPLY   = {avg_vbus:.6f}")
    print("───────────────────────────────────────────")
    print("Copy these into the config block of your experiment script.")

if __name__ == "__main__":
    measure()
    