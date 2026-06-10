import { useDeviceStore } from '../../stores/deviceStore';
import { api } from '../../services/api';

export function StatusPanel() {
  const uartStates = useDeviceStore((s) => s.uartStates);
  const bleState = useDeviceStore((s) => s.bleState);
  const config = useDeviceStore((s) => s.hardwareConfig);
  const mismatchPins = useDeviceStore((s) => s.mismatchPins);
  const updateUart = useDeviceStore((s) => s.updateUart);
  const lockedPins = useDeviceStore((s) => s.lockedPins);
  const toggleLock = useDeviceStore((s) => s.toggleLock);
  const addHistory = useDeviceStore((s) => s.addHistory);
  const now = () => new Date().toLocaleTimeString();

  const pinLabel = (gpio: number) => config?.pins.find(p => p.gpio === gpio)?.label ?? `GPIO${gpio}`;

  const boundUarts = Object.entries(uartStates).filter(([, u]) => u.bound);

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

      {/* BLE Status */}
      <div>
        <h3 className="text-xs font-semibold text-gray-400 mb-2">📶 蓝牙</h3>
        <div className="bg-gray-800 rounded p-2 text-xs space-y-1">
          <div className="flex justify-between">
            <span className="text-gray-500">配对</span>
            <span className={bleState.pairingEnabled ? 'text-green-400' : 'text-gray-600'}>
              {bleState.pairingEnabled ? '已启用' : '已停用'}
            </span>
          </div>
          <div className="flex justify-between">
            <span className="text-gray-500">扫描</span>
            <span className={bleState.scanEnabled ? 'text-green-400' : 'text-gray-600'}>
              {bleState.scanEnabled ? '扫描中' : '已停止'}
            </span>
          </div>
          <div className="flex justify-between">
            <span className="text-gray-500">已连接设备</span>
            <span className="text-white font-mono">{bleState.peerCount}</span>
          </div>
        </div>
      </div>
    </div>
  );
}
