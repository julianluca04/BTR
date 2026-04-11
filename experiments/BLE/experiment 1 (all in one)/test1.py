import asyncio
import os
import serial
import shutil
import subprocess
import threading
import time
from datetime import datetime
from bleak import BleakClient

# ─── CONFIG ───────────────────────────────────────────────────────────────────
PAYLOAD_SIZES = [
    1, 2, 4, 8, 16, 32, 64, 128, 256, 512,
    1024, 2048, 4096, 8192, 16384, 32768, 65536,
    131072
]

PICO_PORT     = "/dev/tty.usbmodem11301"
PICO_BAUD     = 115200
NRF_ADDRESS   = "1385E324-4660-24ED-9B2E-A55F8DF154AE"
NUS_TX_UUID   = "6e400003-b5a3-f393-e0a9-e50e24dcca9e"

NRF_SKETCH_SRC  = '/Users/foml/coding/MSP/year_3/BTR/experiments/BLE/experiment 1 (all in one)/ble_1'
NRF_FQBN        = 'Seeeduino:nrf52:xiaonRF52840Sense'
NRF_PORT        = '/dev/cu.usbmodem11101'
SAFE_BUILD_BASE = '/tmp/ble_upload_tmp'

PICO_SKETCH_SRC = '/Users/foml/coding/MSP/year_3/BTR/experiments/BLE/experiment 1 (all in one)/Pico_1'
PICO_FQBN       = 'arduino:mbed_rp2040:pico'
# ─────────────────────────────────────────────────────────────────────────────


def run_cmd(cmd, check=True):
    print(f"$ {' '.join(cmd)}")
    result = subprocess.run(cmd, text=True)
    if check and result.returncode != 0:
        raise RuntimeError(f"Command failed: {' '.join(cmd)}")
    return result.returncode


def upload_nrf():
    print("\n[→] Uploading nRF sketch...")
    sketch = NRF_SKETCH_SRC
    if " " in sketch or "(" in sketch or ")" in sketch:
        name = os.path.basename(os.path.normpath(sketch))
        safe = os.path.join(SAFE_BUILD_BASE, name)
        if os.path.exists(safe): shutil.rmtree(safe)
        shutil.copytree(sketch, safe)
        sketch = safe
    run_cmd(["arduino-cli", "compile", "--fqbn", NRF_FQBN, sketch])
    rc = run_cmd(["arduino-cli", "upload", "-p", NRF_PORT, "-b", NRF_FQBN, sketch], check=False)
    if rc != 0:
        print("[!] Upload failed — double-tap reset, press ENTER")
        input("    → ")
        time.sleep(1)
        run_cmd(["arduino-cli", "upload", "-p", NRF_PORT, "-b", NRF_FQBN, sketch])
    print("[✓] nRF uploaded. Waiting 5s...")
    time.sleep(5)


def upload_pico():
    print("\n[→] Uploading Pico sketch...")
    sketch = PICO_SKETCH_SRC
    if " " in sketch or "(" in sketch or ")" in sketch:
        name = os.path.basename(os.path.normpath(sketch))
        safe = os.path.join(SAFE_BUILD_BASE, name)
        if os.path.exists(safe): shutil.rmtree(safe)
        shutil.copytree(sketch, safe)
        sketch = safe
    run_cmd(["arduino-cli", "compile", "--fqbn", PICO_FQBN, sketch])
    rc = run_cmd(["arduino-cli", "upload", "-p", PICO_PORT.replace("tty.", "cu."),
                  "-b", PICO_FQBN, sketch], check=False)
    if rc != 0:
        print("[!] Pico upload failed, press ENTER to retry")
        input("    → ")
        run_cmd(["arduino-cli", "upload", "-p", PICO_PORT.replace("tty.", "cu."),
                 "-b", PICO_FQBN, sketch])
    print("[✓] Pico uploaded. Waiting 3s...")
    time.sleep(3)


def wait_for_pico(pico, expected, timeout=20):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if pico.in_waiting:
            line = pico.readline().decode(errors='replace').strip()
            if line: print(f"[Pico] {line}")
            if line == expected: return True
        else:
            time.sleep(0.05)
    return False


def verify_payload(payload: bytes, payload_size: int, index: int) -> bool:
    expected_byte = ord('0') + (index % 10)
    if len(payload) != payload_size:
        print(f"  [!] Size mismatch: expected {payload_size}B got {len(payload)}B")
        return False
    wrong = sum(1 for b in payload if b != expected_byte)
    if wrong > 0:
        print(f"  [!] Content mismatch: {wrong}/{len(payload)} bytes wrong")
        return False
    return True


