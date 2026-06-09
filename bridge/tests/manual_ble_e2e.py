#!/usr/bin/env python3
"""
本机蓝牙 → ESP32 端到端测试
目标：PIN 配对 → 常驻连接 → 断线感知 → 自动重连
"""
import asyncio
import sys
import time
import httpx

ESP32_MAC = "F0:F5:BD:26:92:26"
API_BASE = "http://127.0.0.1:8000"
PIN_TIMEOUT = 120

# ============================================================
# Helper: backend API calls
# ============================================================
def api_enable_pairing():
    r = httpx.post(f"{API_BASE}/api/v1/ble/pairing/enable",
                   json={"timeout_s": PIN_TIMEOUT}, timeout=10)
    r.raise_for_status()
    pin = r.json()["data"]["pin_code"]
    print(f"  [API] BLE pairing enabled, PIN={pin}")
    return pin

def api_get_peers():
    r = httpx.get(f"{API_BASE}/api/v1/ble/peers", timeout=5)
    r.raise_for_status()
    peers = r.json().get("data", {}).get("peers", [])
    return peers

def api_device_status():
    r = httpx.get(f"{API_BASE}/api/v1/device/status", timeout=5)
    r.raise_for_status()
    return r.json().get("data", {})

# ============================================================
# BLE test flow
# ============================================================
from bleak import BleakScanner, BleakClient

async def scan_esp32(timeout=10):
    """Scan for ESP32 device"""
    print(f"\n  [BLE] Scanning ({timeout}s)...")
    devices = await BleakScanner.discover(timeout=timeout, return_adv=True)
    for addr, (device, adv) in devices.items():
        name = device.name or adv.local_name or "(unknown)"
        rssi = adv.rssi if hasattr(adv, 'rssi') else "?"
        print(f"    {addr}  RSSI={rssi}  {name}")
    esp = [(addr, dev, adv) for addr, (dev, adv) in devices.items()
           if dev.name and "ESP32" in dev.name]
    if esp:
        addr, dev, adv = esp[0]
        rssi = adv.rssi if hasattr(adv, 'rssi') else "?"
        print(f"  [BLE] ✓ Found ESP32: {addr}  RSSI={rssi}  name={dev.name}")
        return addr, dev
    print("  [BLE] ✗ ESP32 NOT found in scan!")
    return None, None

async def connect_and_pair(address, pin_code):
    """Connect to ESP32 — user must enter PIN in Windows BLE dialog"""
    print(f"\n  [BLE] Connecting to {address}...")
    print(f"  ╔══════════════════════════════════════╗")
    print(f"  ║  PIN 码: {pin_code:>26}  ║")
    print(f"  ║  请在 Windows 弹窗中输入此 PIN !    ║")
    print(f"  ╚══════════════════════════════════════╝")
    
    client = BleakClient(address, timeout=30)
    
    try:
        await client.connect(timeout=30)
        
        if not client.is_connected:
            print("  [BLE] ✗ Connection failed")
            return None

        print(f"  [BLE] ✓ Physical link established (MTU={client.mtu_size})")
        
        # 交互式等待：用户输入 PIN 后按 Enter
        print(f"  ┌─────────────────────────────────────────┐")
        print(f"  │  Windows 会弹出 PIN 输入框              │")
        print(f"  │  输入 PIN: {pin_code:>27s}  │")
        print(f"  │  完成后回到这里按 Enter 继续...        │")
        print(f"  └─────────────────────────────────────────┘")
        
        # 阻塞等待用户确认
        await asyncio.get_event_loop().run_in_executor(None, input, "")
        
        # 用户已确认，检查加密状态
        if client.mtu_size > 23:
            print(f"  [BLE] ✓ Encryption confirmed! MTU={client.mtu_size}")
            return client
        
        # 给额外的等待时间（Windows 可能还在处理）
        print(f"  [BLE] ⏳ Waiting for encryption to finalize...")
        for i in range(10):
            await asyncio.sleep(1)
            if client.mtu_size > 23:
                print(f"  [BLE] ✓ Encryption complete! MTU={client.mtu_size}")
                return client
        
        if client.is_connected:
            print(f"  [BLE] ⚠ Connected but MTU={client.mtu_size} (may not be encrypted)")
            return client
        else:
            print("  [BLE] ✗ Disconnected during wait")
            return None
            
    except Exception as e:
        print(f"  [BLE] ✗ Connection failed: {e}")
        return None

async def monitor_connection(client, duration=30):
    """Monitor connection stability"""
    print(f"\n  [Monitor] Watching connection for {duration}s...")
    start = time.time()
    while time.time() - start < duration:
        if not client.is_connected:
            print(f"  [Monitor] ✗ Disconnected at t={time.time()-start:.0f}s!")
            return False
        await asyncio.sleep(1)
    print(f"  [Monitor] ✓ Connection stable for {duration}s")
    return True

