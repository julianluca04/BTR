from bleak import BleakClient
import asyncio

ADDRESS = "1385E324-4660-24ED-9B2E-A55F8DF154AE"

async def main():
    async with BleakClient(ADDRESS) as client:
        services = client.services
        for s in services:
            print(s.uuid)

asyncio.run(main())