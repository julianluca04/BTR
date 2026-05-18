import asyncio
from bleak import BleakScanner

async def main():
    print("Scanning for BLE devices...")
    devices = await BleakScanner.discover(timeout=5.0)

    if not devices:
        print("No devices found.")
        return

    for d in devices:
        print(f"Address: {d.address}")
        print(f"Name: {d.name}")
        print("-" * 40)

asyncio.run(main())