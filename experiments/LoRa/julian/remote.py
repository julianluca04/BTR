import serial
import time

# Update to your RX port
ser = serial.Serial("/dev/cu.usbmodem11301", 57600, timeout=1)

def cmd(c):
    ser.write((c + "\r\n").encode())
    return ser.readline().decode().strip()

print("Configuring Battery-Powered TX...")
cmd("sys reset")
time.sleep(2)
cmd("mac pause")
cmd("radio set pwr 2")       # Low power is best for indoor distance
cmd("radio set sf sf8")       # Reliable spreading factor
cmd("radio set bw 125")       # Standard bandwidth for better sensitivity
cmd("radio set prlen 12")
cmd("radio set freq 915000000")

counter = 1
print("Beacon Active! Switch to Battery Power and move the device.")

try:
    while True:
        # Payload: 'DATA' (44415441) + 4-digit hex counter
        count_hex = format(counter, '04x')
        payload = f"44415441{count_hex}"
        
        cmd(f"radio tx {payload}")
        print(f"Sent: DATA_{counter}")
        
        counter += 1
        if counter > 9999: counter = 1
        time.sleep(2.0) # Send every 2 seconds to keep it clean
except:
    ser.close()