import { useState, useEffect, useCallback } from 'react';
import { useDeviceStore } from '../../stores/deviceStore';
import { api } from '../../services/api';

function fmtMac(mac: string): string {
  return mac.length === 17 ? mac : mac;
}

export function StatusPanel() {
  const connected = useDeviceStore((s) => s.connected);
  const uartStates = useDeviceStore((s) => s.uartStates);
  const bleState = useDeviceStore((s) => s.bleState);
  const blePeers = useDeviceStore((s) => s.blePeers);
  const setBlePeers = useDeviceStore((s) => s.setBlePeers);
  const config = useDeviceStore((s) => s.hardwareConfig);
  const mismatchPins = useDeviceStore((s) => s.mismatchPins);
  const updateUart = useDeviceStore((s) => s.updateUart);
  const lockedPins = useDeviceStore((s) => s.lockedPins);
  const toggleLock = useDeviceStore((s) => s.toggleLock);
  const addHistory = useDeviceStore((s) => s.addHistory);
  const now = () => new Date().toLocaleTimeString();

  const pinLabel = (gpio: number) => config?.pins.find(p => p.gpio === gpio)?.label ?? `GPIO${gpio}`;

  const boundUarts = Object.entries(uartStates).filter(([, u]) => u.bound);

  // BLE state
  const [pairingCode, setPairingCode] = useState<string | null>(null);
  const [deviceNames, setDeviceNames] = useState<Record<string, string>>({});
  const [editingMac, setEditingMac] = useState<string | null>(null);
  const [editName, setEditName] = useState('');

  // Load device names from platform
  const loadDeviceNames = useCallback(async () => {
    try {
      const res = await api.listBleDeviceNames() as { data: { names: { mac: string; name: string }[] } };
      const map: Record<string, string> = {};
      for (const n of res.data.names) {
        map[n.mac] = n.name;
      }
      setDeviceNames(map);
    } catch { /* ignore */ }
  }, []);

  useEffect(() => { loadDeviceNames(); }, [loadDeviceNames]);

  // Sync pairing code display with BLE state
  useEffect(() => {
    if (!bleState.pairingEnabled) setPairingCode(null);
  }, [bleState.pairingEnabled]);

  const refreshPeers = useCallback(async () => {
    try {
      const res = await api.blePeers() as { data: { peers: { mac: string; rssi: number }[] } };
      setBlePeers(res.data.peers || []);
      useDeviceStore.getState().setBleState({
        ...useDeviceStore.getState().bleState,
        peerCount: (res.data.peers || []).length,
      });
    } catch { /* ignore */ }
  }, [setBlePeers]);

  const handleEnablePairing = async () => {
    try {
      const res = await api.blePairingEnable(60) as { data: { pin_code?: string } };
      setPairingCode(res.data?.pin_code || null);
      useDeviceStore.getState().setBleState({ ...useDeviceStore.getState().bleState, pairingEnabled: true });
      addHistory({ time: now(), op: 'BLE 配对', result: '✓ 已启用 (60s超时)' });
    } catch (e: unknown) {
      addHistory({ time: now(), op: 'BLE 配对', result: '✗ ' + (e as Error).message });
    }
  };

  const handleDisablePairing = async () => {
    try {
      await api.blePairingDisable();
      setPairingCode(null);
      useDeviceStore.getState().setBleState({ ...useDeviceStore.getState().bleState, pairingEnabled: false });
      addHistory({ time: now(), op: 'BLE 配对', result: '✓ 已停用' });
    } catch (e: unknown) {
      addHistory({ time: now(), op: 'BLE 配对', result: '✗ ' + (e as Error).message });
    }
  };

  const handleSaveDeviceName = async (mac: string) => {
    if (!editName.trim()) return;
    try {
      await api.setBleDeviceName(mac, editName.trim());
      setDeviceNames((prev) => ({ ...prev, [mac]: editName.trim() }));
      setEditingMac(null);
      addHistory({ time: now(), op: 'BLE 设备名', result: `✓ ${mac} → ${editName.trim()}` });
    } catch (e: unknown) {
      addHistory({ time: now(), op: 'BLE 设备名', result: '✗ ' + (e as Error).message });
    }
  };

  const getDisplayName = (mac: string): string => {
    const name = deviceNames[mac];
    return name ? `${name} (${mac})` : mac;
  };

  const handleUnbindUart = async (uartId: number) => {
    if (!confirm(`确认解绑 UART${uartId}？`)) return;
    try {
      const uart = uartStates[uartId];
      await api.portUnbind(1, uartId);
      updateUart(uartId, { bound: false, tx_gpio: 0, rx_gpio: 0 } as never);
      if (uart?.tx_gpio != null && lockedPins.has(uart.tx_gpio)) toggleLock(uart.tx_gpio);
      if (uart?.rx_gpio != null && lockedPins.has(uart.rx_gpio)) toggleLock(uart.rx_gpio);
      addHistory({ time: now(), op: `UART${uartId} 解绑`, result: '✓' });
    } catch (e: unknown) {
      addHistory({ time: now(), op: `UART${uartId} 解绑`, result: `✗ ${(e as Error).message}` });
    }
  };

  return (
    <div className="flex-1 overflow-y-auto p-3 space-y-4">
      {/* Mismatch warnings */}
      {mismatchPins.size > 0 && (
        <div className="bg-red-900/40 border border-red-800 rounded p-2 text-xs">
          <div className="text-red-400 font-medium mb-1">⚠ 配置不一致 ({mismatchPins.size})</div>
          <div className="text-red-300/70">
            以下引脚的实际状态与保存的预期配置不同：
            {[...mismatchPins].slice(0, 8).map((gpio) => (
              <span key={gpio} className="inline-block bg-red-900/60 px-1.5 py-0.5 rounded mr-1 mt-1 font-mono">
                {pinLabel(gpio)}
              </span>
            ))}
            {mismatchPins.size > 8 && <span className="text-gray-500"> +{mismatchPins.size - 8} more</span>}
          </div>
        </div>
      )}

      {/* UART Status */}
      <div>
        <h3 className="text-xs font-semibold text-gray-400 mb-2">UART 接口</h3>
        {boundUarts.length === 0 ? (
          <div className="text-xs text-gray-600 italic">无已绑定 UART</div>
        ) : (
          boundUarts.map(([id, u]) => (
            <div key={id} className="bg-gray-800 rounded p-2 mb-1.5 text-xs group">
              <div className="flex items-center justify-between mb-1">
                <span className="text-blue-400 font-bold">UART{id}</span>
                <span className="text-gray-500">{u.baudrate} baud</span>
              </div>
              <div className="flex items-center justify-between">
                <div className="flex gap-2 text-[10px]">
                  <span className="text-sky-400">TX: {pinLabel(u.tx_gpio)}</span>
                  <span className="text-orange-400">RX: {pinLabel(u.rx_gpio)}</span>
                </div>
                <button
                  onClick={() => handleUnbindUart(Number(id))}
                  className="opacity-0 group-hover:opacity-100 text-[10px] text-red-500 hover:text-red-400 transition-all"
                  title="解绑此 UART"
                >
                  ✕ 解绑
                </button>
              </div>
            </div>
          ))
        )}
      </div>

      {/* BLE Status & Controls */}
      <div>
        <h3 className="text-xs font-semibold text-gray-400 mb-2">📶 蓝牙</h3>
        <div className="bg-gray-800 rounded p-2 text-xs space-y-2">
          {/* Status info */}
          <div className="flex justify-between">
            <span className="text-gray-500">配对</span>
            <span className={bleState.pairingEnabled ? 'text-green-400' : 'text-gray-600'}>
              {bleState.pairingEnabled ? '已启用' : '已停用'}
            </span>
          </div>
          <div className="flex justify-between">
            <span className="text-gray-500">已连接设备</span>
            <span className="text-white font-mono">{blePeers.length}</span>
          </div>

          {/* Pairing controls - only one button */}
          <div className="flex gap-1.5 pt-1">
            {!bleState.pairingEnabled ? (
              <button
                onClick={handleEnablePairing}
                disabled={!connected}
                className="flex-1 py-1.5 bg-blue-700 hover:bg-blue-600 disabled:opacity-40 rounded text-xs"
              >
                启用配对
              </button>
            ) : (
              <button
                onClick={handleDisablePairing}
                className="flex-1 py-1.5 bg-red-800 hover:bg-red-700 rounded text-xs"
              >
                {pairingCode ? `停用配对 (${pairingCode})` : '停用配对'}
              </button>
            )}
            <button
              onClick={refreshPeers}
              className="py-1.5 px-2 bg-gray-700 hover:bg-gray-600 rounded text-xs"
              title="刷新设备列表"
            >
              🔄
            </button>
          </div>

          {/* PIN display */}
          {pairingCode && (
            <div className="bg-yellow-400/10 border border-yellow-500/30 rounded p-2 text-center">
              <div className="text-[10px] text-yellow-400/70 mb-0.5">配对 PIN 码</div>
              <div className="text-lg font-bold font-mono tracking-[0.25em] text-yellow-400">
                {pairingCode}
              </div>
            </div>
          )}

          {/* Peers list with rename */}
          <div className="text-xs text-gray-500 max-h-48 overflow-y-auto border-t border-gray-700 pt-1.5">
            <div className="text-gray-600 mb-1">已连接设备</div>
            {blePeers.length === 0 ? (
              <div className="italic text-gray-700 py-1">暂无已连接设备</div>
            ) : (
              blePeers.map((p, i) => (
                <div key={i} className="py-1 border-b border-gray-700 last:border-0">
                  {editingMac === p.mac ? (
                    <div className="flex gap-1">
                      <input
                        value={editName}
                        onChange={(e) => setEditName(e.target.value)}
                        onKeyDown={(e) => { if (e.key === 'Enter') handleSaveDeviceName(p.mac); if (e.key === 'Escape') setEditingMac(null); }}
                        placeholder="输入设备名"
                        className="flex-1 bg-gray-700 border border-gray-600 rounded px-1.5 py-0.5 text-xs text-gray-200 font-mono"
                        autoFocus
                        spellCheck={false}
                      />
                      <button onClick={() => handleSaveDeviceName(p.mac)} className="text-green-400 hover:text-green-300 text-[10px] px-1">✓</button>
                      <button onClick={() => setEditingMac(null)} className="text-gray-500 hover:text-gray-400 text-[10px] px-1">✕</button>
                    </div>
                  ) : (
                    <div className="flex items-center justify-between group">
                      <div className="flex items-center gap-1.5 min-w-0 flex-1">
                        <span className="w-1.5 h-1.5 rounded-full bg-green-500 flex-shrink-0" title="已连接" />
                        <span className="text-gray-300 truncate" title={p.mac}>
                          {getDisplayName(p.mac)}
                        </span>
                      </div>
                      <div className="flex items-center gap-1 flex-shrink-0">
                        <button
                          onClick={() => { setEditingMac(p.mac); setEditName(deviceNames[p.mac] || ''); }}
                          className="text-[10px] text-gray-600 hover:text-blue-400 opacity-0 group-hover:opacity-100 transition-all"
                          title="重命名"
                        >
                          ✏️
                        </button>
                        <span className={p.rssi > -50 ? 'text-green-400' : p.rssi > -70 ? 'text-yellow-400' : 'text-red-400'}>
                          {p.rssi}dBm
                        </span>
                      </div>
                    </div>
                  )}
                </div>
              ))
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
