"""
uart_test.py  —  send a small payload directly from Mac to Pico via USB serial,
which forwards it to the nRF via UART, then check if BLE notification arrives.

This bypasses the full experiment to isolate whether the Pico->nRF UART link works.

Run with both Pico and nRF powered and connected.
"""

import asyncio
import serial
import threading
import time
from bleak import BleakClient

PICO_PORT  = "/dev/tty.usbmodem21101"
PICO_BAUD  = 115200

BLE_DEVICE_ADDRESS = "1385E324-4660-24ED-9B2E-A55F8DF154AE"
NUS_TX_CHAR_UUID = "12345678-1234-1234-1234-1234567890ac"

received = []

def on_notify(sender, data: bytearray):
    received.append(bytes(data))
    print(f"[BLE] Got notification: {data[:40]}{'...' if len(data) > 40 else ''} ({len(data)} bytes)")

async def run_test():
    print(f"[1] Connecting to nRF via BLE @ {BLE_DEVICE_ADDRESS}...")
    async with BleakClient(BLE_DEVICE_ADDRESS) as client:
        print(f"[2] BLE connected: {client.is_connected}")
        await client.start_notify(NUS_TX_CHAR_UUID, on_notify)
        print(f"[3] Notifications enabled.")

        print(f"\n[4] Opening Pico serial port {PICO_PORT}...")
        pico = serial.Serial(PICO_PORT, PICO_BAUD, timeout=5)
        time.sleep(2)
        pico.reset_input_buffer()

        # Simulate the go handshake
        print(f"[5] Waiting for Pico READY...")
        deadline = time.time() + 10
        ready = False
        while time.time() < deadline:
            if pico.in_waiting:
                line = pico.readline().decode().strip()
                print(f"    Pico: {line}")
                if line == "READY":
                    ready = True
                    break
            time.sleep(0.05)

        if not ready:
            print("[!] Pico did not send READY — is Pico_ble_full.ino uploaded?")
            pico.close()
            return

        print(f"[6] Sending 'go' to Pico...")
        pico.write(b"go\n")

        # Wait for START_IN
        deadline = time.time() + 5
        while time.time() < deadline:
            if pico.in_waiting:
                line = pico.readline().decode().strip()
                print(f"    Pico: {line}")
                if line.startswith("START_IN_"):
                    break
            time.sleep(0.05)

        print(f"\n[7] Waiting up to 30s for BLE notification (Pico sending 1B payload to nRF)...")
        deadline = time.time() + 30
        while time.time() < deadline:
            if pico.in_waiting:
                line = pico.readline().decode().strip()
                if line:
                    print(f"    Pico: {line}")
            if received:
                break
            time.sleep(0.1)

        if received:
            print(f"\n[OK] UART->BLE pipeline working! Got {len(received)} notification(s).")
            print(f"     First notification: {received[0]}")
        else:
            print(f"\n[!] No BLE notifications received after 30s.")
            print(f"    The Pico->nRF UART link is broken.")
            print(f"    Check: TX->RX crossed, shared GND, correct Serial1 pins.")

        pico.write(b"SKIP\n")
        pico.close()
        await client.stop_notify(NUS_TX_CHAR_UUID)

if __name__ == "__main__":
    asyncio.run(run_test())