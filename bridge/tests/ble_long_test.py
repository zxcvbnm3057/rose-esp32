"""长时间 BLE 连接测试"""
import asyncio, httpx, time
from bleak import BleakClient, BleakScanner

ESP32 = 'F0:F5:BD:26:92:26'
API = 'http://127.0.0.1:8000'

async def long_test():
    # 1. Check initial state
    r = httpx.get(f'{API}/api/v1/ble/peers', timeout=5)
    print(f'Init peers: {r.json()["data"]["peers"]}')
    
    # 2. Scan
    devs = await BleakScanner.discover(timeout=3, return_adv=True)
    esp = [a for a, (d, _) in devs.items() if d.name and 'ESP32' in d.name]
    print(f'Scan ESP32: {esp}')
    if not esp:
        print('ESP32 not found!')
        return
    
    # 3. Enable pairing
    r = httpx.post(f'{API}/api/v1/ble/pairing/enable', json={'timeout_s': 120}, timeout=10)
    pin = r.json()['data']['pin_code']
    print(f'PIN: {pin}')
    
    # 4. Connect
    print(f'Connecting...')
    client = BleakClient(ESP32, timeout=15)
    t0 = time.time()
    await client.connect()
    print(f'Connected in {time.time()-t0:.1f}s, MTU={client.mtu_size}')
    
    # 5. Long monitoring
    print('\n--- Monitoring (check every 5s) ---')
    start = time.time()
    last_report = start
    while time.time() - start < 35:
        await asyncio.sleep(5)
        elapsed = time.time() - start
        pc_ok = client.is_connected
        
        r = httpx.get(f'{API}/api/v1/ble/peers', timeout=5)
        esp_peers = r.json()['data']['peers']
        
        print(f'  t={elapsed:4.0f}s  PC:{"✓" if pc_ok else "✗"}  ESP32 peers:{esp_peers}')
        
        if not pc_ok:
            print(f'  *** PC disconnected at t={elapsed:.0f}s! ***')
            break
    
    final_ok = client.is_connected
    print(f'\nFinal: PC connected={final_ok}, elapsed={time.time()-start:.0f}s')
    
    if client.is_connected:
        await client.disconnect()
        await asyncio.sleep(2)
    
    r = httpx.get(f'{API}/api/v1/ble/peers', timeout=5)
    print(f'After disconnect: {r.json()["data"]["peers"]}')

asyncio.run(long_test())
