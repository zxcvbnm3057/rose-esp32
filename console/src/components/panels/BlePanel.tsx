import { useState, useEffect, useCallback } from 'react';
import { useDeviceStore } from '../../stores/deviceStore';
import { api } from '../../services/api';

export function BlePanel() {
  const connected = useDeviceStore((s) => s.connected);
  const bleState = useDeviceStore((s) => s.bleState);
  const blePeers = useDeviceStore((s) => s.blePeers);
  const setBlePeers = useDeviceStore((s) => s.setBlePeers);
  const addHistory = useDeviceStore((s) => s.addHistory);
  const now = () => new Date().toLocaleTimeString();
  const [pairingCode, setPairingCode] = useState<string | null>(null);
  const [scanning, setScanning] = useState(false);
  const [collapsed, setCollapsed] = useState(true);
  const [refreshingMac, setRefreshingMac] = useState<string | null>(null);

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

  // Sync pairing code display with BLE state
  useEffect(() => {
    if (!bleState.pairingEnabled) setPairingCode(null);
  }, [bleState.pairingEnabled]);

  // Auto-refresh peers list when connected or peerCount changes
  useEffect(() => {
    if (connected && bleState.peerCount > 0) {
      refreshPeers();
    }
  }, [connected, bleState.peerCount, refreshPeers]);

  const handleEnablePairing = async () => {
    try {
      const res = await api.blePairingEnable(120) as { data: { pin_code?: string } };
      setPairingCode(res.data?.pin_code || null);
      useDeviceStore.getState().setBleState({ ...useDeviceStore.getState().bleState, pairingEnabled: true });
      addHistory({ time: now(), op: 'BLE 配对', result: '✓ 已启用 (Just Works, PIN仅供参考)' });
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

  const handleStartScan = async () => {
    try {
      await api.bleScanStart(10);
      setScanning(true);
      useDeviceStore.getState().setBleState({ ...useDeviceStore.getState().bleState, scanEnabled: true });
      addHistory({ time: now(), op: 'BLE RSSI 扫描', result: '✓ 已开始' });
    } catch (e: unknown) {
      addHistory({ time: now(), op: 'BLE RSSI 扫描', result: '✗ ' + (e as Error).message });
    }
  };

  const handleStopScan = async () => {
    try {
      await api.bleScanStop();
      setScanning(false);
      useDeviceStore.getState().setBleState({ ...useDeviceStore.getState().bleState, scanEnabled: false });
      addHistory({ time: now(), op: 'BLE RSSI 扫描', result: '✓ 已停止' });
    } catch (e: unknown) {
      addHistory({ time: now(), op: 'BLE RSSI 扫描', result: '✗ ' + (e as Error).message });
    }
  };

  const refreshSingleRssi = async (mac: string) => {
    setRefreshingMac(mac);
    await refreshPeers();
    setRefreshingMac(null);
    addHistory({ time: now(), op: 'BLE RSSI', result: '🔄 刷新 ' + mac.slice(0, 17) });
  };

  if (!connected) return null;

  const pairingActive = pairingCode != null;
  const pairingEnabled = bleState.pairingEnabled;
  const scanActive = scanning || bleState.scanEnabled;

  return (
    <div className="border-t border-gray-700 bg-gray-950">
      <div className="flex items-center justify-between px-3 py-1.5 border-b border-gray-800 bg-gray-900">
        <button
          onClick={() => setCollapsed(!collapsed)}
          className="text-gray-400 text-xs font-medium flex items-center gap-2"
        >
          <span className={`w-1.5 h-1.5 rounded-full ${blePeers.length > 0 ? 'bg-green-500' : 'bg-blue-500'}`} />
          📶 BLE{blePeers.length > 0 ? ` (${blePeers.length})` : ''}
          <span className="text-gray-600">{collapsed ? '▶' : '▼'}</span>
        </button>
        <div className="flex items-center gap-2">
          {pairingCode && (
            <span className="text-base text-yellow-400 font-bold font-mono tracking-widest bg-yellow-400/10 px-2 py-0.5 rounded" title="在手机上输入此 PIN">
              🔑 {pairingCode}
            </span>
          )}
          <button onClick={refreshPeers} className="text-[10px] text-gray-600 hover:text-gray-400">
            refresh
          </button>
        </div>
      </div>

      {!collapsed && (
        <div className="px-3 py-2 space-y-2">
          {/* PIN display — big & obvious when pairing */}
          {pairingCode && (
            <div className="bg-yellow-400/10 border border-yellow-500/30 rounded-lg p-3 text-center">
              <div className="text-[11px] text-yellow-400/70 mb-1">配对 PIN 码 — 在手机/电脑蓝牙配对弹窗中输入</div>
              <div className="text-2xl font-bold font-mono tracking-[0.3em] text-yellow-400">
                {pairingCode}
              </div>
            </div>
          )}

          {/* Pairing controls */}
          <div className="flex gap-1.5">
            <button
              onClick={handleEnablePairing}
              disabled={pairingEnabled || pairingActive}
              className="flex-1 py-1.5 bg-blue-700 hover:bg-blue-600 disabled:opacity-40 rounded text-xs"
            >
              {pairingActive ? '配对中…' : pairingEnabled ? '已启用' : '启用配对'}
            </button>
            <button
              onClick={handleDisablePairing}
              disabled={!pairingEnabled && !pairingActive}
              className="flex-1 py-1.5 bg-gray-700 hover:bg-gray-600 disabled:opacity-40 rounded text-xs"
            >
              停用配对
            </button>
          </div>

          {/* Scan controls */}
          <div className="flex gap-1.5">
            <button
              onClick={handleStartScan}
              disabled={scanActive}
              className="flex-1 py-1.5 bg-teal-700 hover:bg-teal-600 disabled:opacity-40 rounded text-xs"
            >
              {scanActive ? '扫描中…' : '开始扫描'}
            </button>
            <button
              onClick={handleStopScan}
              disabled={!scanActive}
              className="flex-1 py-1.5 bg-gray-700 hover:bg-gray-600 disabled:opacity-40 rounded text-xs"
            >
              停止扫描
            </button>
          </div>

          {/* Peers list */}
          <div className="text-xs text-gray-500 max-h-40 overflow-y-auto">
            <div className="flex items-center justify-between mb-1">
              <span className="text-gray-600">已连接设备</span>
              <button
                onClick={refreshPeers}
                className="text-[10px] text-gray-600 hover:text-blue-400 transition-colors"
                title="刷新设备列表及信号强度"
              >
                🔄 刷新信号
              </button>
            </div>
            {blePeers.length === 0 ? (
              <div className="italic text-gray-700 py-2">暂无已连接设备 — 启用配对后其他设备可连接</div>
            ) : (
              blePeers.map((p, i) => (
                <div key={i} className="flex items-center justify-between py-1 border-b border-gray-800 last:border-0 group">
                  <div className="flex items-center gap-1.5 min-w-0">
                    <span className="w-1.5 h-1.5 rounded-full bg-green-500 flex-shrink-0" title="已连接" />
                    <span className="font-mono text-gray-400 truncate">{p.mac}</span>
                  </div>
                  <div className="flex items-center gap-2 flex-shrink-0">
                    <span className={p.rssi > -50 ? 'text-green-400' : p.rssi > -70 ? 'text-yellow-400' : 'text-red-400'}>
                      {p.rssi} dBm
                    </span>
                    <button
                      onClick={(e) => { e.stopPropagation(); refreshSingleRssi(p.mac); }}
                      disabled={refreshingMac === p.mac}
                      className={`text-[10px] transition-all ${
                        refreshingMac === p.mac ? 'text-blue-400 animate-pulse' : 'text-gray-600 hover:text-blue-400 opacity-0 group-hover:opacity-100'
                      }`}
                      title="刷新信号强度"
                    >
                      {refreshingMac === p.mac ? '⏳' : '🔍'}
                    </button>
                  </div>
                </div>
              ))
            )}
          </div>
        </div>
      )}
    </div>
  );
}
