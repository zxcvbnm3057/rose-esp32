import { useEffect, useState, useCallback } from 'react';
import { Header } from './components/layout/Header';
import { ChipView } from './components/chip/ChipView';
import { PinConfigSheet } from './components/panels/PinConfigSheet';
import { StatusPanel } from './components/panels/StatusPanel';
import { BlePanel } from './components/panels/BlePanel';
import { WaveformPanel } from './components/panels/WaveformPanel';
import { UartConsole } from './components/panels/UartConsole';
import { CustomCmdEditor } from './components/custom-cmds/CustomCmdEditor';
import { CustomCmdListPanel } from './components/custom-cmds/CustomCmdListPanel';
import { useWebSocket } from './hooks/useWebSocket';
import { api } from './services/api';
import { useDeviceStore } from './stores/deviceStore';
import type { HardwareConfig } from './types';

type RightTab = 'status' | 'customCmds';

export default function App() {
  useWebSocket();
  const setConfig = useDeviceStore((s) => s.setHardwareConfig);
  const selectedGpio = useDeviceStore((s) => s.selectedGpio);

  // Custom command editor modal
  const [editingSlug, setEditingSlug] = useState<string | null>(null);
  const [cmdRefreshKey, setCmdRefreshKey] = useState(0);
  const [rightTab, setRightTab] = useState<RightTab>('status');

  // Fallback: fetch hardware config if WebSocket hasn't delivered it yet
  useEffect(() => {
    const timer = setTimeout(async () => {
      const state = useDeviceStore.getState();
      if (!state.hardwareConfig) {
        try {
          const res = await api.getHardwareConfig() as { data: HardwareConfig };
          setConfig(res.data);
        } catch { /* ignore */ }
      }
    }, 2000);
    return () => clearTimeout(timer);
  }, []);

  // Load persisted locks + expected states from backend on mount
  useEffect(() => {
    (async () => {
      try {
        const res = await api.getLocks();
        const locks = res.data || [];
        const store = useDeviceStore.getState();
        store.setExpectedGpios(locks);
        store.loadLocks(locks.filter((l) => l.locked).map((l) => l.gpio));
      } catch { /* ignore */ }
    })();
  }, []);

  const handleCloseEditor = useCallback(() => {
    setEditingSlug(null);
    setCmdRefreshKey((k) => k + 1);
  }, []);
  const handleCmdSaved = useCallback(() => {
    setEditingSlug(null);
    setCmdRefreshKey((k) => k + 1);
  }, []);

  return (
    <div className="h-screen flex flex-col bg-gray-950 text-gray-200">
      <Header onOpenCustomCmds={() => { setRightTab('customCmds'); setEditingSlug(''); }} />

      {/* Main area: chip view + right panel */}
      <div className="flex-1 flex overflow-hidden">
        {/* Center: chip view — click pins to interact */}
        <div className="flex-1 overflow-auto">
          <ChipView />
        </div>

        {/* Right panel: device status / pin config / custom commands */}
        <div className="w-80 border-l border-gray-700 bg-gray-900 flex flex-col overflow-hidden shrink-0">
          {selectedGpio != null ? (
            <PinConfigSheet embedded />
          ) : (
            <>
              {/* Tab bar */}
              <div className="flex border-b border-gray-700 shrink-0">
                <button
                  onClick={() => setRightTab('status')}
                  className={`flex-1 py-2 text-xs font-medium ${
                    rightTab === 'status'
                      ? 'text-blue-400 border-b-2 border-blue-400 bg-gray-800'
                      : 'text-gray-500 hover:text-gray-300'
                  }`}
                >
                  设备状态
                </button>
                <button
                  onClick={() => setRightTab('customCmds')}
                  className={`flex-1 py-2 text-xs font-medium ${
                    rightTab === 'customCmds'
                      ? 'text-blue-400 border-b-2 border-blue-400 bg-gray-800'
                      : 'text-gray-500 hover:text-gray-300'
                  }`}
                >
                  自定义指令
                </button>
              </div>

              {rightTab === 'status' ? (
                <StatusPanel />
              ) : (
                <CustomCmdListPanel
                  onEdit={(slug) => setEditingSlug(slug)}
                  onCreate={() => setEditingSlug('')}
                  refreshKey={cmdRefreshKey}
                />
              )}
            </>
          )}
        </div>
      </div>

      {/* Bottom panels: waveform + UART console */}
      <WaveformPanel />
      <UartConsole />

      {/* BLE controller (collapsible) */}
      <BlePanel />

      {/* Custom command editor modal */}
      {editingSlug !== null && (
        <CustomCmdEditor
          slug={editingSlug || undefined}
          onClose={handleCloseEditor}
          onSaved={handleCmdSaved}
        />
      )}
    </div>
  );
}
