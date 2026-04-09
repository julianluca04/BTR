"""
ble_upload.py  —  compile and upload a sketch to the XIAO nRF52840 Sense
Usage:
    python ble_upload.py                        # uses defaults below
    python ble_upload.py --sketch ~/Desktop/ble_1
    python ble_upload.py --port /dev/cu.usbmodem2101
"""

import argparse
import os
import shutil
import subprocess
import sys
import time

# ─── DEFAULTS — edit these to match your setup ────────────────────────────────
DEFAULT_SKETCH = '/Users/foml/coding/MSP/year_3/BTR/experiment/BLE/experiment 1 (all in one)/ble_1'
DEFAULT_FQBN   = "Seeeduino:nrf52:xiaonRF52840Sense"
# Leave DEFAULT_PORT as "" to auto-detect from board list
DEFAULT_PORT   = ""
# ──────────────────────────────────────────────────────────────────────────────
 
SAFE_BUILD_BASE = "/tmp/ble_upload_tmp"
 
 
def run(cmd, check=True):
    print(f"\n$ {' '.join(cmd)}")
    result = subprocess.run(cmd, text=True, capture_output=False)
    if check and result.returncode != 0:
        print(f"\n[!] Command failed (exit {result.returncode})")
        sys.exit(result.returncode)
    return result.returncode
 
 
def safe_copy(sketch_path):
    """
    Copy sketch folder to a space-free path under /tmp.
    Returns the path to the copied folder.
    """
    sketch_name = os.path.basename(os.path.normpath(sketch_path))
    safe_path   = os.path.join(SAFE_BUILD_BASE, sketch_name)
 
    if os.path.exists(safe_path):
        shutil.rmtree(safe_path)
    shutil.copytree(sketch_path, safe_path)
 
    print(f"[→] Sketch copied to safe path: {safe_path}")
    return safe_path
 
 
def find_port(fqbn):
    print("\n[→] Scanning for connected boards...")
    result = subprocess.run(
        ["arduino-cli", "board", "list"],
        text=True, capture_output=True
    )
    print(result.stdout)
    for line in result.stdout.splitlines():
        if fqbn in line:
            port = line.split()[0]
            print(f"[✓] Found board on {port}")
            return port
    return None
 
 
def main():
    parser = argparse.ArgumentParser(description="Compile and upload nRF52840 sketch")
    parser.add_argument("--sketch", default=DEFAULT_SKETCH,
                        help="Path to sketch folder (spaces/parens OK)")
    parser.add_argument("--fqbn",   default=DEFAULT_FQBN,   help="Board FQBN")
    parser.add_argument("--port",   default=DEFAULT_PORT,
                        help="Upload port (auto-detected if blank)")
    args = parser.parse_args()
 
    sketch = os.path.expanduser(args.sketch)
    if not os.path.isdir(sketch):
        print(f"[!] Sketch folder not found: {sketch}")
        sys.exit(1)
 
    # Copy to space-free path if necessary
    if " " in sketch or "(" in sketch or ")" in sketch:
        print(f"[→] Path contains spaces/parens — copying to safe location...")
        sketch = safe_copy(sketch)
    else:
        print(f"[→] Sketch path is clean, compiling in place.")
 
    # ── Compile ──────────────────────────────────────────────────────────────
    print("\n[1/3] Compiling...")
    run(["arduino-cli", "compile", "--fqbn", args.fqbn, sketch])
 
    # ── Export binaries ──────────────────────────────────────────────────────
    print("\n[2/3] Exporting binaries...")
    run(["arduino-cli", "compile", "--fqbn", args.fqbn, "--export-binaries", sketch])
 
    # ── Detect port ──────────────────────────────────────────────────────────
    port = args.port or find_port(args.fqbn)
    if not port:
        print("\n[!] Board not found. Double-tap the reset button on the nRF52840,")
        print("    wait for the LED to pulse, then press ENTER to retry.")
        input("    → ")
        time.sleep(1)
        port = find_port(args.fqbn)
 
    if not port:
        print("\n[!] Still not found. Run 'arduino-cli board list' manually to check.")
        sys.exit(1)
 
    # ── Upload ───────────────────────────────────────────────────────────────
    print(f"\n[3/3] Uploading to {port}...")
    rc = run(["arduino-cli", "upload", "-p", port, "-b", args.fqbn, sketch], check=False)
 
    if rc != 0:
        print("\n[!] Upload failed. Double-tap reset to enter bootloader mode,")
        print("    wait for the LED to pulse, then press ENTER to retry.")
        input("    → ")
        time.sleep(1)
        port = find_port(args.fqbn) or port
        run(["arduino-cli", "upload", "-p", port, "-b", args.fqbn, sketch])
 
    print("\n[✓] Done — sketch uploaded successfully.")
    print("\n[→] Final board list:")
    subprocess.run(["arduino-cli", "board", "list"])
 
 
if __name__ == "__main__":
    main()