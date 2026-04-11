"""
test1.py
1. Uploads nRF sketch
2. Flashes Pico with MicroPython experiment code
3. Connects BLE, orchestrates payload test, ACKs Pico via USB serial
"""

import asyncio
import os
import serial
import shutil
import subprocess
import time
from bleak import BleakClient

# ─── CONFIG ───────────────────────────────────────────────────────────────────
PAYLOAD_SIZES = [
    1, 2, 4, 8, 16, 32, 64, 128, 256, 512,
    1024, 2048, 4096, 8192, 16384, 32768, 65536,
    131072, 262144, 524288, 1048576
]

PICO_PORT       = "/dev/tty.usbmodem11301"
PICO_BAUD       = 115200
NRF_ADDRESS     = "1385E324-4660-24ED-9B2E-A55F8DF154AE"
NUS_TX_UUID     = "6e400003-b5a3-f393-e0a9-e50e24dcca9e"
NRF_SKETCH_SRC  = '/Users/foml/coding/MSP/year_3/BTR/experiments/BLE/experiment 1 (all in one)/ble_1'
NRF_FQBN        = 'Seeeduino:nrf52:xiaonRF52840Sense'
NRF_PORT        = '/dev/cu.usbmodem11101'
SAFE_BUILD_BASE = '/tmp/ble_upload_tmp'
BLE_TIMEOUT_S   = 300   # BLE sending alone; UART buffering is covered by wait_for_size
IDLE_S          = 1.0
# ─────────────────────────────────────────────────────────────────────────────

PICO_CODE = '''\
import machine, time, sys, select

led  = machine.Pin(25, machine.Pin.OUT)
uart = machine.UART(0, baudrate=115200, tx=machine.Pin(0), rx=machine.Pin(1))

PAYLOAD_SIZES  = [1, 2, 4, 8, 16, 32, 64, 128, 256, 512,
                  1024, 2048, 4096, 8192, 16384, 32768, 65536,
                  131072, 262144, 524288, 1048576]
SETTLE_MS      = 1000
START_DELAY_MS = 500

def flash(n):
    for _ in range(n):
        led.value(1); time.sleep_ms(80)
        led.value(0); time.sleep_ms(80)

def usb_readline(timeout_ms=300000):
    buf = b""
    deadline = time.ticks_add(time.ticks_ms(), timeout_ms)
    while time.ticks_diff(deadline, time.ticks_ms()) > 0:
        if select.select([sys.stdin], [], [], 0.01)[0]:
            c = sys.stdin.read(1)
            if c == "\\n":
                return buf.decode("utf-8", "replace").strip()
            buf += c.encode()
    return ""

print("READY")

while True:
    led.value(1); time.sleep_ms(100)
    led.value(0); time.sleep_ms(900)

    if select.select([sys.stdin], [], [], 0)[0]:
        cmd = sys.stdin.readline().strip()
        if cmd == "go":
            print("START_IN_" + str(START_DELAY_MS))
            time.sleep_ms(START_DELAY_MS)

            for i, size in enumerate(PAYLOAD_SIZES):
                digit = bytes([ord("0") + (i % 10)])

                uart.write((str(size) + "\\n").encode())
                time.sleep_ms(50)

                flash(1)
                sent = 0
                aborted = False
                while sent < size:
                    # Check for mid-send abort (SKIP sent by Mac on nRF FAIL)
                    if select.select([sys.stdin], [], [], 0)[0]:
                        sys.stdin.readline()
                        aborted = True
                        break
                    chunk = min(256, size - sent)
                    uart.write(digit * chunk)
                    sent += chunk
                    time.sleep_ms(10)
                flash(2)

                if aborted:
                    print("ABORTED " + str(size) + "B")
                    break

                print("SENT " + str(size) + "B")

                response = usb_readline(timeout_ms=300000)
                if response == "ACK":
                    time.sleep_ms(SETTLE_MS)
                else:
                    print("NO_ACK got=" + response)
                    break

            flash(3)
            print("DONE")
            print("READY")
'''


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
    """Flash main.py onto the Pico and return the open serial port.

    The port is kept open so that the 'READY' line printed by the new
    main.py during boot is not lost when the port is closed/reopened.
    The caller is responsible for closing the returned Serial object.
    """
    print("\n[→] Flashing Pico via raw REPL...")
    ser = serial.Serial(PICO_PORT, PICO_BAUD, timeout=2)

    # Interrupt whatever is running
    for _ in range(20):
        ser.write(b'\x03')
        time.sleep(0.05)
    time.sleep(0.5)
    ser.reset_input_buffer()

    # Enter raw REPL
    ser.write(b'\x01')
    time.sleep(1.0)  # give it time to respond
    response = ser.read(ser.in_waiting)
    print(f"[REPL] {response}")

    if b'raw REPL' not in response:
        print("[!] Trying Ctrl+D then Ctrl+A...")
        ser.write(b'\x02')  # exit any REPL mode first
        time.sleep(0.5)
        ser.write(b'\x04')  # soft reboot
        time.sleep(3.0)     # wait for boot
        ser.reset_input_buffer()
        ser.write(b'\x01')  # enter raw REPL
        time.sleep(1.0)
        response = ser.read(ser.in_waiting)
        print(f"[REPL2] {response}")

    if b'raw REPL' not in response:
        ser.close()
        raise RuntimeError("Could not enter raw REPL")

    escaped = PICO_CODE.replace('\\', '\\\\').replace("'", "\\'").replace('\n', '\\n')
    cmd = f"f=open('main.py','w');f.write('{escaped}');f.close()\x04"
    ser.write(cmd.encode())
    time.sleep(3)
    response = ser.read(ser.in_waiting)
    print(f"[Write] {response}")

    ser.write(b'\x02')  # exit raw REPL
    time.sleep(0.5)
    ser.write(b'\x04')  # soft reboot into main.py

    # Keep the port open and wait for READY so the line isn't lost when
    # the port would otherwise be closed and the OS buffer discarded.
    print("[→] Waiting for Pico READY (on flash connection)...")
    ser.timeout = 15
    deadline = time.time() + 30
    while time.time() < deadline:
        if ser.in_waiting:
            line = ser.readline().decode(errors='replace').strip()
            if line:
                print(f"[Pico] {line}")
            if line == "READY":
                print("[✓] Pico flashed and ready.")
                return ser
        time.sleep(0.05)

    ser.close()
    raise RuntimeError("Pico did not print READY after flashing")


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


