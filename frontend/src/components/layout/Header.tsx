import { useDeviceStore } from '../../stores/deviceStore';

interface Props {
  onOpenCustomCmds?: () => void;
}

export function Header({ onOpenCustomCmds }: Props) {
  const connected = useDeviceStore((s) => s.connected);
  const config = useDeviceStore((s) => s.hardwareConfig);

  return (
    <header className="flex items-center justify-between px-4 py-2 bg-gray-900 border-b border-gray-700 shrink-0">
      <div className="flex items-center gap-3">
        <span className="text-xl">🌹</span>
        <span className="font-bold text-lg">{config?.chip.name || 'Rose-ESP32'}</span>
        <span className="text-xs text-gray-500 hidden sm:inline">IoT Agent</span>
      </div>
      <div className="flex items-center gap-3">
        {onOpenCustomCmds && (
          <button
            onClick={onOpenCustomCmds}
            className="flex items-center gap-1 px-2.5 py-1 bg-gray-800 hover:bg-gray-700 border border-gray-600 rounded text-xs text-gray-300 hover:text-white transition-colors"
            title="自定义指令 — 跨协议组合指令"
          >
            📋 指令
          </button>
        )}
        <span className={`inline-flex items-center gap-1 text-sm ${connected ? 'text-green-400' : 'text-red-400'}`}>
          <span className={`w-2 h-2 rounded-full ${connected ? 'bg-green-400' : 'bg-red-400'}`} />
          {connected ? '已连接' : '未连接'}
        </span>
      </div>
    </header>
  );
}
