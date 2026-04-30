import serial
import time

TX_PORT = "/dev/cu.usbmodem1201"
RX_PORT = "/dev/cu.usbmodem11301"
BAUD = 57600

PAYLOAD_SIZES = [1, 2, 4, 8, 16, 32, 64, 128, 220]
TX_TIMEOUT = 5.0
RX_TIMEOUT = 5.0

def readline(ser, timeout=2.0):
    deadline = time.time() + timeout
    buf = b""
    while time.time() < deadline:
        if ser.in_waiting:
            ch = ser.read(1)
            buf += ch
            if buf.endswith(b"\r\n"):
                return buf.decode(errors="ignore").strip()
        else:
            time.sleep(0.002)
    return buf.decode(errors="ignore").strip()

def cmd(ser, command, timeout=1.0):
    ser.reset_input_buffer()
    ser.write((command + "\r\n").encode())
    time.sleep(0.15) # Increased for chip stability
    return readline(ser, timeout=timeout)

def hard_reset_all(tx, rx):
    print("--- PERFORMING HARD HARDWARE RESET ---")
    tx.write(b"sys reset\r\n")
    rx.write(b"sys reset\r\n")
    time.sleep(2.5)
    configure_radios(tx, rx)

def configure_radios(tx_ser, rx_ser):
    for s in [tx_ser, rx_ser]:
        cmd(s, "mac pause")
        cmd(s, "radio set mod lora")
        cmd(s, "radio set freq 915000000")
        cmd(s, "radio set sf sf8")       # Switched to SF8 for better desk stability
        cmd(s, "radio set bw 500")
        cmd(s, "radio set cr 4/5")
        cmd(s, "radio set pwr 2")
        cmd(s, "radio set crc on")
        cmd(s, "radio set prlen 12")     # Longer preamble for better sync lock
        cmd(s, "radio set sync 12")
    print("Configuration applied.")

if __name__ == "__main__":
    tx_ser = serial.Serial(TX_PORT, BAUD, timeout=0)
    rx_ser = serial.Serial(RX_PORT, BAUD, timeout=0)

    hard_reset_all(tx_ser, rx_ser)

    print("\n===== STARTING RELIABLE PIPELINE =====\n")
    passed_count = 0

    for i, size in enumerate(PAYLOAD_SIZES):
        char = chr(ord('A') + (i % 26))
        payload_hex = (char.encode().hex() * size).upper()
        print(f"TEST {i+1} ({size}B):", end=" ", flush=True)

        test_success = False
        consecutive_errors = 0
        
        for attempt in range(1, 16): 
            # If we keep failing, reset the hardware entirely
            if consecutive_errors >= 4:
                print("(Resetting HW)", end=" ", flush=True)
                hard_reset_all(tx_ser, rx_ser)
                consecutive_errors = 0

            tx_ser.write(b"radio rxstop\r\n")
            rx_ser.write(b"radio rxstop\r\n")
            time.sleep(0.2)
            
            tx_ser.reset_input_buffer()
            rx_ser.reset_input_buffer()

            cmd(rx_ser, "radio rx 0")
            time.sleep(0.2) 

            tx_ser.write(f"radio tx {payload_hex}\r\n".encode())
            
            received_val = None
            rx_deadline = time.time() + RX_TIMEOUT
            while time.time() < rx_deadline:
                line = readline(rx_ser, timeout=0.5)
                if line:
                    if line.startswith("radio_rx"):
                        parts = line.split()
                        if len(parts) > 1:
                            received_val = parts[1].upper()
                        break
                    elif "radio_err" in line:
                        print("X", end="", flush=True)
                        consecutive_errors += 1
                        time.sleep(0.4) 
                        break
            
            if received_val == payload_hex:
                print(f" [A{attempt}: PASS]")
                passed_count += 1
                test_success = True
                time.sleep(1.0) # VITAL: Cool-down after success
                break
        
        if not test_success:
            print(" [FAILED]")

    tx_ser.close()
    rx_ser.close()