def wait_for_line(pico, expected, timeout=30):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if pico.in_waiting:
            line = pico.readline().decode(errors='replace').strip()
            if line:
                print(f"[Pico] {line}")
            if line == expected:
                return True
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
    """Asyncio-native BLE packet collector.

    All public methods that wait for data are coroutines — they yield
    control back to the event loop so bleak's notification callbacks can
    run.  handler() is safe to call from any thread via call_soon_threadsafe.
    """

    def __init__(self):
        self._queue = None   # asyncio.Queue; created in start()
        self._loop  = None
        self._size  = None
        self._fail  = False

    def start(self):
        """Call once from within the running event loop before first use."""
        self._loop  = asyncio.get_running_loop()
        self._queue = asyncio.Queue()

    def reset(self):
        """Drain leftover packets and clear state for the next payload."""
        while not self._queue.empty():
            try:
                self._queue.get_nowait()
            except asyncio.QueueEmpty:
                break
        self._size = None
        self._fail = False

    def handler(self, sender, data: bytearray):
        """BLE notification callback — called on the event loop thread by bleak."""
        self._queue.put_nowait(bytes(data))

    async def wait_for_size(self, timeout=30) -> bool:
        """Consume packets until a SIZE:N or FAIL header is found."""
        deadline = self._loop.time() + timeout
        while True:
            rem = deadline - self._loop.time()
            if rem <= 0:
                return False
            try:
                data = await asyncio.wait_for(self._queue.get(), timeout=rem)
            except asyncio.TimeoutError:
                return False
            try:
                text = data.decode('utf-8').strip()
                if text.startswith("SIZE:"):
                    self._size = int(text.split(":")[1])
                    print(f"  [BLE] SIZE header: {self._size}B")
                    return True
                if text == "FAIL":
                    self._fail = True
                    return True
            except Exception:
                pass
            # Non-text packet before SIZE header — discard and keep waiting

    async def read_exact(self, n: int, timeout=BLE_TIMEOUT_S):
        """Collect exactly n bytes from queued BLE notification chunks."""
        buf      = bytearray()
        deadline = self._loop.time() + timeout
        while len(buf) < n:
            rem = deadline - self._loop.time()
            if rem <= 0:
                print(f"  [!] Timeout: have {len(buf)}B, need {n}B")
                return None
            try:
                chunk = await asyncio.wait_for(self._queue.get(), timeout=rem)
                buf.extend(chunk)
            except asyncio.TimeoutError:
                print(f"  [!] Timeout: have {len(buf)}B, need {n}B")
                return None
        return bytes(buf[:n])

    @property
    def declared_size(self): return self._size

    @property
    def is_fail(self): return self._fail


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

    results = []

    try:
        receiver = BLEReceiver()
        receiver.start()  # bind asyncio queue to this event loop
        await client.start_notify(NUS_TX_UUID, receiver.handler)
        print(f"[✓] Subscribed to BLE notifications. MTU: {client.mtu_size}B ({client.mtu_size - 3}B data)")

        pico.reset_input_buffer()
        pico.write(b"go\n")
        print("[Test] Sent 'go' to Pico.")

        # Wait for Pico to confirm it's starting — use await so the event
        # loop stays live and BLE callbacks can land while we're waiting.
        deadline = time.time() + 10
        while time.time() < deadline:
            if pico.in_waiting:
                line = pico.readline().decode(errors='replace').strip()
                if line:
                    print(f"[Pico] {line}")
                if line.startswith("START_IN_"):
                    break
            await asyncio.sleep(0.01)

        for i, payload_size in enumerate(PAYLOAD_SIZES):
            receiver.reset()
            print(f"\n  [{i+1}/{len(PAYLOAD_SIZES)}] Expecting {payload_size}B...")
            t_start = time.monotonic()

            if not await receiver.wait_for_size(timeout=300):
                print(f"  [!] No SIZE header — stopping.")
                pico.write(b"SKIP\n")
                break

            if receiver.is_fail:
                print(f"  [!] nRF sent FAIL (malloc?) — stopping.")
                pico.write(b"SKIP\n")
                break

            if receiver.declared_size != payload_size:
                print(f"  [!] SIZE mismatch: nRF says {receiver.declared_size}B, expected {payload_size}B")
                pico.write(b"SKIP\n")
                break

            payload = await receiver.read_exact(receiver.declared_size, timeout=BLE_TIMEOUT_S)

            if payload is None:
                print(f"  [!] {payload_size}B timed out.")
                pico.write(b"SKIP\n")
                break

            t_elapsed = time.monotonic() - t_start
            verified = verify_payload(payload, payload_size, i)
            status = "PASS" if verified else "FAIL"
            throughput = payload_size / t_elapsed if t_elapsed > 0 else 0
            print(f"  [{status}] {payload_size}B  {t_elapsed:.2f}s  {throughput/1024:.1f} KB/s")
            results.append((payload_size, status, t_elapsed))

            pico.write(b"ACK\n")
            await asyncio.sleep(IDLE_S)

        await asyncio.sleep(1)
        while pico.in_waiting:
            line = pico.readline().decode(errors='replace').strip()
            if line:
                print(f"[Pico] {line}")

    finally:
        await client.stop_notify(NUS_TX_UUID)
        await client.disconnect()

    print("\n─── Results ──────────────────────────────────────────")
    print(f"  {'Size':>10}   {'Status':<6}  {'Time':>8}  {'KB/s':>8}")
    print(f"  {'─'*10}   {'─'*6}  {'─'*8}  {'─'*8}")
    for size, status, elapsed in results:
        kbps = (size / elapsed / 1024) if elapsed > 0 else 0
        print(f"  {size:>9}B   {status:<6}  {elapsed:>7.2f}s  {kbps:>7.1f}")
    print("──────────────────────────────────────────────────────")
    print(f"[✓] Test complete. {sum(1 for _, s, _ in results if s == 'PASS')}/{len(results)} passed.")


if __name__ == "__main__":
    upload_nrf()
    pico = flash_pico()  # returns open port, already confirmed READY

    print(f"\nPayloads: {PAYLOAD_SIZES}")
    input("\nPress ENTER to begin → ")

    asyncio.run(run_test_async(pico))
    pico.close()