class BLEReceiver:
    def __init__(self):
        self._buf       = bytearray()
        self._lock      = threading.Lock()
        self._new_data  = threading.Event()

    def handler(self, sender, data: bytearray):
        with self._lock:
            self._buf.extend(data)
        self._new_data.set()

    def read_until(self, marker: bytes, timeout=30):
        deadline = time.time() + timeout
        while time.time() < deadline:
            with self._lock:
                idx = self._buf.find(marker)
                if idx != -1:
                    result = bytes(self._buf[:idx])
                    del self._buf[:idx + len(marker)]
                    return result
            self._new_data.clear()
            self._new_data.wait(timeout=0.5)
        return None

    def read_exact(self, n: int, timeout=60):
        deadline = time.time() + timeout
        while time.time() < deadline:
            with self._lock:
                if len(self._buf) >= n:
                    result = bytes(self._buf[:n])
                    del self._buf[:n]
                    return result
            self._new_data.clear()
            self._new_data.wait(timeout=0.5)
        return None

    def clear(self):
        with self._lock:
            self._buf.clear()


async def run_test_async(pico):
    print(f"\n[Test] Connecting to nRF via BLE...")
    async with BleakClient(NRF_ADDRESS) as client:
        print(f"[BLE] Connected: {client.is_connected}")

        receiver = BLEReceiver()
        await client.start_notify(NUS_TX_UUID, receiver.handler)

        print("[Test] Waiting for Pico READY...")
        if not wait_for_pico(pico, "READY", timeout=20):
            print("[!] Pico did not send READY.")
            await client.stop_notify(NUS_TX_UUID)
            return

        pico.write(b"go\n")
        print("[Test] Sent 'go' to Pico.")

        deadline = time.time() + 5
        while time.time() < deadline:
            if pico.in_waiting:
                line = pico.readline().decode(errors='replace').strip()
                if line: print(f"[Pico] {line}")
                if line.startswith("START_IN_"): break
            else:
                time.sleep(0.05)

        time.sleep(1)

        for i, payload_size in enumerate(PAYLOAD_SIZES):
            receiver.clear()
            print(f"\n  [→] {i+1}/{len(PAYLOAD_SIZES)} Waiting for {payload_size}B...")

            # Wait for SIZE:N\n marker
            size_line = receiver.read_until(b"\n", timeout=30)
            if size_line is None:
                print(f"  [!] No SIZE marker received, stopping.")
                pico.write(b"SKIP\n")
                break

            size_line_str = size_line.decode('utf-8', errors='replace').strip()
            print(f"  [BLE] Marker: '{size_line_str}'")

            if not size_line_str.startswith("SIZE:"):
                print(f"  [!] Unexpected marker: '{size_line_str}', stopping.")
                pico.write(b"SKIP\n")
                break

            declared_size = int(size_line_str.replace("SIZE:", ""))

            # Read exactly payload_size bytes
            payload = receiver.read_exact(declared_size, timeout=60)
            if payload is None:
                print(f"  [!] Timed out waiting for {payload_size}B payload.")
                pico.write(b"SKIP\n")
                break

            # Read END marker
            receiver.read_until(b"END\n", timeout=10)

            verified = verify_payload(payload, payload_size, i)
            if verified:
                print(f"  [✓] {payload_size}B received and verified")
            else:
                print(f"  [✗] {payload_size}B FAILED verification")

            pico.write(b"ACK\n")
            time.sleep(1)

        while pico.in_waiting:
            line = pico.readline().decode(errors='replace').strip()
            if line: print(f"[Pico] {line}")

        await client.stop_notify(NUS_TX_UUID)
        print("\n[✓] Test complete.")


if __name__ == "__main__":
    upload_nrf()
    upload_pico()

    print("\n[Setup] Connecting to Pico...")
    try:
        pico = serial.Serial(PICO_PORT, PICO_BAUD, timeout=15)
    except serial.SerialException as e:
        print(f"[!] Could not open Pico port: {e}")
        exit(1)

    time.sleep(2)
    pico.reset_input_buffer()

    print(f"\nPayloads: {PAYLOAD_SIZES}")
    input("\nPress ENTER to begin → ")

    asyncio.run(run_test_async(pico))
    pico.close()