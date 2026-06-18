import { useState, useRef, useEffect, useCallback } from 'react';
import { useDeviceStore } from '../../stores/deviceStore';
import { api } from '../../services/api';

const COLORS = ['#eab308', '#22d3ee', '#a78bfa', '#f472b6', '#34d399', '#fb923c'];

function fmtHex(bytes: number[]): string {
  return bytes.map((b) => b.toString(16).padStart(2, '0').toUpperCase()).join(' ');
}

function fmtAscii(bytes: number[]): string {
  return bytes.map((b) => (b >= 0x20 && b <= 0x7e ? String.fromCharCode(b) : '.')).join('');
}

export function UartConsole() {
  const uartStates = useDeviceStore((s) => s.uartStates);
  const uartMessages = useDeviceStore((s) => s.uartMessages);
  const clearUartMessages = useDeviceStore((s) => s.clearUartMessages);
  const connected = useDeviceStore((s) => s.connected);

  const scrollRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const [input, setInput] = useState('');
  const [selectedUart, setSelectedUart] = useState<number | null>(null);
  const [hexMode, setHexMode] = useState(true);
  const [displayHex, setDisplayHex] = useState(true);
  const [collapsed, setCollapsed] = useState(true);

  // Auto-scroll to bottom on new messages
  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [uartMessages]);

  // Default select first bound UART
  const boundIds = Object.keys(uartStates).map(Number).filter((id) => {
    const u = uartStates[id];
    return u.tx_gpio != null && u.rx_gpio != null;
  });
  useEffect(() => {
    if (selectedUart == null && boundIds.length > 0) {
      setSelectedUart(boundIds[0]);
    }
  }, [boundIds, selectedUart]);

  const handleSend = useCallback(async () => {
    if (selectedUart == null || !input.trim()) return;
    try {
      if (hexMode) {
        const hex = input.trim();
        if (!/^[0-9a-fA-F\s]+$/.test(hex)) return;
        await api.uartSendHex(selectedUart, hex);
        const bytes = hex.split(/\s+/).filter(Boolean).map((h) => parseInt(h, 16));
        useDeviceStore.getState().addUartMessage({
          uart_id: selectedUart, dir: 'tx', data: bytes, timestamp: Date.now(),
        });
      } else {
        await api.uartSend(selectedUart, input);
        const bytes = Array.from(input, (c) => c.charCodeAt(0));
        useDeviceStore.getState().addUartMessage({
          uart_id: selectedUart, dir: 'tx', data: bytes, timestamp: Date.now(),
        });
      }
      setInput('');
    } catch { /* ignore */ }
  }, [selectedUart, input, hexMode]);

  const handleKeyDown = useCallback((e: React.KeyboardEvent) => {
    if (e.key === 'Enter') handleSend();
  }, [handleSend]);

  if (boundIds.length === 0) return null;

  return (
    <div className="border-t border-gray-700 bg-gray-950 flex flex-col">
      {/* Header */}
      <div className="flex items-center justify-between px-3 py-1.5 border-b border-gray-800 bg-gray-900 shrink-0">
        <button
          onClick={() => setCollapsed(!collapsed)}
          className="text-gray-400 text-xs font-medium flex items-center gap-2"
        >
          <span className="w-1.5 h-1.5 rounded-full bg-green-500 animate-pulse" />
          UART Monitor
          <span className="text-gray-600">{collapsed ? '▶' : '▼'}</span>
        </button>
        <div className="flex items-center gap-2">
          <button
            onClick={() => setDisplayHex(!displayHex)}
            className={`text-[10px] px-1.5 py-0.5 rounded ${displayHex ? 'bg-blue-700 text-blue-200' : 'bg-gray-700 text-gray-400'}`}
            title="切换 16进制/ASCII 显示"
          >
            {displayHex ? 'HEX' : 'ASC'}
          </button>
          <button
            onClick={() => clearUartMessages()}
            className="text-xs text-gray-600 hover:text-gray-400"
          >
            clear
          </button>
        </div>
      </div>

      {!collapsed && (
        <>
      {/* Messages */}
      <div ref={scrollRef} className="overflow-y-auto px-3 py-1 font-mono text-xs leading-5" style={{ height: 140 }}>
        {uartMessages.length === 0 && (
          <div className="text-gray-600 italic">等待 UART 消息…</div>
        )}
        {uartMessages.map((msg, i) => {
          const colorIdx = (msg.uart_id % COLORS.length);
          const color = COLORS[colorIdx];
          const dirChar = msg.dir === 'rx' ? '←' : '→';
          const formatted = displayHex ? fmtHex(msg.data) : fmtAscii(msg.data);
          return (
            <div key={i} className="flex gap-2 hover:bg-gray-900/50">
              <span className="text-gray-600 shrink-0 w-14 text-right">
                {new Date(msg.timestamp).toLocaleTimeString('zh', {
                  hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit',
                })}
              </span>
              <span style={{ color }} className="shrink-0 font-bold">
                UART{msg.uart_id}&gt;
              </span>
              <span className="text-gray-500 w-3 shrink-0 text-center">{dirChar}</span>
              <span className="text-gray-300 break-all">{formatted}</span>
            </div>
          );
        })}
      </div>

      {/* Input */}
      <div className="flex items-center gap-1 px-3 py-1.5 border-t border-gray-800 bg-gray-900 shrink-0">
        <select
          value={selectedUart ?? ''}
          onChange={(e) => setSelectedUart(e.target.value ? Number(e.target.value) : null)}
          className="bg-gray-800 border border-gray-600 rounded px-1.5 py-0.5 text-xs text-gray-300 shrink-0"
        >
          {boundIds.map((id) => (
            <option key={id} value={id}>UART{id}</option>
          ))}
        </select>
        <span className="text-gray-600 text-xs shrink-0">&lt;&lt;</span>
        <button
          onClick={() => setHexMode(!hexMode)}
          className={`text-[10px] px-1.5 py-0.5 rounded shrink-0 ${
            hexMode ? 'bg-blue-700 text-blue-200' : 'bg-emerald-700 text-emerald-200'
          }`}
          title={hexMode ? '当前: 16进制输入' : '当前: 文本输入'}
        >
          {hexMode ? 'HEX' : 'TXT'}
        </button>
        <input
          ref={inputRef}
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          disabled={!connected}
          placeholder={hexMode ? 'HEX bytes e.g. FE EE' : 'Text e.g. hello'}
          className="flex-1 bg-gray-800 border border-gray-600 rounded px-2 py-0.5 text-xs text-gray-200 font-mono placeholder-gray-600 focus:outline-none focus:border-gray-500"
          spellCheck={false}
        />
        <button
          onClick={handleSend}
          disabled={!connected || !input.trim()}
          className="bg-gray-700 hover:bg-gray-600 disabled:opacity-40 rounded px-2 py-0.5 text-xs text-gray-300 shrink-0"
        >
          Send
        </button>
      </div>
        </>
      )}
    </div>
  );
}
