import serial
import time
import csv
import os
import pyvisa
import threading
from datetime import datetime

# --- CONFIGURATION ---
TX_PORT = "/dev/cu.usbmodem11301"  
RX_PORT = "/dev/cu.usbmodem21201"  
BAUD_LORA = 57600
DMM_ADDR = 'USB0::2733::309::020633987::0::INSTR'

PAYLOAD_SIZES = [1, 2, 4, 8, 16, 32, 64, 128, 220]
TOTAL_RUNS = 30
IDLE_S = 1.0        
BASELINE_S = 5.0    

# Setup Directory
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SESSION_TAG = datetime.now().strftime("%Y%m%d_%H%M%S")
OUT_DIR = os.path.join(SCRIPT_DIR, "data", "LoRa", "full_payload", SESSION_TAG)
os.makedirs(OUT_DIR, exist_ok=True)

# --- GLOBAL PHASE TRACKING ---
_current_phase = "idle"
_phase_lock = threading.Lock()

def set_phase(phase):
    global _current_phase
    with _phase_lock:
        _current_phase = phase

# --- METER STREAMING ---
def meter_stream(meter, csv_writer, stop_event, file_handle):
    while not stop_event.is_set():
        try:
            val = meter.query("READ?").strip()
            ts = datetime.now().isoformat(timespec="milliseconds")
            with _phase_lock:
                phase = _current_phase
            csv_writer.writerow([ts, val, phase])
            file_handle.flush() 
        except Exception:
            pass

# --- LORA UTILITIES ---
def cmd(ser, command):
    ser.write((command + "\r\n").encode())
    time.sleep(0.2)

def configure_loras(tx, rx):
    print("\n[→] Initializing LoRa Hardware...")
    tx.write(b"sys reset\r\n")
    rx.write(b"sys reset\r\n")
    time.sleep(4.0)
    for s in [tx, rx]:
        s.reset_input_buffer()
        cmd(s, "mac pause")
        cmd(s, "radio set mod lora")
        cmd(s, "radio set freq 915000000")
        cmd(s, "radio set sf sf8")
        cmd(s, "radio set bw 500")
        cmd(s, "radio set pwr 14")
        cmd(s, "radio set crc on")
    print("[✓] LoRa Hardware Ready.")

# --- EXPERIMENT ORCHESTRATION ---
def run_one_experiment(run_num, meter, tx_ser):
    filename = os.path.join(OUT_DIR, f"LoRa_run{run_num:02d}.csv")
    stop_meter = threading.Event()
    
    with open(filename, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["# META"])
        writer.writerow(["module", "LoRa_RN2903"])
        writer.writerow(["run", run_num])
        writer.writerow(["session", SESSION_TAG])
        writer.writerow([])
        writer.writerow(["# METER"])
        writer.writerow(["timestamp", "v_shunt", "phase"])
        f.flush()
        
        m_thread = threading.Thread(target=meter_stream, args=(meter, writer, stop_meter, f))
        m_thread.start()

        # 1. Baseline
        print(f"\n[Run {run_num:02d}] Recording {BASELINE_S}s Baseline...")
        set_phase("baseline")
        time.sleep(BASELINE_S)

        # 2. Transmission Loop
        for size in PAYLOAD_SIZES:
            hex_payload = ("{:02X}".format(size % 256)) * size
            
            print(f"  [{size:>3}B] Loading & Sending...", end=" ", flush=True)
            tx_ser.reset_input_buffer()
            
            # --- START ACTIVE PHASE ---
            # The phase begins as the Mac starts pushing the payload into the LoRa buffer
            set_phase(f"tx_{size}")
            tx_ser.write(f"radio tx {hex_payload}\r\n".encode())
            
            # Wait for Hardware acknowledgment
            # The RN2903 will say 'ok' once buffered, and 'radio_tx_ok' once sent.
            tx_finished_physically = False
            deadline = time.time() + 15.0 # Increased deadline for 220B payloads
            
            while time.time() < deadline:
                if tx_ser.in_waiting:
                    line = tx_ser.readline().decode(errors='ignore').strip()
                    
                    # 'radio_tx_ok' is the signal that the entire package has left the antenna
                    if "radio_tx_ok" in line:
                        tx_finished_physically = True
                        break
                    elif "invalid_param" in line or "radio_err" in line:
                        print(f"ERROR ({line})", end=" ")
                        break
            
            # --- END ACTIVE PHASE ---
            set_phase("idle")
            
            if tx_finished_physically:
                print("SUCCESS")
            else:
                print("TIMEOUT (Assumed Done)")
            
            # 1 second of recovery/idle energy recording
            time.sleep(IDLE_S)

        # Shutdown run
        stop_meter.set()
        m_thread.join()
        print(f"[✓] Run {run_num:02d} Saved.")

if __name__ == "__main__":
    rm = pyvisa.ResourceManager('@py')
    try:
        meter = rm.open_resource(DMM_ADDR)
        meter.timeout = 10000 
        meter.write("*CLS")
        time.sleep(0.5)
        meter.write("CONF:VOLT:DC")
        meter.write("SENS:VOLT:DC:NPLC 0.02") 
        print(f"[Meter] Connected: {meter.query('*IDN?').strip()}")
    except Exception as e:
        print(f"DMM Error: {e}")
        exit()

    tx_ser = serial.Serial(TX_PORT, BAUD_LORA, timeout=0.1)
    rx_ser = serial.Serial(RX_PORT, BAUD_LORA, timeout=0.1)

    configure_loras(tx_ser, rx_ser)

    try:
        for r in range(1, TOTAL_RUNS + 1):
            run_one_experiment(r, meter, tx_ser)
    finally:
        print("\nAll experiments complete.")
        tx_ser.close()
        rx_ser.close()
        meter.close()