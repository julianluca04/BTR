import asyncio
import os
import serial
import shutil
import subprocess
import threading
import time
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

BLE_TIMEOUT_S = 120
IDLE_S        = 1.0
# ─────────────────────────────────────────────────────────────────────────────

# MicroPython code for Pico — uses UART0 (GP0=TX, GP1=RX) confirmed working
PICO_CODE = """
import machine
import time

led  = machine.Pin(25, machine.Pin.OUT)
uart = machine.UART(0, baudrate=115200, tx=machine.Pin(0), rx=machine.Pin(1))
usb  = machine.UART(0, baudrate=115200)

PAYLOAD_SIZES = [1, 2, 4, 8, 16, 32, 64, 128, 256, 512,
                 1024, 2048, 4096, 8192, 16384, 32768, 65536, 131072]
SETTLE_MS      = 1000
START_DELAY_MS = 500

def flash(n):
    for _ in range(n):
        led.value(1); time.sleep_ms(80)
        led.value(0); time.sleep_ms(80)

def usb_println(s):
    print(s)

def usb_readline(timeout_ms=15000):
    buf = b''
    deadline = time.ticks_add(time.ticks_ms(), timeout_ms)
    while time.ticks_diff(deadline, time.ticks_ms()) > 0:
        import sys
        import select
        if select.select([sys.stdin], [], [], 0.01)[0]:
            c = sys.stdin.read(1)
            if c == '\\n':
                return buf.decode('utf-8', 'replace').strip()
            buf += c.encode()
    return ''

usb_println('READY')

while True:
    led.value(1); time.sleep_ms(100)
    led.value(0); time.sleep_ms(900)
    
    import sys, select
    if select.select([sys.stdin], [], [], 0)[0]:
        cmd = sys.stdin.readline().strip()
        if cmd == 'go':
            usb_println('START_IN_' + str(START_DELAY_MS))
            time.sleep_ms(START_DELAY_MS)
            
            skip = False
            for i, size in enumerate(PAYLOAD_SIZES):
                if skip:
                    break
                digit = ord('0') + (i % 10)
                
                uart.write((str(size) + '\\n').encode())
                time.sleep_ms(50)
                
                flash(1)
                sent = 0
                while sent < size:
                    chunk = min(256, size - sent)
                    uart.write(bytes([digit] * chunk))
                    sent += chunk
                    time.sleep_ms(10)
                flash(2)
                
                usb_println('SENT ' + str(size) + 'B')
                
                deadline = time.ticks_add(time.ticks_ms(), 15000)
                got = ''
                while time.ticks_diff(deadline, time.ticks_ms()) > 0:
                    if select.select([sys.stdin], [], [], 0.01)[0]:
                        got = sys.stdin.readline().strip()
                        break
                
                if got == 'ACK':
                    pass
                else:
                    skip = True
                
                if not skip:
                    time.sleep_ms(SETTLE_MS)
            
            flash(3)
            usb_println('DONE')
            usb_println('READY')
"""


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
        if os.path.exists(safe):
            shutil.rmtree(safe)
        shutil.copytree(sketch, safe)
        sketch = safe
        print(f"[→] Copied to: {sketch}")
    run_cmd(["arduino-cli", "compile", "--fqbn", NRF_FQBN, sketch])
    rc = run_cmd(["arduino-cli", "upload", "-p", NRF_PORT, "-b", NRF_FQBN, sketch], check=False)
    if rc != 0:
        print("[!] Upload failed — double-tap reset on nRF, wait for LED pulse, press ENTER")
        input("    → ")
        time.sleep(1)
        run_cmd(["arduino-cli", "upload", "-p", NRF_PORT, "-b", NRF_FQBN, sketch])
    print("[✓] nRF uploaded. Waiting 5s to boot...")
    time.sleep(5)


def flash_pico():
    print("\n[→] Flashing Pico via MicroPython raw REPL...")

    with serial.Serial(PICO_PORT, PICO_BAUD, timeout=2) as ser:
        for _ in range(20):
            ser.write(b'\x03')
            time.sleep(0.05)
        time.sleep(0.5)
        ser.reset_input_buffer()
        ser.write(b'\x01')
        time.sleep(0.5)
        response = ser.read(ser.in_waiting)
        print(f"[REPL] {response}")

        if b'raw REPL' not in response:
            ser.write(b'\x04')
            time.sleep(2)
            ser.write(b'\x01')
            time.sleep(0.5)
            response = ser.read(ser.in_waiting)
            print(f"[REPL2] {response}")

        if b'raw REPL' not in response:
            raise RuntimeError("Could not enter raw REPL")

        cmd = b"f=open('main.py','w');f.write(" + repr(PICO_CODE).encode() + b");f.close()\x04"
        ser.write(cmd)
        time.sleep(3)
        response = ser.read(ser.in_waiting)
        print(f"[Write] {response}")

        ser.write(b'\x04')
        time.sleep(2)
        print("[✓] Pico flashed and restarted.")


