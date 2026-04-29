import serial
import time

TX_PORT = "/dev/cu.usbmodem1201"
RX_PORT = "/dev/cu.usbmodem11301"
BAUD = 57600

PAYLOAD_SIZES = [1, 2, 4, 8, 16, 32, 64, 128, 220]

TX_TIMEOUT = 20.0
RX_TIMEOUT = 20.0


def readline(ser, timeout=2.0):
    """Read one CRLF-terminated line."""
    deadline = time.time() + timeout
    buf = b""
    while time.time() < deadline:
        if ser.in_waiting:
            ch = ser.read(1)
            buf += ch
            if buf.endswith(b"\r\n"):
                return buf.decode(errors="ignore").strip()
        else:
            time.sleep(0.002)
    return buf.decode(errors="ignore").strip()


def cmd(ser, command, timeout=0.5):
    """Send command, return first response."""
    ser.reset_input_buffer()
    ser.write((command + "\r\n").encode())
    time.sleep(0.05)
    resp = readline(ser, timeout=timeout)
    print(f"    >> {command!r}  <- {resp!r}")
    return resp


def reset_radio(ser, name):
    print(f"\n[{name}] RESET")
    ser.write(b"sys reset\r\n")
    time.sleep(2.0)
    while ser.in_waiting:
        line = readline(ser, timeout=0.3)
        if line:
            print(f"[{name}] {line}")
    ser.reset_input_buffer()


def configure(ser, name):
    print(f"[{name}] CONFIGURE")
    steps = [
        "mac pause",
        "radio set mod lora",
        "radio set freq 915000000",
        "radio set sf sf12",
        "radio set bw 125",
        "radio set cr 4/5",
        "radio set pwr -3",  # Minimum TX power for close-range
        "radio set crc off",  # Disable CRC to accept potentially corrupted packets
        "radio set wdt 15000",
        "radio set prlen 8",
        "radio set sync 12",
    ]
    for command in steps:
        cmd(ser, command)
    print(f"[{name}] CONFIG DONE\n")


if __name__ == "__main__":
    tx = serial.Serial(TX_PORT, BAUD, timeout=0)
    rx = serial.Serial(RX_PORT, BAUD, timeout=0)

    time.sleep(1)

    reset_radio(tx, "TX")
    reset_radio(rx, "RX")
    configure(tx, "TX")
    configure(rx, "RX")

    print("\n===== START PIPELINE =====\n")

    passed = 0
    for i, size in enumerate(PAYLOAD_SIZES):
        char = chr(ord('A') + (i % 26))
        payload = bytes([ord(char)] * size)
        hex_payload = payload.hex().upper()

        print(f"\n--- Test {i+1}/{len(PAYLOAD_SIZES)}: {size}B ('{char}' x {size}) ---")

        # Arm RX
        print("[1] Arming RX")
        rx.reset_input_buffer()
        rx.write(b"radio rx 0\r\n")
        time.sleep(0.05)
        ack = readline(rx, timeout=1.0)
        print(f"[RX] arm: {ack!r}")
        if ack != "ok":
            print(f"[FAIL] RX arm rejected")
            break

        time.sleep(0.3)

        # TX sends
        print(f"[2] TX transmitting {size}B")
        tx.reset_input_buffer()
        tx.write(f"radio tx {hex_payload}\r\n".encode())
        time.sleep(0.05)

        first = readline(tx, timeout=2.0)
        print(f"[TX] immediate: {first!r}")
        if first != "ok":
            print(f"[FAIL] TX rejected")
            break

        print("[TX] waiting for airtime...")
        tx_ok = False
        deadline = time.time() + TX_TIMEOUT
        while time.time() < deadline:
            line = readline(tx, timeout=1.0)
            if line:
                print(f"[TX] {line}")
                if line == "radio_tx_ok":
                    tx_ok = True
                    break
                if line.startswith("radio_err"):
                    break

        if not tx_ok:
            print(f"[FAIL] TX failed")
            break

        print("[3] Waiting for RX")

        # Wait for RX
        rx_val = None
        deadline = time.time() + RX_TIMEOUT
        while time.time() < deadline:
            line = readline(rx, timeout=1.0)
            if line:
                print(f"[RX] {line}")
                if line.startswith("radio_rx"):
                    parts = line.split()
                    if len(parts) > 1:
                        rx_val = parts[1]
                    break
                if line.startswith("radio_err"):
                    print("[RX] receive error")
                    break

        if rx_val is None:
            print(f"[FAIL] No valid RX")
            break

        # Verify
        print("[4] Verifying")
        try:
            rx_bytes = bytes.fromhex(rx_val)
        except ValueError:
            print(f"[FAIL] Bad hex: {rx_val!r}")
            break

        expected = ord(char)
        if len(rx_bytes) == size and all(b == expected for b in rx_bytes):
            print(f"[PASS] {size}B OK")
            passed += 1
        else:
            print(f"[FAIL] Mismatch: expected {size}B of 0x{expected:02X}, got {len(rx_bytes)}B")
            if rx_bytes:
                print(f"       First bytes: {rx_bytes[:10].hex()}")
            break

    tx.close()
    rx.close()

    print(f"\n===== DONE: {passed}/{len(PAYLOAD_SIZES)} passed =====")