import { useState, useEffect, useMemo, useCallback } from 'react';
import { useDeviceStore, getUartForGpio, getAvailableUartPins } from '../../stores/deviceStore';
import { api } from '../../services/api';
import type { PinConfig } from '../../types';

function getModeLabel(modeCode: number | null | undefined) {
  const modes = ['INPUT', 'OUTPUT', 'INTERRUPT', 'ADC', 'SIGNAL', 'INPUT_OUTPUT'] as const;
  if (modeCode == null || modeCode < 0 || modeCode >= modes.length) return 'UNCONFIGURED';
  return modes[modeCode];
}

// ── Types ──────────────────────────────────────────

type PanelMode = 'gpio' | 'uart_setup' | 'uart_active';
type PickingStage = 'idle' | 'picking_tx' | 'picking_rx';

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
  const setUartPinPicker = useDeviceStore((s) => s.setUartPinPicker);
  const lockedPins = useDeviceStore((s) => s.lockedPins);
  const toggleLock = useDeviceStore((s) => s.toggleLock);
  const [isEditingGpioForm, setIsEditingGpioForm] = useState(false);

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
    if (pin && panelMode === 'gpio' && !isEditingGpioForm) {
      setMode(pinState?.mode_code ?? 0);
      setPull(pinState?.pull_code ?? 0);
      setEdge(pinState?.edge ?? 0);
      setOutValue(pinState?.value ?? 0);
    }
  }, [selectedGpio, pinState, panelMode, isEditingGpioForm]);

  useEffect(() => {
    setGpioReadResult(null);
    setAdcReadResult(null);
    setIsEditingGpioForm(false);
  }, [selectedGpio]);

  // ── UART setup state ──
  const [uartId, setUartId] = useState(0);
  const [uartTx, setUartTx] = useState(selectedGpio ?? 0);
  const [uartRx, setUartRx] = useState(0);
  const [uartBaud, setUartBaud] = useState(115200);

  // ── GPIO status display ──
  const [gpioReadResult, setGpioReadResult] = useState<string | null>(null);
  const [adcReadResult, setAdcReadResult] = useState<string | null>(null);

  const syncPinStateFromStatus = useCallback(async (gpio: number) => {
    const res = await api.portStatus(0, gpio) as { data: { in_use: number; mode?: number; pull?: number; edge?: number; value?: number } };
    const d = res.data;
    const pulls = ['NONE', 'DOWN', 'UP'] as const;
    const next: Record<string, unknown> = {
      bound: d.in_use === 1,
    };
    if (d.value != null) next.value = d.value;
    if (d.mode != null) {
      next.mode = getModeLabel(d.mode);
      next.mode_code = d.mode;
    }
    if (d.pull != null) {
      next.pull = pulls[d.pull] ?? 'NONE';
      next.pull_code = d.pull;
    }
    if (d.edge != null) next.edge = d.edge;
    useDeviceStore.getState().updatePin(gpio, next as never);
    return d;
  }, []);

  // ── UART active state (send/read) ──
  const [uartSendData, setUartSendData] = useState('');
  const [uartHexMode, setUartHexMode] = useState(false);
  const [uartReadLen, setUartReadLen] = useState(256);
  const [uartReadResult, setUartReadResult] = useState<string | null>(null);

  // UART pin picker stage
  const [pickingStage, setPickingStage] = useState<PickingStage>('idle');

  // Cleanup picker on unmount/mode change
  useEffect(() => { return () => { setUartPinPicker(null); }; }, []);
  useEffect(() => {
    if (panelMode !== 'uart_setup') { setUartPinPicker(null); setPickingStage('idle'); }
  }, [panelMode]);

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

  // Pin picker callbacks — independent TX / RX
  const startPickTx = useCallback(() => {
    setPickingStage('picking_tx');
    setUartPinPicker({
      uart_id: uartId, role: 'tx',
      onPick: (gpio) => {
        setUartTx(gpio);
        setPickingStage('idle');
        setUartPinPicker(null);
      },
    });
  }, [uartId]);

  const startPickRx = useCallback(() => {
    setPickingStage('picking_rx');
    setUartPinPicker({
      uart_id: uartId, role: 'rx',
      onPick: (gpio) => {
        setUartRx(gpio);
        setPickingStage('idle');
        setUartPinPicker(null);
      },
    });
  }, [uartId]);

  const cancelPick = useCallback(() => {
    setPickingStage('idle');
    setUartPinPicker(null);
  }, []);

  if (selectedGpio == null || !pin) return null;

  const now = () => new Date().toLocaleTimeString();
  const caps = pin.capabilities;
  const actualModeCode = pinState?.mode_code ?? -1;
  const actualMode = pinState?.mode ?? 'UNCONFIGURED';
  const actualOutputReadUnavailable = actualModeCode === 1 || actualMode === 'OUTPUT';
  const maxUartCount = config?.capabilities.uart_count ?? 2;
  const availablePins = getAvailableUartPins(config, uartStates);
  const usedUartIds = new Set(
    Object.entries(uartStates).filter(([, u]) => u.bound).map(([k]) => Number(k))
  );

  // ── GPIO: mode options ──
  const modes = [
    { v: 0, l: 'INPUT', e: caps.input },
    { v: 1, l: 'OUTPUT', e: caps.output },
    { v: 2, l: 'INTERRUPT', e: caps.interrupt },
    { v: 3, l: 'ADC', e: caps.adc },
    { v: 4, l: 'SIGNAL', e: caps.signal },
    { v: 5, l: 'INPUT_OUTPUT', e: caps.input && caps.output },
  ].filter((m) => m.e);

  // ── Handlers: GPIO ──
  const handleApplyGpio = async () => {
    try {
      await api.gpioConfig(pin.gpio, mode, pull, edge);
      if (mode === 1) {
        await api.gpioSet(pin.gpio, outValue);
      }
      try {
        await syncPinStateFromStatus(pin.gpio);
      } catch { /* best-effort */ }
      setIsEditingGpioForm(false);
      addHistory({ time: now(), op: `GPIO${pin.gpio} 配置`, result: '✓' });
      selectGpio(null);
    } catch (e: unknown) {
      addHistory({ time: now(), op: `GPIO${pin.gpio} 配置`, result: `✗ ${(e as Error).message}` });
    }
  };

  // ── Handlers: UART Setup ──
  const handleApplyUartSetup = async () => {
    if (uartTx === uartRx) {
      addHistory({ time: now(), op: 'UART 配置', result: '✗ TX/RX 不能相同' });
      return;
    }
    try {
      await api.uartConfig(uartId, { baudrate: uartBaud, tx_gpio: uartTx, rx_gpio: uartRx });
      updateUart(uartId, { uart_id: uartId, bound: true, baudrate: uartBaud, tx_gpio: uartTx, rx_gpio: uartRx });
      // Auto-lock TX and RX pins
      if (!lockedPins.has(uartTx)) toggleLock(uartTx);
      if (!lockedPins.has(uartRx)) toggleLock(uartRx);
      addHistory({ time: now(), op: `UART${uartId} 配置`, result: `✓ TX=GPIO${uartTx} RX=GPIO${uartRx} @${uartBaud}` });
      setPickingStage('idle');
      setUartPinPicker(null);
      setPanelMode('uart_active');
      selectGpio(null); // auto-close on success
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
      if (uartHexMode) {
        const hex = uartSendData.trim();
        if (!/^[0-9a-fA-F\s]+$/.test(hex)) {
          addHistory({ time: now(), op: `UART${activeUartId} TX`, result: '✗ 无效的16进制数据' });
          return;
        }
        await api.uartSendHex(activeUartId, hex);
        addHistory({ time: now(), op: `UART${activeUartId} TX`, result: `→ [HEX] ${hex.slice(0, 40)}` });
      } else {
        await api.uartSend(activeUartId, uartSendData);
        addHistory({ time: now(), op: `UART${activeUartId} TX`, result: `→ ${uartSendData.slice(0, 40)}` });
      }
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

  const handleUartRebindTxRx = async (tx: number, rx: number) => {
    if (tx === rx) {
      addHistory({ time: now(), op: 'UART 改绑', result: '✗ TX/RX 不能相同' });
      return;
    }
    try {
      await api.uartConfig(activeUartId, {
        baudrate: activeUart?.baudrate ?? 115200,
        tx_gpio: tx, rx_gpio: rx,
      });
      updateUart(activeUartId, { tx_gpio: tx, rx_gpio: rx });
      if (!lockedPins.has(tx)) toggleLock(tx);
      if (!lockedPins.has(rx)) toggleLock(rx);
      addHistory({ time: now(), op: `UART${activeUartId} 改绑`, result: `✓ TX→GPIO${tx} RX→GPIO${rx}` });
      selectGpio(null); // auto-close on success
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
              <button
                onClick={() => setUartHexMode(!uartHexMode)}
                className={`text-[10px] px-1.5 py-1 rounded ${
                  uartHexMode ? 'bg-blue-700 text-blue-200' : 'bg-emerald-700 text-emerald-200'
                }`}
                title={uartHexMode ? '当前: 16进制输入' : '当前: 文本输入'}
              >
                {uartHexMode ? 'HEX' : 'TXT'}
              </button>
              <input
                value={uartSendData}
                onChange={(e) => setUartSendData(e.target.value)}
                placeholder={uartHexMode ? 'FE EE' : 'hello'}
                className="flex-1 bg-gray-800 border border-gray-600 rounded px-2 py-1 text-xs text-gray-200 font-mono"
                spellCheck={false}
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

          {/* Rebind pins — click to pick */}
          <details className="text-xs">
            <summary className="text-gray-500 cursor-pointer hover:text-gray-300">改绑 IO 引脚</summary>
            <div className="mt-2 space-y-2 bg-gray-800/50 p-2 rounded">
              <div>
                <label className="text-gray-500 block mb-0.5">TX 引脚</label>
                <button
                  onClick={() => setUartPinPicker({
                    uart_id: activeUartId, role: 'tx',
                    onPick: (gpio) => { handleUartRebindTxRx(gpio, activeUart.rx_gpio); setUartPinPicker(null); },
                  })}
                  className="w-full text-left bg-gray-700 border border-gray-600 rounded px-2 py-1 text-xs hover:bg-gray-600"
                >
                  {pinLabel(activeUart.tx_gpio)} (点击更换)
                </button>
              </div>
              <div>
                <label className="text-gray-500 block mb-0.5">RX 引脚</label>
                <button
                  onClick={() => setUartPinPicker({
                    uart_id: activeUartId, role: 'rx',
                    onPick: (gpio) => { handleUartRebindTxRx(activeUart.tx_gpio, gpio); setUartPinPicker(null); },
                  })}
                  className="w-full text-left bg-gray-700 border border-gray-600 rounded px-2 py-1 text-xs hover:bg-gray-600"
                >
                  {pinLabel(activeUart.rx_gpio)} (点击更换)
                </button>
              </div>
            </div>
          </details>

          {/* Unbind UART */}
          <button
            onClick={async () => {
              if (!confirm('确认解绑 UART 引脚绑定？')) return;
              try {
                await api.portUnbind(1, activeUartId);
                const { [activeUartId]: _, ...rest } = uartStates;
                useDeviceStore.setState({ uartStates: rest });
                if (activeUart.tx_gpio != null && lockedPins.has(activeUart.tx_gpio)) toggleLock(activeUart.tx_gpio);
                if (activeUart.rx_gpio != null && lockedPins.has(activeUart.rx_gpio)) toggleLock(activeUart.rx_gpio);
                addHistory({ time: now(), op: `UART${activeUartId} 解绑`, result: '✓' });
                setPanelMode('gpio');
              } catch (e: unknown) {
                addHistory({ time: now(), op: `UART${activeUartId} 解绑`, result: `✗ ${(e as Error).message}` });
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
          UART SETUP: click pins on chip to pick TX/RX
          ════════════════════════════════════════════ */}
      {panelMode === 'uart_setup' && !pin.reserved && (
        <div className="space-y-4">
          <div className="bg-blue-900/30 text-blue-300 p-2 rounded text-xs">
            {pickingStage === 'idle'
              ? '📡 点击下方「选择」按钮，然后在芯片上点击引脚来分别选择 TX/RX'
              : pickingStage === 'picking_tx'
                ? '👆 请在芯片上点击 TX (发送) 引脚'
                : '👆 请在芯片上点击 RX (接收) 引脚'}
          </div>

          <div>
            <label className="text-xs text-gray-500 block mb-1">UART 编号</label>
            <div className="flex flex-wrap gap-1.5">
              {Array.from({ length: maxUartCount }, (_, i) => (
                <button
                  key={i}
                  onClick={() => setUartId(i)}
                  disabled={usedUartIds.has(i)}
                  className={`px-3 py-1.5 text-xs rounded ${
                    usedUartIds.has(i)
                      ? 'bg-gray-800 text-gray-600 cursor-not-allowed line-through'
                      : uartId === i
                        ? 'bg-blue-600 text-white'
                        : 'bg-gray-700 text-gray-300 hover:bg-gray-600'
                  }`}
                >
                  UART{i}{usedUartIds.has(i) ? ' (占用)' : ''}
                </button>
              ))}
            </div>
          </div>

          <div>
            <label className="text-xs text-gray-500 block mb-1">TX 引脚 (发送)</label>
            <button onClick={startPickTx}
              className={`w-full text-left px-3 py-1.5 rounded text-xs font-mono border transition-colors ${
                pickingStage === 'picking_tx'
                  ? 'bg-yellow-900/50 text-yellow-300 border-yellow-600 animate-pulse cursor-pointer'
                  : 'bg-gray-800 text-gray-200 border-gray-600 hover:border-blue-500 cursor-pointer'
              }`}>
              {pinLabel(uartTx)}{uartTx === selectedGpio ? ' (当前)' : ''}
            </button>
          </div>

          <div>
            <label className="text-xs text-gray-500 block mb-1">RX 引脚 (接收)</label>
            <button onClick={startPickRx}
              className={`w-full text-left px-3 py-1.5 rounded text-xs font-mono border transition-colors ${
                pickingStage === 'picking_rx'
                  ? 'bg-yellow-900/50 text-yellow-300 border-yellow-600 animate-pulse cursor-pointer'
                  : 'bg-gray-800 text-gray-200 border-gray-600 hover:border-orange-500 cursor-pointer'
              }`}>
              {pinLabel(uartRx)}
              {uartTx === uartRx && ' ⚠️'}
            </button>
            {pickingStage !== 'idle' && (
              <button onClick={cancelPick} className="mt-2 px-3 py-1 bg-gray-600 hover:bg-gray-500 rounded text-xs w-full">
                ✕ 取消选择
              </button>
            )}
            {uartTx === uartRx && (
              <div className="text-red-400 text-xs mt-1">⚠ TX 和 RX 不能使用同一引脚</div>
            )}
          </div>

          <div>
            <label className="text-xs text-gray-500 block mb-1">波特率</label>
            <select value={uartBaud} onChange={(e) => setUartBaud(Number(e.target.value))}
              className="w-full bg-gray-800 border border-gray-600 rounded px-2 py-1.5 text-sm text-gray-200">
              {[9600, 19200, 38400, 57600, 115200, 230400, 460800, 921600].map((b) => (
                <option key={b} value={b}>{b}</option>
              ))}
            </select>
          </div>

          <div className="flex gap-2">
            <button onClick={handleApplyUartSetup}
              disabled={uartTx === uartRx}
              className="flex-1 py-2 bg-blue-600 hover:bg-blue-500 disabled:opacity-40 rounded text-sm font-medium">
              应用 UART 配置
            </button>
            <button onClick={() => { setPanelMode('gpio'); setUartPinPicker(null); }}
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
          {/* GPIO Status */}
          <div className="bg-gray-800/60 rounded p-2.5 space-y-1.5 text-xs">
            <div className="flex items-center justify-between">
              <span className="text-gray-500 text-[11px]">状态</span>
              <button
                onClick={async () => {
                  try {
                    const res = await api.gpioGet(pin.gpio);
                    const v = (res as { data: { value: number } }).data.value;
                    useDeviceStore.getState().updatePin(pin.gpio, { value: v } as never);
                    const currentModeCode = useDeviceStore.getState().pinStates[pin.gpio]?.mode_code ?? -1;
                    if (currentModeCode === 1) {
                      setGpioReadResult('not available');
                      setAdcReadResult('not available');
                    } else {
                      setGpioReadResult(v === 1 ? 'HIGH' : 'LOW');
                    }
                    if (caps.adc && currentModeCode === 3) {
                      const ares = await api.gpioAdc(pin.gpio, samples);
                      const av = (ares as { data: { value: number; voltage_mv: number } }).data;
                      useDeviceStore.getState().updatePin(pin.gpio, {
                        adc_value: av.value,
                        adc_voltage_mv: av.voltage_mv,
                      } as never);
                      setAdcReadResult(`${av.value} / ${av.voltage_mv}mV`);
                    } else if (currentModeCode !== 3) {
                      setAdcReadResult(currentModeCode === 1 ? 'not available' : '--');
                    }
                    try {
                      await syncPinStateFromStatus(pin.gpio);
                    } catch { /* best-effort */ }
                  } catch { /* ignore */ }
                }}
                className="text-[10px] text-gray-500 hover:text-gray-300 px-1.5 py-0.5 rounded hover:bg-gray-700"
              >🔄 刷新</button>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-gray-500">电平</span>
              <span className={`font-mono font-bold ${gpioReadResult === 'HIGH' ? 'text-green-400' : gpioReadResult === 'LOW' ? 'text-red-400' : pinState?.value === 1 ? 'text-green-400' : pinState?.value === 0 ? 'text-red-400' : 'text-gray-600'}`}>
                {actualOutputReadUnavailable
                  ? 'not available'
                  : gpioReadResult ?? (pinState?.value === 1 ? 'HIGH' : pinState?.value === 0 ? 'LOW' : '--')}
              </span>
            </div>
            {caps.adc && (
              <div className="flex items-center justify-between">
                <span className="text-gray-500">ADC</span>
                <span className="font-mono text-purple-300">
                  {actualOutputReadUnavailable
                    ? 'not available'
                    : adcReadResult ?? (pinState?.adc_value != null ? `${pinState.adc_value} / ${pinState.adc_voltage_mv}mV` : '--')}
                </span>
              </div>
            )}
          </div>

          {/* Mode selection */}
          <div>
            <label className="text-xs text-gray-500 block mb-1.5">模式</label>
            <div className="flex flex-wrap gap-1.5">
              {modes.map((m) => (
                <button
                  key={m.v}
                  onClick={() => { setIsEditingGpioForm(true); setMode(m.v); }}
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
                <button key={p.v} onClick={() => { setIsEditingGpioForm(true); setPull(p.v); }}
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
                  <button key={e.v} onClick={() => { setIsEditingGpioForm(true); setEdge(e.v); }}
                    className={`px-3 py-1.5 text-xs rounded ${edge === e.v ? 'bg-yellow-600 text-white' : 'bg-gray-700 text-gray-300 hover:bg-gray-600'}`}>
                    {e.l}
                  </button>
                ))}
              </div>
            </div>
          )}

          {/* Output level */}
          {(mode === 1 || mode === 5) && (
            <div>
              <label className="text-xs text-gray-500 block mb-1.5">输出电平</label>
              <div className="flex gap-1.5">
                {[{ v: 0, l: '低 (0) ○' }, { v: 1, l: '高 (1) ●' }].map((o) => (
                  <button key={o.v} onClick={() => { setIsEditingGpioForm(true); setOutValue(o.v); }}
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

          {/* Lock toggle — disabled for UART-bound pins */}
          {uartInfo ? (
            <button disabled
              className="w-full py-1.5 rounded text-xs border bg-amber-900/40 text-amber-300/70 border-amber-700/50 cursor-not-allowed"
            >
              🔒 UART 占用中，由 UART 管理锁定
            </button>
          ) : (
            <button
              onClick={() => toggleLock(pin.gpio)}
              className={`w-full py-1.5 rounded text-xs border ${
                lockedPins.has(pin.gpio)
                  ? 'bg-amber-900/40 text-amber-300 border-amber-700 hover:bg-amber-800/40'
                  : 'bg-gray-800 text-gray-500 border-gray-700 hover:text-gray-300 hover:border-gray-600'
              }`}
            >
              {lockedPins.has(pin.gpio) ? '🔒 已锁定 — 防自动覆盖 (点击解锁)' : '🔓 锁定引脚配置'}
            </button>
          )}

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
