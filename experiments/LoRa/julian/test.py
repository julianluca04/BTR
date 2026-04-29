import pyvisa
import serial
import threading
import time
from datetime import datetime

TX_PORT = "/dev/cu.usbmodem1201"
RX_PORT = "/dev/cu.usbmodem11301"
BAUD = 57600

LORA_FREQ = "915000000"
LORA_SF = "sf12"
LORA_BW = "125"
LORA_CR = "4/5"
LORA_PWR = "14"

PAYLOAD_SIZE = 220

RX_RUNNING = True
rx_lock = threading.Lock()
last_payload = None


def drain(ser):
    time.sleep(0.05)
    ser.read(ser.in_waiting or 0)


def send_cmd(ser, cmd):
    ser.write((cmd + "\r\n").encode())
    time.sleep(0.3)
    out = ser.read(ser.in_waiting or 0).decode(errors="ignore")
    return out.strip()


def autobaud(ser, name):
    print(f"[{name}] Sync...")
    for _ in range(3):
        ser.write(b"\x00\x55\r\n")
        time.sleep(0.3)

    time.sleep(1)
    out = ser.read(ser.in_waiting or 0).decode(errors="ignore")
    print(f"[{name}] {out}")


def configure(ser, name):
    print(f"[{name}] Config")

    cmds = [
        "mac pause",
        "radio set mod lora",
        f"radio set freq {LORA_FREQ}",
        f"radio set sf {LORA_SF}",
        f"radio set bw {LORA_BW}",
        f"radio set cr {LORA_CR}",
        f"radio set pwr {LORA_PWR}",
        "radio set crc on",
        "radio set wdt 0",
    ]

    for c in cmds:
        r = send_cmd(ser, c)
        print(f"[{name}] {c} -> {r}")


def rx_loop(rx):
    global last_payload, RX_RUNNING

    while RX_RUNNING:
        try:
            rx.write(b"radio rx 0\r\n")
            time.sleep(0.2)

            deadline = time.time() + 1.5

            while time.time() < deadline:
                if rx.in_waiting:
                    line = rx.readline().decode(errors="ignore").strip()

                    if not line:
                        continue

                    print("[RX]", line)

                    if line.startswith("radio_rx"):
                        parts = line.split()

                        if len(parts) > 1:
                            payload_hex = parts[1]

                            with rx_lock:
                                last_payload = payload_hex

                        rx.write(b"radio rxstop\r\n")
                        time.sleep(0.1)
                        break

                time.sleep(0.01)

        except Exception as e:
            print("[RX ERROR]", e)

        time.sleep(0.05)


def send_220(tx):
    payload = bytes([ord('A') + (i % 26) for i in range(PAYLOAD_SIZE)])
    hex_payload = payload.hex().upper()

    tx.write(b"radio rxstop\r\n")
    time.sleep(0.2)

    tx.write(f"radio tx {hex_payload}\r\n".encode())

    end = time.time() + 10

    while time.time() < end:
        if tx.in_waiting:
            line = tx.readline().decode(errors="ignore").strip()
            print("[TX]", line)
            if "radio_tx_ok" in line:
                return True

    return False


if __name__ == "__main__":
    tx = serial.Serial(TX_PORT, BAUD, timeout=1)
    rx = serial.Serial(RX_PORT, BAUD, timeout=1)

    time.sleep(2)

    autobaud(tx, "TX")
    autobaud(rx, "RX")

    configure(tx, "TX")
    configure(rx, "RX")

    RX_RUNNING = True
    t = threading.Thread(target=rx_loop, args=(rx,), daemon=True)
    t.start()

    print("START 220 BYTE TEST")

    ok = send_220(tx)

    time.sleep(2)

    with rx_lock:
        print("LAST PAYLOAD:", last_payload)

    RX_RUNNING = False

    tx.close()
    rx.close()

    print("SUCCESS" if ok else "FAIL")