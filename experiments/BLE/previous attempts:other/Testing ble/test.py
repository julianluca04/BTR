"""
run_test.py
1. Interrupts Pico and writes main.py
2. Uploads nRF sketch
3. Connects to nRF via BLE, listens for GOT: messages, ACKs Pico via USB serial
"""

import os
import shutil
import subprocess
import sys
import time
import serial
import asyncio
from bleak import BleakClient

# ── CONFIG ────────────────────────────────────────────────────────────────────
SKETCH_SRC   = '/Users/foml/coding/MSP/year_3/BTR/experiments/BLE/Testing ble/ble_uart_tx'
FQBN         = 'Seeeduino:nrf52:xiaonRF52840Sense'
NRF_PORT     = '/dev/cu.usbmodem11101'
PICO_PORT    = '/dev/tty.usbmodem11301'
BAUD         = 115200
SAFE_PATH    = '/tmp/ble_uart_tx'
NRF_ADDRESS  = '1385E324-4660-24ED-9B2E-A55F8DF154AE'
NUS_TX_UUID  = '6e400003-b5a3-f393-e0a9-e50e24dcca9e'
# ─────────────────────────────────────────────────────────────────────────────

PICO_CODE = """\
import machine, time, sys, select
led = machine.Pin(25, machine.Pin.OUT)
uart = machine.UART(0, baudrate=115200, tx=machine.Pin(0), rx=machine.Pin(1))
print("READY")
count = 0
while True:
    led.toggle()
    msg = "PING_" + str(count) + "\\n"
    uart.write(msg.encode())
    print("Sent: PING_" + str(count))
    deadline = time.ticks_add(time.ticks_ms(), 5000)
    got_ack = False
    while time.ticks_diff(deadline, time.ticks_ms()) > 0:
        if select.select([sys.stdin], [], [], 0)[0]:
            line = sys.stdin.readline()
            if 'ACK' in line:
                got_ack = True
                count += 1
                break
        time.sleep_ms(10)
    if not got_ack:
        print("Timeout waiting for ACK, retrying PING_" + str(count))
"""


def run(cmd, check=True):
    print(f"$ {' '.join(cmd)}")
    result = subprocess.run(cmd, text=True)
    if check and result.returncode != 0:
        print(f"[!] Failed (exit {result.returncode})")
        sys.exit(result.returncode)
    return result.returncode


def write_pico_via_raw_repl():
    print("[→] Interrupting Pico and writing main.py via raw REPL...")
    with serial.Serial(PICO_PORT, BAUD, timeout=2) as ser:
        for _ in range(20):
            ser.write(b'\x03')
            time.sleep(0.05)
        time.sleep(0.5)
        ser.reset_input_buffer()
        ser.write(b'\x01')
        time.sleep(0.5)
        response = ser.read(ser.in_waiting)
        print(f"[raw repl response] {response}")
        if b'raw REPL' not in response:
            print("[!] Could not enter raw REPL — trying Ctrl+D then Ctrl+A...")
            ser.write(b'\x04')
            time.sleep(2)
            ser.write(b'\x01')
            time.sleep(0.5)
            response = ser.read(ser.in_waiting)
            print(f"[raw repl response 2] {response}")
        escaped = PICO_CODE.replace('\\', '\\\\').replace("'", "\\'").replace('\n', '\\n')
        cmd = f"f=open('main.py','w');f.write('{escaped}');f.close()\x04"
        ser.write(cmd.encode())
        time.sleep(2)
        response = ser.read(ser.in_waiting)
        print(f"[write response] {response}")
        ser.write(b'\x02')  # Ctrl+B: exit raw REPL
        time.sleep(0.5)
        ser.write(b'\x04')  # Ctrl+D: soft reboot into main.py
        time.sleep(2)
        print("[✓] Pico main.py written and restarted.")


def upload_nrf():
    if os.path.exists(SAFE_PATH):
        shutil.rmtree(SAFE_PATH)
    shutil.copytree(SKETCH_SRC, SAFE_PATH)
    print(f"[→] Copied sketch to {SAFE_PATH}")

    for stale in ['nrfx_uarte.c', 'nrfx_uarte.cpp']:
        stale_path = os.path.join(SAFE_PATH, stale)
        if os.path.exists(stale_path):
            os.remove(stale_path)

    ino = os.path.join(SAFE_PATH, 'ble_uart_tx.ino')
    if not os.path.exists(ino):
        print(f"[!] .ino not found at {ino}")
        sys.exit(1)

    print("\n[1/2] Compiling...")
    run(["arduino-cli", "compile", "--fqbn", FQBN, SAFE_PATH])

    print(f"\n[2/2] Uploading to {NRF_PORT}...")
    rc = run(["arduino-cli", "upload", "-p", NRF_PORT, "-b", FQBN, SAFE_PATH], check=False)
    if rc != 0:
        print("\n[!] Upload failed — double-tap reset, wait for pulse, press ENTER")
        input("    → ")
        time.sleep(1)
        run(["arduino-cli", "upload", "-p", NRF_PORT, "-b", FQBN, SAFE_PATH])

    print("\n[✓] Upload done. Waiting 5s for nRF to boot and advertise...")
    time.sleep(5)


async def ble_listen():
    print(f"\n[→] Connecting to nRF via BLE ({NRF_ADDRESS})...")
    pico_ser = serial.Serial(PICO_PORT, BAUD, timeout=1)
    async with BleakClient(NRF_ADDRESS) as client:
        print(f"[✓] BLE connected: {client.is_connected}")

        def notification_handler(sender, data):
            msg = data.decode('utf-8', errors='replace').strip()
            print(f"[BLE] Received: '{msg}'")
            if msg.startswith("GOT:PING_"):
                pico_ser.write(b'ACK\n')
                print(f"[→] ACK sent to Pico")

        await client.start_notify(NUS_TX_UUID, notification_handler)
        print("[✓] Subscribed to NUS TX. Waiting for GOT: messages (Ctrl+C to stop)...\n")
        try:
            while True:
                await asyncio.sleep(1)
        except KeyboardInterrupt:
            pass
        await client.stop_notify(NUS_TX_UUID)
        pico_ser.close()
        print("[→] Done.")


if __name__ == "__main__":
    write_pico_via_raw_repl()
    upload_nrf()
    asyncio.run(ble_listen())