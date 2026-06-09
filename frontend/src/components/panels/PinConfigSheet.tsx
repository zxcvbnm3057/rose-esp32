import { useState, useEffect, useMemo } from 'react';
import { useDeviceStore, getUartForGpio, getAvailableUartPins } from '../../stores/deviceStore';
import { api } from '../../services/api';
import type { PinConfig } from '../../types';

// ── Types ──────────────────────────────────────────

type PanelMode = 'gpio' | 'uart_setup' | 'uart_active';

interface Props {
  embedded?: boolean;
}

// ── Component ──────────────────────────────────────

export function PinConfigSheet({ embedded }: Props) {
  const config = useDeviceStore((s) => s.hardwareConfig);
  const selectedGpio = useDeviceStore((s) => s.selectedGpio);
  const selectGpio = useDeviceStore((s) => s.selectGpio);
  const pinState = useDeviceStore((s) => selectedGpio != null ? s.pinStates[selectedGpio] : undefined);
  const uartStates = useDeviceStore((s) => s.uartStates);
  const updateUart = useDeviceStore((s) => s.updateUart);
  const addHistory = useDeviceStore((s) => s.addHistory);

  // ── Determine panel mode ──
  const uartInfo = useMemo(() => {
    if (selectedGpio == null) return null;
    return getUartForGpio(uartStates, selectedGpio);
  }, [selectedGpio, uartStates]);

  const pin: PinConfig | undefined = selectedGpio != null
    ? config?.pins.find((p) => p.gpio === selectedGpio)
    : undefined;

  // Initial panel mode: if pin is uart-bound → uart_active, else gpio
  const [panelMode, setPanelMode] = useState<PanelMode>('gpio');

  useEffect(() => {
    if (uartInfo) {
      setPanelMode('uart_active');
    } else {
      setPanelMode('gpio');
    }
  }, [selectedGpio, uartInfo]);

  // ── GPIO config state ──
  const [mode, setMode] = useState(0);
  const [pull, setPull] = useState(0);
  const [edge, setEdge] = useState(0);
  const [outValue, setOutValue] = useState(0);
  const [samples, setSamples] = useState(4);

  useEffect(() => {
    if (pin && panelMode === 'gpio') {
      setMode(pinState?.mode_code ?? 0);
      setPull(pinState?.pull_code ?? 0);
      setEdge(pinState?.edge ?? 0);
      setOutValue(pinState?.value ?? 0);
    }
  }, [selectedGpio, pinState, panelMode]);

  // ── UART setup state ──
  const [uartId, setUartId] = useState(0);
  const [uartTx, setUartTx] = useState(selectedGpio ?? 0);
  const [uartRx, setUartRx] = useState(0);
  const [uartBaud, setUartBaud] = useState(115200);

  // ── UART active state (send/read) ──
  const [uartSendData, setUartSendData] = useState('');
  const [uartReadLen, setUartReadLen] = useState(256);
  const [uartReadResult, setUartReadResult] = useState<string | null>(null);
  // Rebind state
  const [rebindTx, setRebindTx] = useState<number | null>(null);
  const [rebindRx, setRebindRx] = useState<number | null>(null);

  // Reset uart setup when entering uart_setup mode
  useEffect(() => {
    if (panelMode === 'uart_setup' && selectedGpio != null) {
      setUartId(0);
      setUartTx(selectedGpio);
      // Auto-pick a different pin for RX
      const available = getAvailableUartPins(config, uartStates);
      const rx = available.find((g) => g !== selectedGpio);
      setUartRx(rx ?? 0);
      setUartBaud(115200);
    }
  }, [panelMode, selectedGpio]);

  // Reset rebind when entering uart_active
  useEffect(() => {
    if (panelMode === 'uart_active' && uartInfo) {
      const u = uartStates[uartInfo.uart_id];
      setRebindTx(u?.tx_gpio ?? null);
      setRebindRx(u?.rx_gpio ?? null);
    }
  }, [panelMode, uartInfo]);

  if (selectedGpio == null || !pin) return null;

  const now = () => new Date().toLocaleTimeString();
  const caps = pin.capabilities;
  const maxUartCount = config?.capabilities.uart_count ?? 2;
  const availablePins = getAvailableUartPins(config, uartStates);

  // ── GPIO: mode options ──
  const modes = [
    { v: 0, l: 'INPUT', e: caps.input },
    { v: 1, l: 'OUTPUT', e: caps.output },
    { v: 2, l: 'INTERRUPT', e: caps.interrupt },
    { v: 3, l: 'ADC', e: caps.adc },
    { v: 4, l: 'SIGNAL', e: caps.signal },
  ].filter((m) => m.e);

  // ── Handlers: GPIO ──
  const handleApplyGpio = async () => {
    try {
      await api.gpioConfig(pin.gpio, mode, pull, edge);
      addHistory({ time: now(), op: `GPIO${pin.gpio} 配置`, result: '✓' });
      if (mode === 1) {
        await api.gpioSet(pin.gpio, outValue);
        addHistory({ time: now(), op: `GPIO${pin.gpio} SET ${outValue}`, result: '✓' });
      }
    } catch (e: unknown) {
      addHistory({ time: now(), op: `GPIO${pin.gpio} 配置`, result: `✗ ${(e as Error).message}` });
    }
  };

  const handleReadGpio = async () => {
    try {
      const res = await api.gpioGet(pin.gpio);
      addHistory({ time: now(), op: `GPIO${pin.gpio} GET`, result: `→ ${(res as { data: { value: number } }).data.value}` });
    } catch { addHistory({ time: now(), op: `GPIO${pin.gpio} GET`, result: '✗' }); }
  };

  const handleAdcSample = async () => {
    try {
      const res = await api.gpioAdc(pin.gpio, samples);
      const v = (res as { data: { value: number; voltage_mv: number } }).data;
      addHistory({ time: now(), op: `GPIO${pin.gpio} ADC`, result: `→ ${v.value} (${v.voltage_mv}mV)` });
    } catch { addHistory({ time: now(), op: `GPIO${pin.gpio} ADC`, result: '✗' }); }
  };

  // ── Handlers: UART Setup ──
  const handleApplyUartSetup = async () => {
    if (uartTx === uartRx) {
      addHistory({ time: now(), op: 'UART 配置', result: '✗ TX/RX 不能相同' });
      return;
    }
    try {
      await api.uartConfig(uartId, { baudrate: uartBaud, tx_gpio: uartTx, rx_gpio: uartRx });
      // Optimistically update store
      updateUart(uartId, { uart_id: uartId, bound: true, baudrate: uartBaud, tx_gpio: uartTx, rx_gpio: uartRx });
      addHistory({ time: now(), op: `UART${uartId} 配置`, result: `✓ TX=GPIO${uartTx} RX=GPIO${uartRx} @${uartBaud}` });
      setPanelMode('uart_active');
    } catch (e: unknown) {
      addHistory({ time: now(), op: `UART${uartId} 配置`, result: `✗ ${(e as Error).message}` });
    }
  };

  // ── Handlers: UART Active ──
  const activeUartId = uartInfo?.uart_id ?? 0;
  const activeUart = uartStates[activeUartId];

  const handleUartSend = async () => {
    if (!uartSendData.trim()) return;
    try {
      await api.uartSend(activeUartId, uartSendData);
      addHistory({ time: now(), op: `UART${activeUartId} TX`, result: `→ ${uartSendData.slice(0, 40)}` });
    } catch (e: unknown) {
      addHistory({ time: now(), op: `UART${activeUartId} TX`, result: `✗ ${(e as Error).message}` });
    }
  };

  const handleUartRead = async () => {
    try {
      const res = await api.uartRead(activeUartId, uartReadLen);
      const d = (res as { data: { length: number; data_base64?: string } }).data;
      setUartReadResult(`读取 ${d.length} 字节` + (d.data_base64 ? `: ${d.data_base64.slice(0, 60)}` : ''));
      addHistory({ time: now(), op: `UART${activeUartId} RX`, result: `← ${d.length}B` });
    } catch (e: unknown) {
      setUartReadResult(`✗ ${(e as Error).message}`);
      addHistory({ time: now(), op: `UART${activeUartId} RX`, result: `✗` });
    }
  };

  const handleUartRebind = async () => {
    if (rebindTx == null || rebindRx == null || rebindTx === rebindRx) {
      addHistory({ time: now(), op: 'UART 改绑', result: '✗ 无效引脚' });
      return;
    }
    try {
      await api.uartConfig(activeUartId, {
        baudrate: activeUart?.baudrate ?? 115200,
        tx_gpio: rebindTx,
        rx_gpio: rebindRx,
      });
      updateUart(activeUartId, { tx_gpio: rebindTx, rx_gpio: rebindRx });
      addHistory({ time: now(), op: `UART${activeUartId} 改绑`, result: `✓ TX→GPIO${rebindTx} RX→GPIO${rebindRx}` });
    } catch (e: unknown) {
      addHistory({ time: now(), op: `UART${activeUartId} 改绑`, result: `✗ ${(e as Error).message}` });
    }
  };

  // ── Pin label helpers ──
  const pinLabel = (gpio: number) => {
    const p = config?.pins.find((x) => x.gpio === gpio);
    return p ? `${p.label}` : `GPIO${gpio}`;
  };

  // ── Render ──
  const containerClass = embedded
    ? 'flex-1 overflow-y-auto p-4'
    : 'fixed right-0 top-0 h-full w-80 bg-gray-900 border-l border-gray-700 p-4 overflow-y-auto z-50 shadow-xl';

  return (
    <div className={containerClass}>
      {/* Header */}
      <div className="flex justify-between items-center mb-4">
        <h2 className="text-sm font-bold text-gray-300">
          {pin.label} 配置
          {uartInfo && (
            <span className={`ml-2 text-xs px-1.5 py-0.5 rounded ${
              uartInfo.role === 'tx' ? 'bg-blue-900 text-blue-300' : 'bg-orange-900 text-orange-300'
            }`}>
              UART{uartInfo.uart_id} {uartInfo.role.toUpperCase()}
            </span>
          )}
        </h2>
        <button onClick={() => selectGpio(null)} className="text-gray-500 hover:text-gray-300 text-lg">&times;</button>
      </div>

      {/* ── Reserved pin ── */}
      {pin.reserved && (
        <div className="bg-red-900/50 text-red-300 p-2 rounded mb-3 text-sm">
          🔒 保留引脚: {pin.reserved_reason || '不可配置'}
        </div>
      )}

      {/* ════════════════════════════════════════════
          UART ACTIVE: pin is bound to a UART
          ════════════════════════════════════════════ */}
      {panelMode === 'uart_active' && activeUart && !pin.reserved && (
        <div className="space-y-4">
          {/* Current config */}
          <div className="bg-gray-800 rounded p-3 text-xs space-y-1">
            <div className="flex justify-between">
              <span className="text-gray-500">UART ID</span>
              <span className="text-gray-200">{activeUartId}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-gray-500">波特率</span>
              <span className="text-gray-200">{activeUart.baudrate}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-gray-500">TX</span>
              <button
                onClick={() => { selectGpio(activeUart.tx_gpio); }}
                className="text-blue-400 hover:underline"
              >
                {pinLabel(activeUart.tx_gpio)}
              </button>
            </div>
            <div className="flex justify-between">
              <span className="text-gray-500">RX</span>
              <button
                onClick={() => { selectGpio(activeUart.rx_gpio); }}
                className="text-orange-400 hover:underline"
              >
                {pinLabel(activeUart.rx_gpio)}
              </button>
            </div>
          </div>

          {/* Send data */}
          <div>
            <label className="text-xs text-gray-500 block mb-1">发送数据</label>
            <div className="flex gap-1">
              <input
                value={uartSendData}
                onChange={(e) => setUartSendData(e.target.value)}
                placeholder="hello"
                className="flex-1 bg-gray-800 border border-gray-600 rounded px-2 py-1 text-xs text-gray-200"
              />
              <button onClick={handleUartSend}
                className="px-3 py-1 bg-blue-600 hover:bg-blue-500 rounded text-xs">
                发送
              </button>
            </div>
          </div>

          {/* Read data */}
          <div>
            <label className="text-xs text-gray-500 block mb-1">读取数据</label>
            <div className="flex gap-1">
              <select value={uartReadLen} onChange={(e) => setUartReadLen(Number(e.target.value))}
                className="bg-gray-800 border border-gray-600 rounded px-2 py-1 text-xs text-gray-200">
                {[64, 128, 256, 512, 1024].map((n) => <option key={n} value={n}>{n}B</option>)}
              </select>
              <button onClick={handleUartRead}
                className="px-3 py-1 bg-purple-700 hover:bg-purple-600 rounded text-xs">
                读取
              </button>
            </div>
            {uartReadResult && (
              <div className="mt-1 text-xs text-gray-400 font-mono bg-gray-800 p-1.5 rounded">{uartReadResult}</div>
            )}
          </div>

          {/* Rebind pins — collapsible */}
          <details className="text-xs">
            <summary className="text-gray-500 cursor-pointer hover:text-gray-300">改绑 IO 引脚</summary>
            <div className="mt-2 space-y-2 bg-gray-800/50 p-2 rounded">
              <div>
                <label className="text-gray-500 block mb-0.5">TX 引脚</label>
                <select
                  value={rebindTx ?? activeUart.tx_gpio}
                  onChange={(e) => setRebindTx(Number(e.target.value))}
                  className="w-full bg-gray-700 border border-gray-600 rounded px-2 py-1 text-xs"
                >
                  {availablePins.concat(activeUart.tx_gpio).filter((g, i, a) => a.indexOf(g) === i).map((g) => (
                    <option key={g} value={g}>{pinLabel(g)}</option>
                  ))}
                </select>
              </div>
              <div>
                <label className="text-gray-500 block mb-0.5">RX 引脚</label>
                <select
                  value={rebindRx ?? activeUart.rx_gpio}
                  onChange={(e) => setRebindRx(Number(e.target.value))}
                  className="w-full bg-gray-700 border border-gray-600 rounded px-2 py-1 text-xs"
                >
                  {availablePins.concat(activeUart.rx_gpio).filter((g, i, a) => a.indexOf(g) === i).map((g) => (
                    <option key={g} value={g}>{pinLabel(g)}</option>
                  ))}
                </select>
              </div>
              <button onClick={handleUartRebind}
                className="w-full py-1 bg-yellow-700 hover:bg-yellow-600 rounded text-xs">
                应用改绑
              </button>
            </div>
          </details>

          {/* Unbind UART */}
          <button
            onClick={async () => {
              if (!confirm('确认解绑 UART 引脚绑定？GPIO 模式保留但 UART 配置将被清除。')) return;
              try {
                // Unbind by re-configuring with empty/invalid pins triggers unbind on backend
                // Alternatively just remove from local store
                const { [activeUartId]: _, ...rest } = uartStates;
                useDeviceStore.setState({ uartStates: rest });
                addHistory({ time: now(), op: `UART${activeUartId} 解绑`, result: '✓' });
                setPanelMode('gpio');
              } catch (e: unknown) {
                addHistory({ time: now(), op: `UART${activeUartId} 解绑`, result: `✗` });
              }
            }}
            className="w-full py-1.5 bg-red-900/60 hover:bg-red-800/60 rounded text-xs text-red-300 border border-red-800"
          >
            🔓 解绑 UART
          </button>

          {/* Switch back to GPIO mode */}
          <button
            onClick={() => setPanelMode('gpio')}
            className="w-full py-1.5 bg-gray-700 hover:bg-gray-600 rounded text-xs text-gray-300"
          >
            ← 查看 GPIO 模式
          </button>
        </div>
      )}

      {/* ════════════════════════════════════════════
          UART SETUP: configuring a new UART
          ════════════════════════════════════════════ */}
      {panelMode === 'uart_setup' && !pin.reserved && (
        <div className="space-y-4">
          <div className="bg-blue-900/30 text-blue-300 p-2 rounded text-xs">
            📡 为此 IO 配置 UART — 请选择 TX/RX 引脚
          </div>

          <div>
            <label className="text-xs text-gray-500 block mb-1">UART 编号</label>
            <select value={uartId} onChange={(e) => setUartId(Number(e.target.value))}
              className="w-full bg-gray-800 border border-gray-600 rounded px-2 py-1 text-sm text-gray-200">
              {Array.from({ length: maxUartCount }, (_, i) => (
                <option key={i} value={i}>UART{i}</option>
              ))}
            </select>
          </div>

          <div>
            <label className="text-xs text-gray-500 block mb-1">TX 引脚 (发送)</label>
            <select value={uartTx} onChange={(e) => setUartTx(Number(e.target.value))}
              className="w-full bg-gray-800 border border-gray-600 rounded px-2 py-1 text-sm text-gray-200">
              {availablePins.concat(selectedGpio).filter((g, i, a) => a.indexOf(g) === i).map((g) => (
                <option key={g} value={g}>{pinLabel(g)}{g === selectedGpio ? ' (当前)' : ''}</option>
              ))}
            </select>
          </div>

          <div>
            <label className="text-xs text-gray-500 block mb-1">RX 引脚 (接收)</label>
            <select value={uartRx} onChange={(e) => setUartRx(Number(e.target.value))}
              className="w-full bg-gray-800 border border-gray-600 rounded px-2 py-1 text-sm text-gray-200">
              {availablePins.concat(selectedGpio).filter((g, i, a) => a.indexOf(g) === i).map((g) => (
                <option key={g} value={g}>{pinLabel(g)}</option>
              ))}
            </select>
            {uartTx === uartRx && (
              <div className="text-red-400 text-xs mt-1">⚠ TX 和 RX 不能使用同一引脚</div>
            )}
          </div>

          <div>
            <label className="text-xs text-gray-500 block mb-1">波特率</label>
            <select value={uartBaud} onChange={(e) => setUartBaud(Number(e.target.value))}
              className="w-full bg-gray-800 border border-gray-600 rounded px-2 py-1 text-sm text-gray-200">
              {[9600, 19200, 38400, 57600, 115200, 230400, 460800, 921600].map((b) => (
                <option key={b} value={b}>{b}</option>
              ))}
            </select>
          </div>

          <div className="flex gap-2">
            <button onClick={handleApplyUartSetup}
              className="flex-1 py-2 bg-blue-600 hover:bg-blue-500 rounded text-sm font-medium">
              应用 UART 配置
            </button>
            <button onClick={() => setPanelMode('gpio')}
              className="px-4 py-2 bg-gray-700 hover:bg-gray-600 rounded text-sm">
              取消
            </button>
          </div>
        </div>
      )}

      {/* ════════════════════════════════════════════
          GPIO MODE: normal pin configuration
          ════════════════════════════════════════════ */}
      {panelMode === 'gpio' && !pin.reserved && (
        <div className="space-y-4">
          {/* Current status */}
          <div className="text-xs text-gray-400">
            当前: {pinState?.mode ?? pin.default_mode?.toUpperCase()}
            {pinState?.value != null && ` · ${pinState.value === 1 ? '高电平' : '低电平'}`}
            {pinState?.adc_voltage_mv != null && ` · ${pinState.adc_voltage_mv}mV`}
          </div>

          {/* Mode selection */}
          <div>
            <label className="text-xs text-gray-500 block mb-1.5">模式</label>
            <div className="flex flex-wrap gap-1.5">
              {modes.map((m) => (
                <button
                  key={m.v}
                  onClick={() => setMode(m.v)}
                  className={`px-3 py-1.5 text-xs rounded ${mode === m.v ? 'bg-blue-600 text-white' : 'bg-gray-700 text-gray-300 hover:bg-gray-600'}`}
                >
                  {m.l}
                </button>
              ))}
            </div>
          </div>

          {/* Pull */}
          <div>
            <label className="text-xs text-gray-500 block mb-1.5">上下拉</label>
            <div className="flex gap-1.5">
              {[{ v: 0, l: '无' }, { v: 1, l: '下拉' }, { v: 2, l: '上拉' }].map((p) => (
                <button key={p.v} onClick={() => setPull(p.v)}
                  className={`px-3 py-1.5 text-xs rounded ${pull === p.v ? 'bg-blue-600 text-white' : 'bg-gray-700 text-gray-300 hover:bg-gray-600'}`}>
                  {p.l}
                </button>
              ))}
            </div>
          </div>

          {/* Interrupt edge */}
          {mode === 2 && (
            <div>
              <label className="text-xs text-gray-500 block mb-1.5">触发边沿</label>
              <div className="flex gap-1.5">
                {[{ v: 0, l: '无' }, { v: 1, l: '上升 ↑' }, { v: 2, l: '下降 ↓' }, { v: 3, l: '双沿 ⇅' }].map((e) => (
                  <button key={e.v} onClick={() => setEdge(e.v)}
                    className={`px-3 py-1.5 text-xs rounded ${edge === e.v ? 'bg-yellow-600 text-white' : 'bg-gray-700 text-gray-300 hover:bg-gray-600'}`}>
                    {e.l}
                  </button>
                ))}
              </div>
            </div>
          )}

          {/* Output level */}
          {mode === 1 && (
            <div>
              <label className="text-xs text-gray-500 block mb-1.5">输出电平</label>
              <div className="flex gap-1.5">
                {[{ v: 0, l: '低 (0) ○' }, { v: 1, l: '高 (1) ●' }].map((o) => (
                  <button key={o.v} onClick={() => setOutValue(o.v)}
                    className={`px-3 py-1.5 text-xs rounded ${outValue === o.v ? 'bg-green-600 text-white' : 'bg-gray-700 text-gray-300 hover:bg-gray-600'}`}>
                    {o.l}
                  </button>
                ))}
              </div>
            </div>
          )}

          {/* ADC samples */}
          {mode === 3 && (
            <div>
              <label className="text-xs text-gray-500 block mb-1.5">采样次数</label>
              <select value={samples} onChange={(e) => setSamples(Number(e.target.value))}
                className="bg-gray-800 border border-gray-600 rounded px-2 py-1.5 text-sm text-gray-200 w-full">
                {[1, 2, 4, 8, 16].map((n) => <option key={n} value={n}>{n} 次</option>)}
              </select>
            </div>
          )}

          {/* Quick actions */}
          <div className="flex gap-2">
            <button onClick={handleReadGpio}
              className="flex-1 py-2 bg-gray-700 hover:bg-gray-600 rounded text-xs">
              📥 读取电平
            </button>
            {caps.adc && (
              <button onClick={handleAdcSample}
                className="flex-1 py-2 bg-purple-700 hover:bg-purple-600 rounded text-xs">
                📊 ADC 采样
              </button>
            )}
          </div>

          {/* Apply GPIO config */}
          <button onClick={handleApplyGpio}
            className="w-full py-2 bg-blue-600 hover:bg-blue-500 rounded text-sm font-medium">
            应用 GPIO 配置
          </button>

          {/* Divider + UART setup/return trigger */}
          {config?.capabilities.uart && (
            <>
              <div className="border-t border-gray-700 pt-3">
                {uartInfo ? (
                  <button
                    onClick={() => setPanelMode('uart_active')}
                    className="w-full py-2 bg-teal-900/50 hover:bg-teal-800/50 rounded text-sm text-teal-300 border border-teal-800"
                  >
                    📡 返回 UART 配置
                  </button>
                ) : (
                  <button
                    onClick={() => setPanelMode('uart_setup')}
                    className="w-full py-2 bg-teal-800 hover:bg-teal-700 rounded text-sm text-teal-200 border border-teal-700"
                  >
                    📡 配置为 UART 引脚
                  </button>
                )}
                <div className="text-[10px] text-gray-600 mt-1 text-center">
                  {uartInfo ? '管理 UART 通信、发送/接收数据' : '将此 IO 与另一 IO 组合为 UART 通信接口'}
                </div>
              </div>
            </>
          )}
        </div>
      )}
    </div>
  );
}
