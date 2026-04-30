import serial
import time

# Update to your RX port
rx = serial.Serial("/dev/cu.usbmodem11301", 57600, timeout=1)

def cmd(c):
    rx.write((c + "\r\n").encode())
    return rx.readline().decode().strip()

print("Initializing Stationary RX...")
cmd("sys reset")
time.sleep(2)
cmd("mac pause")
cmd("radio set freq 915000000")
cmd("radio set sf sf8")
cmd("radio set bw 125")
cmd("radio set prlen 12")
cmd("radio set crc on")
cmd("radio rx 0") # Continuous RX

last_count = None

print("\n--- DATA LOGGING STARTED ---")
try:
    while True:
        line = rx.readline().decode(errors='ignore').strip()
        if line.startswith("radio_rx"):
            raw_hex = line.split()[1].upper()
            
            # Verify the 'DATA' prefix (44415441)
            if raw_hex.startswith("44415441"):
                count_hex = raw_hex[8:]
                current_count = int(count_hex, 16)
                
                # Check for dropped packets
                gap = ""
                if last_count is not None and current_count != last_count + 1:
                    missed = current_count - last_count - 1
                    gap = f" | !!! MISSED {missed} PACKETS !!!"
                
                print(f"[{time.strftime('%H:%M:%S')}] RECEIVED: DATA_{current_count:04d}{gap}")
                last_count = current_count
            else:
                print(f"INVALID DATA: {raw_hex}")
        elif "radio_err" in line:
            print("--- Radio Interference Detected ---")
except KeyboardInterrupt:
    rx.close()