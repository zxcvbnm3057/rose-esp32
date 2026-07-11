import { useMemo, useState, useCallback } from 'react';
import { useDeviceStore, getUartForGpio } from '../../stores/deviceStore';
import { groupPins, rotateLayout, isFixedPin } from './chipLayout';
import { PinPad } from './PinPad';
import type { PinConfig } from '../../types';

const COOKIE_KEY = 'chip-rotation';
function getCookieRotation(): number {
  const match = document.cookie.match(new RegExp(`(?:^|; )${COOKIE_KEY}=([^;]*)`));
  return match ? (parseInt(match[1]) || 0) : 0;
}
function setCookieRotation(deg: number) {
  document.cookie = `${COOKIE_KEY}=${deg};path=/;max-age=31536000;SameSite=Lax`;
}

export function ChipView() {
  const config = useDeviceStore((s) => s.hardwareConfig);
  const pinStates = useDeviceStore((s) => s.pinStates);
  const uartStates = useDeviceStore((s) => s.uartStates);
  const selectGpio = useDeviceStore((s) => s.selectGpio);
  const selectedGpio = useDeviceStore((s) => s.selectedGpio);
  const uartPinPicker = useDeviceStore((s) => s.uartPinPicker);
  const lockedPins = useDeviceStore((s) => s.lockedPins ?? new Set<number>());
  const mismatchPins = useDeviceStore((s) => s.mismatchPins ?? new Set<number>());

  const [rotation, setRotation] = useState(() => getCookieRotation());

  const { top, bottom, left, right } = useMemo(() => {
    if (!config) return { top: [] as PinConfig[], bottom: [] as PinConfig[], left: [] as PinConfig[], right: [] as PinConfig[] };
    const original = groupPins(config.pins);
    return rotateLayout(original, rotation);
  }, [config, rotation]);

  const handleRotate = useCallback(() => {
    setRotation((r) => {
      const next = (r + 90) % 360;
      setCookieRotation(next);
      return next;
    });
  }, []);

  if (!config) {
    return <div className="flex items-center justify-center h-96 text-gray-500">加载硬件配置中…</div>;
  }

  const makeProps = (pin: typeof config.pins[number]) => {
    const fixed = isFixedPin(pin);
    const uartInfo = !fixed ? getUartForGpio(uartStates, pin.gpio) : null;
    return {
      config: pin,
      state: fixed ? undefined : pinStates[pin.gpio],
      uartRole: uartInfo?.role ?? null,
      selected: selectedGpio === pin.gpio,
      isPicking: uartPinPicker != null,
      locked: lockedPins.has(pin.gpio),
      mismatch: mismatchPins.has(pin.gpio),
      fixed,
      onClick: () => {
        if (fixed) return;
        if (uartPinPicker) {
          if (!lockedPins.has(pin.gpio)) uartPinPicker.onPick(pin.gpio);
        } else {
          selectGpio(pin.gpio);
        }
      },
      onContextMenu: () => { if (!fixed) selectGpio(pin.gpio); },
    };
  };

  const hasH = top.length > 0 || bottom.length > 0;
  const maxSide = Math.max(left.length, right.length);
  const maxHorizontal = Math.max(top.length, bottom.length);
  const chipMinH = Math.max(80, maxSide * 40 + 16);
  const chipMinW = Math.max(160, maxHorizontal * 60 + 16);

  return (
    <div className="flex flex-col items-center overflow-auto p-4">
      <button
        onClick={handleRotate}
        className="mb-2 px-3 py-1 text-xs bg-gray-700 hover:bg-gray-600 rounded text-gray-300 border border-gray-600"
        title={`当前 ${rotation}° — 点击旋转`}
      >
        🔄 {rotation}°
      </button>

      <div
        className="inline-grid justify-items-center items-center gap-1"
        style={{
          gridTemplateColumns: hasH
            ? `auto minmax(${chipMinW}px, max-content) auto`
            : `auto minmax(160px, max-content) auto`,
          gridTemplateRows: hasH
            ? `auto minmax(${chipMinH}px, max-content) auto`
            : `minmax(80px, max-content)`,
        }}
      >
        {hasH && (
          <div className="col-start-2 flex flex-wrap gap-1 justify-center">
            {top.map((p) => <PinPad key={p.gpio} {...makeProps(p)} />)}
          </div>
        )}

        <div className={`flex flex-col gap-1 ${hasH ? 'row-start-2' : 'col-start-1 row-start-1'}`}>
          {left.map((p) => <PinPad key={p.gpio} {...makeProps(p)} />)}
        </div>

        <div
          className={[
            'rounded-lg flex items-center justify-center px-4 py-2 select-none shrink-0',
            'bg-slate-800 border-2 border-slate-600',
            hasH ? 'row-start-2 col-start-2' : 'row-start-1 col-start-2',
          ].join(' ')}
          style={{ minWidth: chipMinW, minHeight: chipMinH }}
        >
          <div className="flex flex-col items-center gap-1">
            <div className="w-2 h-2 rounded-full bg-slate-500 self-start ml-0.5" />
            <span className="text-slate-400 text-sm font-bold whitespace-nowrap">
              {config.chip.name}
            </span>
          </div>
        </div>

        <div className={`flex flex-col gap-1 ${hasH ? 'row-start-2 col-start-3' : 'row-start-1 col-start-3'}`}>
          {right.map((p) => <PinPad key={p.gpio} {...makeProps(p)} />)}
        </div>

        {hasH && (
          <div className="col-start-2 row-start-3 flex flex-wrap gap-1 justify-center">
            {bottom.map((p) => <PinPad key={p.gpio} {...makeProps(p)} />)}
          </div>
        )}
      </div>
    </div>
  );
}
