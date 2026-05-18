import asyncio
import os
from bleak import BleakClient

ADDRESS = "1385E324-4660-24ED-9B2E-A55F8DF154AE"
CHAR_UUID = "12345678-1234-1234-1234-1234567890ac"

SAVE_FOLDER = "received_files"
file_bytes = bytearray()
expected_size = None

def handle_notification(sender, data):
    global expected_size, file_bytes

    if expected_size is None:
        expected_size = int.from_bytes(data[:4], byteorder="little")
        print("File size:", expected_size)
        return

    file_bytes.extend(data)
    print("Received", len(file_bytes), "bytes")

    if len(file_bytes) >= expected_size:
        save_file()

def save_file():
    os.makedirs(SAVE_FOLDER, exist_ok=True)

    file_path = os.path.join(SAVE_FOLDER, "received_file.txt")

    text = file_bytes[:expected_size].decode("utf-8", errors="ignore")

    with open(file_path, "w", encoding="utf-8") as f:
        f.write(text)

    print("Transfer complete")
    print("File saved to:", file_path)

async def main():
    async with BleakClient(ADDRESS) as client:
        await client.start_notify(CHAR_UUID, handle_notification)
        print("Connected. Waiting for file...")
        await asyncio.sleep(30)

asyncio.run(main())