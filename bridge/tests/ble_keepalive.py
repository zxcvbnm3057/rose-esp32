"""Test BLE with RSSI scan keepalive"""
import asyncio, httpx, time
from bleak import BleakClient

ESP32 = 'F0:F5:BD:26:92:26'
API = 'http://127.0.0.1:8000'

async def main():
    httpx.post(f'{API}/api/v1/ble/pairing/enable', json={'timeout_s': 120}, timeout=10)
    httpx.post(f'{API}/api/v1/ble/scan/start', json={'interval_s': 5}, timeout=10)
    print('RSSI scan ON (5s interval)')
    
    client = BleakClient(ESP32, timeout=15)
    await client.connect()
    print(f'Connected MTU={client.mtu_size}')
    
    t = 0
    for i in range(8):
        await asyncio.sleep(5)
        t = (i + 1) * 5
        pc = client.is_connected
        r = httpx.get(f'{API}/api/v1/ble/peers', timeout=5)
        ps = r.json()['data']['peers']
        status = 'OK' if pc else 'XX'
        print(f'  t={t:3d}s PC:{status} peers:{ps}')
        if not pc:
            break
    
    print(f'Final: PC connected={client.is_connected} after {t}s')
    if client.is_connected:
        await client.disconnect()

asyncio.run(main())
