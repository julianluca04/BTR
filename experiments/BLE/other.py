import asyncio
from bleak import BleakClient

NRF_ADDRESS = "1385E324-4660-24ED-9B2E-A55F8DF154AE"

async def check_mtu():
    async with BleakClient(NRF_ADDRESS) as client:
        print(f"MTU: {client.mtu_size}B")
        print(f"Effective chunk: {client.mtu_size - 3}B")

asyncio.run(check_mtu())