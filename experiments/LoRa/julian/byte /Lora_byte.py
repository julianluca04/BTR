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

# Doubling progression: [1, 2, 4, 8, 16, 32, 64, 128, 256, 512, 1024, 2048, 4096, 8192, 16384]
TOTAL_SIZES = [2**i for i in range(15)] 
TOTAL_RUNS = 30
IDLE_S = 1.0        
BASELINE_S = 5.0    

# Setup Directory
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SESSION_TAG = datetime.now().strftime("%Y%m%d_%H%M%S")
OUT_DIR = os.path.join(SCRIPT_DIR, "data", "LoRa", "single_byte_fragments", SESSION_TAG)
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
    time.sleep(0.1) 

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

# --- EXPERIMENT ORCHESTRATION ---
def run_one_experiment(run_num, meter, tx_ser):
    filename = os.path.join(OUT_DIR, f"LoRa_1B_run{run_num:02d}.csv")
    stop_meter = threading.Event()
    
    with open(filename, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["# META"])
        writer.writerow(["module", "LoRa_RN2903"])
        writer.writerow(["strategy", "single_byte_fragmentation"])
        writer.writerow(["run", run_num])
        writer.writerow([])
        writer.writerow(["# METER"])
        writer.writerow(["timestamp", "v_shunt", "phase"])
        f.flush()
        
        m_thread = threading.Thread(target=meter_stream, args=(meter, writer, stop_meter, f))
        m_thread.start()

        # 1. Baseline
        set_phase("baseline")
        time.sleep(BASELINE_S)

        # 2. Main Message Loop
        for total_bytes in TOTAL_SIZES:
            print(f"\n  [Run {run_num}] Total Message: {total_bytes} bytes (1B at a time)")
            set_phase(f"tx_{total_bytes}")
            
            bytes_sent = 0
            
            while bytes_sent < total_bytes:
                # Strictly 1 byte sent over serial to the module
                hex_payload = "AA"
                
                tx_ser.reset_input_buffer()
                tx_ser.write(f"radio tx {hex_payload}\r\n".encode())
                
                # Handshake: The "Atomic" 1-byte send
                tx_confirmed = False
                deadline = time.time() + 5.0
                while time.time() < deadline:
                    if tx_ser.in_waiting:
                        line = tx_ser.readline().decode(errors='ignore').strip()
                        if "radio_tx_ok" in line:
                            tx_confirmed = True
                            break
                
                bytes_sent += 1
                if bytes_sent % 10 == 0 or bytes_sent == total_bytes:
                    print(f"    Progress: {bytes_sent}/{total_bytes} bytes", end="\r")

            # 3. Message Complete - Idle recovery
            print(f"\n    {total_bytes}B Done. Entering {IDLE_S}s Idle.")
            set_phase("idle")
            time.sleep(IDLE_S)

        stop_meter.set()
        m_thread.join()

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
        
        