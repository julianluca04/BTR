"""
RN2903 Diagnostic Script
------------------------
Run this standalone BEFORE the main experiment.
It will:
  1. Reset the module and print everything it says
  2. Configure LoRa radio parameters step by step
  3. Send a minimal 1-byte test transmission
  4. Print every line the module replies with

Edit PICO_PORT to match your TX module's serial port.
"""

import serial
import time

# ── Edit these to match your setup ──────────────────────────
PICO_PORT = "/dev/cu.usbmodem141301"   # TX RN2903
PICO_BAUD = 57600
RX_PORT   = "/dev/cu.usbmodem143201"   # RX RN2903
RX_BAUD   = 57600
# ─────────────────────────────────────────────────────────────

def send_and_print(ser, cmd, wait=1.5, label=None):
    label = label or cmd
    print(f"\n>>> {label}")
    ser.reset_input_buffer()
    ser.write((cmd + "\r\n").encode())
    time.sleep(wait)
    responses = []
    while ser.in_waiting:
        line = ser.readline().decode(errors="ignore").strip()
        if line:
            print(f"    <- {line!r}")
            responses.append(line)
    return responses

def drain(ser, duration=0.5):
    """Read and print everything arriving within `duration` seconds."""
    deadline = time.time() + duration
    while time.time() < deadline:
        if ser.in_waiting:
            line = ser.readline().decode(errors="ignore").strip()
            if line:
                print(f"    <- {line!r}")
        else:
            time.sleep(0.02)

print("=" * 60)
print("RN2903 TX MODULE DIAGNOSTIC")
print("=" * 60)

pico = serial.Serial(PICO_PORT, PICO_BAUD, timeout=2)
time.sleep(2)
pico.reset_input_buffer()

# ── Step 1: Identity check ───────────────────────────────────
print("\n[1] Resetting and identifying module...")
send_and_print(pico, "sys reset", wait=2.0, label="sys reset")
send_and_print(pico, "sys get ver", label="sys get ver")
send_and_print(pico, "sys get hweui", label="sys get hweui")

# ── Step 2: Configure radio ──────────────────────────────────
print("\n[2] Configuring radio parameters...")
send_and_print(pico, "mac pause",              label="mac pause")
send_and_print(pico, "radio set mod lora",     label="radio set mod lora")
send_and_print(pico, "radio set freq 915000000", label="radio set freq")
send_and_print(pico, "radio set sf sf7",       label="radio set sf sf7")
send_and_print(pico, "radio set bw 125",       label="radio set bw 125")
send_and_print(pico, "radio set cr 4/5",       label="radio set cr 4/5")
send_and_print(pico, "radio set pwr 14",       label="radio set pwr 14")
send_and_print(pico, "radio set crc on",       label="radio set crc on")

# ── Step 3: Verify settings ──────────────────────────────────
print("\n[3] Verifying radio settings...")
for param in ["mod", "freq", "sf", "bw", "cr", "pwr", "crc"]:
    send_and_print(pico, f"radio get {param}", wait=0.5, label=f"radio get {param}")

# ── Step 4: Test TX ──────────────────────────────────────────
print("\n[4] Sending test TX (1 byte = 0x30)...")
send_and_print(pico, "radio rxstop", wait=0.3, label="radio rxstop")

pico.reset_input_buffer()
pico.write(("radio tx 30\r\n").encode())
print(">>> radio tx 30")

# Wait up to 15 seconds for response
print("    Waiting for response (up to 15s)...")
deadline = time.time() + 15
got_any = False
while time.time() < deadline:
    if pico.in_waiting:
        line = pico.readline().decode(errors="ignore").strip()
        if line:
            print(f"    <- {line!r}")
            got_any = True
            if line in ("radio_tx_ok", "radio_err") or "invalid" in line:
                break
    else:
        time.sleep(0.05)

if not got_any:
    print("    !! NO RESPONSE after 15s — module may not be receiving serial commands")

# ── Step 5: Check RX module ──────────────────────────────────
print("\n[5] Checking RX module...")
rx = serial.Serial(RX_PORT, RX_BAUD, timeout=2)
time.sleep(2)
rx.reset_input_buffer()

send_and_print(rx, "sys reset", wait=2.0, label="sys reset")
send_and_print(rx, "sys get ver", label="sys get ver")

print("\n    Configuring RX radio...")
send_and_print(rx, "mac pause")
send_and_print(rx, "radio set mod lora")
send_and_print(rx, "radio set freq 915000000")
send_and_print(rx, "radio set sf sf7")
send_and_print(rx, "radio set bw 125")
send_and_print(rx, "radio set cr 4/5")
send_and_print(rx, "radio set crc on")

print("\n    Opening RX window (listening for 10s)...")
send_and_print(rx, "radio rx 0", wait=0.5, label="radio rx 0")

print("    Sending another TX from TX module...")
pico.reset_input_buffer()
pico.write(("radio rxstop\r\n").encode())
time.sleep(0.3)
pico.write(("radio tx 48454C4C4F\r\n").encode())  # "HELLO"
print(">>> radio tx HELLO")

# Listen on both for 10 seconds
deadline = time.time() + 10
while time.time() < deadline:
    if pico.in_waiting:
        line = pico.readline().decode(errors="ignore").strip()
        if line:
            print(f"    [TX module] <- {line!r}")
    if rx.in_waiting:
        line = rx.readline().decode(errors="ignore").strip()
        if line:
            print(f"    [RX module] <- {line!r}")
    time.sleep(0.01)

print("\n" + "=" * 60)
print("DIAGNOSTIC COMPLETE")
print("=" * 60)
print("""
What to look for:
  - Step 1: Should see firmware version string (e.g. 'RN2903 1.0.5 ...')
            If you see nothing or garbled text → baud rate or wiring issue
  - Step 2/3: Each command should reply 'ok'
              Any 'invalid_param' means a config problem
  - Step 4: Should see 'ok' then 'radio_tx_ok'
            'radio_err' means the radio couldn't transmit (check freq/power)
            No response means serial TX→RX wiring issue on the Pico side
  - Step 5: RX module should print 'radio_rx  48454C4C4F' or similar
            If TX ok but RX gets nothing → frequency/SF mismatch or antenna issue
""")

pico.close()
rx.close()