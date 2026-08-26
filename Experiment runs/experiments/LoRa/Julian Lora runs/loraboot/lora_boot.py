import serial
import time
import csv
import os
import pyvisa
import threading
from datetime import datetime

# --- CONFIGURATION ---
TX_PORT = "/dev/cu.usbmodem11301"  
BAUD_LORA = 57600
DMM_ADDR = 'USB0::2733::309::020633987::0::INSTR'
TOTAL_BOOT_RUNS = 30

# Setup Directory
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SESSION_TAG = datetime.now().strftime("%Y%m%d_%H%M%S")
OUT_DIR = os.path.join(SCRIPT_DIR, "data", "LoRa", "boot_energy", SESSION_TAG)
os.makedirs(OUT_DIR, exist_ok=True)

_current_phase = "no_power"
_phase_lock = threading.Lock()

def set_phase(phase):
    global _current_phase
    with _phase_lock:
        _current_phase = phase

def meter_stream(meter, csv_writer, stop_event, file_handle):
    while not stop_event.is_set():
        try:
            # Simple read
            val = meter.query("READ?").strip()
            ts = datetime.now().isoformat(timespec="milliseconds")
            with _phase_lock:
                phase = _current_phase
            csv_writer.writerow([ts, val, phase])
            file_handle.flush() 
        except Exception:
            pass

def run_boot_experiment(run_num, meter):
    filename = os.path.join(OUT_DIR, f"LoRa_Boot_Run_{run_num:02d}.csv")
    stop_meter = threading.Event()
    
    print(f"\n{'='*40}")
    print(f" PREPARING RUN {run_num}/{TOTAL_BOOT_RUNS}")
    print(f"{'='*40}")
    print("1. UNPLUG the LoRa module.")
    input("2. Press ENTER when it is unplugged...")

    with open(filename, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["# META", f"Run_{run_num}"])
        writer.writerow(["timestamp", "v_shunt", "phase"])
        
        m_thread = threading.Thread(target=meter_stream, args=(meter, writer, stop_meter, f))
        m_thread.start()

        # Step 1: Baseline
        set_phase("unplugged_baseline")
        print("[→] Recording baseline (3s)...")
        time.sleep(3)

        # Step 2: Physical Plug-in
        set_phase("wait_for_plug")
        print(f"\n[!!!] PLUG IN THE LORA MODULE NOW (Run {run_num})")
        
        tx_ser = None
        while tx_ser is None:
            try:
                tx_ser = serial.Serial(TX_PORT, BAUD_LORA, timeout=0.1)
                print("[✓] Connection Detected!")
            except:
                time.sleep(0.1)

        # Step 3: MCU Boot
        set_phase("boot_initialization")
        print("[→] Capturing hardware boot (4s)...")
        time.sleep(4)

        # Step 4: Software Config
        set_phase("software_setup_config")
        print("[→] Running Setup Commands...")
        tx_ser.write(b"sys reset\r\n")
        time.sleep(4.0)
        
        cmds = [
            "mac pause", "radio set mod lora", "radio set freq 915000000",
            "radio set sf sf8", "radio set bw 500", "radio set pwr 14", "radio set crc on"
        ]
        for c in cmds:
            tx_ser.write((c + "\r\n").encode())
            time.sleep(0.2)

        # Step 5: Final Idle
        set_phase("configured_idle")
        print("[→] Recording stable idle (3s)...")
        time.sleep(3)

        print(f"[✓] Run {run_num} Complete.")
        stop_meter.set()
        m_thread.join()
        tx_ser.close()

if __name__ == "__main__":
    rm = pyvisa.ResourceManager('@py')
    try:
        # Simplified Init to avoid VI_ERROR_NSUP_OPER
        meter = rm.open_resource(DMM_ADDR)
        meter.timeout = 5000 
        
        # We only use standard SCPI commands now
        meter.write("*RST") # Reset meter to default
        time.sleep(0.5)
        meter.write("CONF:VOLT:DC")
        meter.write("SENS:VOLT:DC:NPLC 0.02") 
        
        idn = meter.query("*IDN?").strip()
        print(f"[Meter] Connected: {idn}")
    except Exception as e:
        print(f"DMM Error: {e}")
        print("\nPossible fix: Run 'lsusb' or 'system_profiler SPUSBDataType' to check if Mac sees the DMM.")
        exit()

    try:
        for r in range(1, TOTAL_BOOT_RUNS + 1):
            run_boot_experiment(r, meter)
    finally:
        print("\n[FINISH] All cycles recorded.")
        try:
            meter.close()
        except:
            pass