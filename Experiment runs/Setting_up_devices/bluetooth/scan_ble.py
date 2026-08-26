import asyncio
from bleak import BleakScanner

TARGET_NAME = "XIAO_BLE_TEST"

def detection_callback(device, advertisement_data):
    if device.name == TARGET_NAME:
        mfg = advertisement_data.manufacturer_data
        if mfg:
            for company_id, data in mfg.items():
                value = int.from_bytes(data, byteorder="big")
                print(f"From {device.address}: counter = {value}")

async def main():
    scanner = BleakScanner(detection_callback)
    await scanner.start()
    print("Scanning for BLE advertisements...")
    await asyncio.sleep(30)
    await scanner.stop()

asyncio.run(main())