def open_pico_serial(port, baud, retries=10, delay=2.0):
    for attempt in range(retries):
        try:
            s = serial.Serial(port, baud, timeout=15)
            print(f"[✓] Pico serial opened on {port}")
            return s
        except serial.SerialException as e:
            print(f"[!] Attempt {attempt+1}/{retries} failed: {e}")
            time.sleep(delay)
    raise RuntimeError(f"Could not open Pico port {port} after {retries} attempts.")


def wait_for_pico(pico, expected, timeout=30):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if pico.in_waiting:
            line = pico.readline().decode(errors='replace').strip()
            if line:
                print(f"[Pico] {line}")
            if line == expected:
                return True
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
        self._buf        = bytearray()
        self._lock       = threading.Lock()
        self._new_data   = threading.Event()
        self._size       = None
        self._size_ready = threading.Event()

    def reset(self):
        with self._lock:
            self._buf.clear()
            self._size = None
        self._new_data.clear()
        self._size_ready.clear()

    def handler(self, sender, data: bytearray):
        try:
            text = data.decode('utf-8')
            if text.startswith("SIZE:"):
                self._size = int(text.strip().split(":")[1])
                print(f"  [BLE] SIZE: {self._size}B")
                self._size_ready.set()
                return
            if text.strip() == "FAIL":
                self._size = -1
                self._size_ready.set()
                return
        except Exception:
            pass
        with self._lock:
            self._buf.extend(data)
        self._new_data.set()

    def wait_for_size(self, timeout=30):
        return self._size_ready.wait(timeout)

    def read_exact(self, n: int, timeout=BLE_TIMEOUT_S):
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

    @property
    def declared_size(self):
        return self._size


async def run_test_async(pico):
    print(f"\n[Test] Connecting to nRF via BLE...")

    client = BleakClient(NRF_ADDRESS)
    for attempt in range(5):
        try:
            await client.connect()
            if client.is_connected:
                print(f"[✓] BLE connected.")
                break
        except Exception as e:
            print(f"[!] BLE attempt {attempt+1}/5 failed: {e}")
            await asyncio.sleep(2)

    if not client.is_connected:
        print("[!] Could not connect to nRF.")
        return

    try:
        receiver = BLEReceiver()
        await client.start_notify(NUS_TX_UUID, receiver.handler)
        print("[✓] Subscribed to BLE notifications.")

        # BLE connected — now send go to Pico
        pico.reset_input_buffer()
        pico.write(b"go\n")
        print("[Test] Sent 'go' to Pico.")

        deadline = time.time() + 10
        while time.time() < deadline:
            if pico.in_waiting:
                line = pico.readline().decode(errors='replace').strip()
                if line:
                    print(f"[Pico] {line}")
                if line.startswith("START_IN_"):
                    break
            else:
                time.sleep(0.01)

        for i, payload_size in enumerate(PAYLOAD_SIZES):
            receiver.reset()
            print(f"\n  [→] {i+1}/{len(PAYLOAD_SIZES)} Waiting for {payload_size}B...")

            if not receiver.wait_for_size(timeout=30):
                print(f"  [!] No SIZE header received, stopping.")
                pico.write(b"SKIP\n")
                break

            if receiver.declared_size == -1:
                print(f"  [!] nRF sent FAIL, stopping.")
                pico.write(b"SKIP\n")
                break

            payload = receiver.read_exact(receiver.declared_size, timeout=BLE_TIMEOUT_S)

            if payload is None:
                print(f"  [!] {payload_size}B timed out, stopping.")
                pico.write(b"SKIP\n")
                break

            verified = verify_payload(payload, payload_size, i)
            if verified:
                print(f"  [✓] {payload_size}B received and verified")
            else:
                print(f"  [✗] {payload_size}B FAILED verification")

            pico.write(b"ACK\n")
            receiver.reset()
            time.sleep(IDLE_S)

        while pico.in_waiting:
            line = pico.readline().decode(errors='replace').strip()
            if line:
                print(f"[Pico] {line}")

    finally:
        await client.stop_notify(NUS_TX_UUID)
        await client.disconnect()
        print("\n[✓] Test complete.")


if __name__ == "__main__":
    upload_nrf()
    flash_pico()

    print("\n[Setup] Connecting to Pico...")
    pico = open_pico_serial(PICO_PORT, PICO_BAUD)

    print("\n[→] Checking Pico is alive...")
    if not wait_for_pico(pico, "READY", timeout=30):
        print("[!] Pico not responding.")
        pico.close()
        exit(1)
    print("[✓] Pico confirmed alive.")

    print(f"\nPayloads : {PAYLOAD_SIZES}")
    input("\nPress ENTER to begin → ")

    asyncio.run(run_test_async(pico))
    pico.close()