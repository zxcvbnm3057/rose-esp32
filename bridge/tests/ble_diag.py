"""双向 BLE 诊断"""
import asyncio, httpx
from bleak import BleakClient, BleakScanner

ESP32 = 'F0:F5:BD:26:92:26'
API = 'http://127.0.0.1:8000'

async def diag():
    # 1. ESP32 initial state
    r = httpx.get(f'{API}/api/v1/ble/peers', timeout=5)
    peers = r.json()['data']['peers']
    print(f'1. ESP32 peers (init): {peers}')
    
    # 2. Scan from this PC
    devs = await BleakScanner.discover(timeout=5, return_adv=True)
    esp = [a for a, (d, _) in devs.items() if d.name and 'ESP32' in d.name]
    print(f'2. PC scan found ESP32: {esp}')
    if not esp:
        print('   ESP32 NOT advertising!')
        return
    
    # 3. Enable pairing
    r = httpx.post(f'{API}/api/v1/ble/pairing/enable', json={'timeout_s': 120}, timeout=10)
    pin = r.json()['data']['pin_code']
    print(f'3. Pairing enabled, PIN={pin}')
    
    # 4. Connect from PC via bleak
    print(f'4. PC connecting to {ESP32}...')
    client = BleakClient(ESP32, timeout=15)
    await client.connect()
    print(f'   Result: is_connected={client.is_connected}')
    
    # 5. Wait for encryption
    await asyncio.sleep(5)
    
    # 6. Check GATT services from PC side
    print('5. GATT services (PC side):')
    try:
        svcs = await client.get_services()
        count = 0
        for s in svcs:
            print(f'   Service: {s.uuid}')
            for c in s.characteristics:
                count += 1
                props = ','.join(c.properties)
                print(f'     Char: {c.uuid} [{props}]')
        print(f'   Total characteristics: {count}')
    except Exception as e:
        print(f'   Error: {type(e).__name__}: {e}')
    
    # 7. ESP32 peers state
    r = httpx.get(f'{API}/api/v1/ble/peers', timeout=5)
    data = r.json()['data']
    esp_peers = data['peers']
    print(f'6. ESP32 peers: {esp_peers}')
    print(f'   PC is_connected: {client.is_connected}')
    
    # 8. Disconnect
    await client.disconnect()
    await asyncio.sleep(2)
    r = httpx.get(f'{API}/api/v1/ble/peers', timeout=5)
    print(f'7. After disconnect: {r.json()["data"]["peers"]}')

asyncio.run(diag())