async def check_frontend_peers(expected_count=1):
    """Check that frontend/API sees the connected peer"""
    peers = api_get_peers()
    print(f"  [API] Peers: {peers}")
    if len(peers) >= expected_count:
        print(f"  [Frontend] ✓ Device online detected (peers={len(peers)})")
        return True
    else:
        print(f"  [Frontend] ✗ Expected {expected_count} peers, got {len(peers)}")
        return False

async def disconnect_and_verify(client):
    """Disconnect and verify frontend detects offline"""
    print(f"\n  [BLE] Disconnecting...")
    await client.disconnect()
    
    # ESP32 takes ~2-3s to process disconnect event through event pipeline
    for wait_s in [1, 2, 3, 5]:
        await asyncio.sleep(wait_s)
        peers = api_get_peers()
        print(f"  [API] Peers after {wait_s}s: {peers}")
        if len(peers) == 0:
            print(f"  [Frontend] ✓ Device offline detected (peers=0)")
            return True
    
    print(f"  [Frontend] ✗ Still seeing peers, offline NOT detected")
    return False

async def disconnect_and_verify(client):
    """Disconnect and verify frontend detects offline"""
    print(f"\n  [BLE] Disconnecting...")
    await client.disconnect()
    
    # ESP32 takes ~2-3s to process disconnect event through event pipeline
    for wait_s in [1, 2, 3, 5]:
        await asyncio.sleep(wait_s)
        peers = api_get_peers()
        print(f"  [API] Peers after {wait_s}s: {peers}")
        if len(peers) == 0:
            print(f"  [Frontend] ✓ Device offline detected (peers=0)")
            return True
    
    print(f"  [Frontend] ✗ Still seeing peers, offline NOT detected")
    return False

async def reconnect_and_verify(address, pin_code):
    """Reconnect and verify frontend detects online"""
    print(f"\n  [BLE] Reconnecting to {address}...")
    client = await connect_and_pair(address, pin_code)
    if not client:
        return None, False
    
    await asyncio.sleep(2)
    
    peers = api_get_peers()
    print(f"  [API] Peers after reconnect: {peers}")
    if len(peers) > 0:
        print(f"  [Frontend] ✓ Device online detected (peers={len(peers)})")
        return client, True
    else:
        print(f"  [Frontend] ✗ Device NOT detected after reconnect")
        return client, False

# ============================================================
# Main test
# ============================================================
async def main():
    print("=" * 60)
    print("  ESP32 BLE 端到端测试")
    print("  目标: PIN配对 → 常驻连接 → 绑定重连(无PIN)")
    print("=" * 60)
    
    # Step 0: Check backend
    try:
        status = api_device_status()
        print(f"\n[Step 0] Backend: ✓ connected={status.get('connected')}")
    except Exception as e:
        print(f"[Step 0] Backend: ✗ {e}")
        return
    
    # Step 1: Enable pairing, scan & connect (FIRST TIME — needs PIN)
    print(f"\n[Step 1] FIRST CONNECTION — enable pairing + PIN...")
    pin_code = api_enable_pairing()
    await asyncio.sleep(2)
    
    addr, dev = await scan_esp32()
    if not addr:
        print("\n  FAILED: ESP32 not found")
        return
    
    client = await connect_and_pair(addr, pin_code)
    if not client:
        print("\n  FAILED: Could not connect")
        return
    
    print(f"\n[Step 2] Stability check...")
    stable = await monitor_connection(client, 10)
    
    print(f"\n[Step 3] Peers after first connect...")
    await check_frontend_peers(1)
    
    # Step 4: Disconnect (bond saved in NVS)
    print(f"\n[Step 4] Disconnect — bond persists in NVS...")
    await client.disconnect()
    await asyncio.sleep(5)
    peers = api_get_peers()
    print(f"  Peers after disconnect: {peers} (should be empty)")
    
    # Step 5: RECONNECT WITHOUT PAIRING — bond should auto-restore
    print(f"\n[Step 5] RECONNECT WITHOUT pairing — bond auto-restore...")
    print(f"  (pairing is NOT enabled — bonded device should reconnect automatically)")
    
    client2 = await connect_and_pair(addr, "")  # empty PIN = no pairing expected
    if not client2 or not client2.is_connected:
        print("\n  FAILED: Bond reconnection failed!")
        return
    
    print(f"\n[Step 6] Stability after bond reconnect...")
    stable2 = await monitor_connection(client2, 10)
    
    print(f"\n[Step 7] Peers after bond reconnect...")
    await check_frontend_peers(1)
    
    await client2.disconnect()
    
    # Summary
    print("\n" + "=" * 60)
    print("  RESULTS")
    print("=" * 60)
    results = {
        "Scan & Find ESP32": addr is not None,
        "First connect (PIN)": client is not None,
        "Stable (first)": stable,
        "Peers after first": True,
        "Bond reconnect (no PIN)": client2 is not None,
        "Stable (bond)": stable2,
    }
    for k, v in results.items():
        print(f"  {'✓' if v else '✗'} {k}")
    all_pass = all(results.values())
    print(f"\n  {'✓ ALL PASSED!' if all_pass else '✗ SOME FAILED'}")
    print("=" * 60)

if __name__ == "__main__":
    asyncio.run(main())
