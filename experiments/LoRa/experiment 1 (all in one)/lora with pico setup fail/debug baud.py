"""
RN2903 Baud Rate Scanner
------------------------
Tries every common baud rate on the TX module (via Pico bridge)
and prints raw bytes received, to find the correct baud rate.

The Pico bridge UART_BAUD must match whatever baud rate works here.
"""

import serial
import time

PICO_PORT = "/dev/cu.usbmodem141301"   # TX module via Pico
RX_PORT   = "/dev/cu.usbmodem141201"   # RX module direct USB

BAUD_RATES = [57600, 115200, 9600, 19200, 38400, 4800]

def try_baud(port, baud, test_cmd="sys get ver\r\n", wait=2.0):
    print(f"\n  Trying {baud} baud...")
    try:
        s = serial.Serial(port, baud, timeout=wait)
        time.sleep(0.5)
        s.reset_input_buffer()

        s.write(test_cmd.encode())
        time.sleep(wait)

        raw = s.read(s.in_waiting or 1)
        s.close()

        if raw:
            print(f"  RAW bytes: {raw}")
            try:
                decoded = raw.decode("ascii", errors="replace").strip()
                print(f"  Decoded:   {decoded!r}")
            except Exception:
                pass
            return raw
        else:
            print(f"  No response.")
            return None

    except Exception as e:
        print(f"  Error: {e}")
        return None


print("=" * 60)
print("BAUD RATE SCANNER — TX MODULE (via Pico bridge)")
print("=" * 60)
print(f"Port: {PICO_PORT}")
print()
print("NOTE: The Pico Arduino sketch UART_BAUD must be set to")
print("whatever baud rate produces a readable response here.")
print()
print("For each baud rate, we send 'sys get ver' and print")
print("every raw byte that comes back.")
print()

found_baud = None
for baud in BAUD_RATES:
    result = try_baud(PICO_PORT, baud)
    if result and b"RN2903" in result:
        print(f"\n  *** MATCH at {baud} baud! ***")
        found_baud = baud
        break

print()
if found_baud:
    print(f"SUCCESS: TX module responds at {found_baud} baud.")
    print(f"Set UART_BAUD = {found_baud} in your Pico sketch.")
    print(f"Set PICO_BAUD = {found_baud} in your Python scripts.")
else:
    print("No baud rate produced a recognisable RN2903 response.")
    print()
    print("This means one of:")
    print("  1. GP0/GP1 are swapped — RN2903 TX is not reaching Pico GP1")
    print("     Try physically swapping the two wires and re-running.")
    print()
    print("  2. The RN2903 is not powered or is in reset")
    print("     Check 3.3V is present on RN2903 VDD (pin 1)")
    print()
    print("  3. Wrong serial port — confirm Pico is on", PICO_PORT)
    print("     Run: ls /dev/cu.* to list all ports")
    print()

    # Last resort: print raw bytes at most likely baud with no command
    # (just listen for spontaneous boot message)
    print("--- Listening passively at 57600 for 5s (no command sent) ---")
    print("    Power-cycle the RN2903 now if you can...")
    try:
        s = serial.Serial(PICO_PORT, 57600, timeout=5)
        time.sleep(0.3)
        s.reset_input_buffer()
        raw = s.read(200)
        s.close()
        if raw:
            print(f"  RAW: {raw}")
            print(f"  Decoded: {raw.decode('ascii', errors='replace')!r}")
        else:
            print("  Nothing received passively either.")
            print("  The Pico is not forwarding RN2903 output at all.")
    except Exception as e:
        print(f"  Error: {e}")