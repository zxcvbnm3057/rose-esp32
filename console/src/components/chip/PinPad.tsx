import { useState } from 'react';
import { getPinColors, getModeLabel } from './pinColors';
import type { PinConfig, PinState } from '../../types';

export const PAD_W = 56;
export const PAD_H = 36;

interface Props {
  config: PinConfig;
  state?: PinState;
  uartRole?: 'tx' | 'rx' | null;
  selected?: boolean;
  isPicking?: boolean;
  locked?: boolean;
  mismatch?: boolean;
  fixed?: boolean;
  onClick: () => void;
  onContextMenu: () => void;
}

export function PinPad(props: Props) {
  const { config, state, uartRole, selected, isPicking, locked, mismatch, fixed, onClick, onContextMenu } = props;
  const [hover, setHover] = useState(false);
  const isReserved = config.reserved;
  const clickable = !fixed && !isReserved;
  const colors = getPinColors(fixed ? undefined : state, fixed || isReserved, uartRole);

  const label = fixed ? config.label
    : uartRole ? `UART ${uartRole.toUpperCase()}`
    : state?.mode === 'ADC' && state.adc_voltage_mv != null ? `${state.adc_voltage_mv}mV`
    : state?.mode === 'ADC' && state.adc_value != null ? String(state.adc_value)
    : getModeLabel(state?.mode);

  const valueInd = !uartRole && !fixed && (state?.mode === 'OUTPUT' || state?.mode === 'INPUT_OUTPUT')
    ? ` ${state.value === 1 ? '●' : '○'}` : '';

  const isBound = state?.bound || uartRole;
  const ringColor = selected ? '#60a5fa'
    : isPicking && hover && clickable ? '#eab308'
    : hover && clickable ? (mismatch ? '#f97316' : '#60a5fa')
    : colors.border;

  return (
    <div
      onClick={clickable ? onClick : undefined}
      onContextMenu={(e) => { e.preventDefault(); if (clickable) onContextMenu(); }}
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
      style={{
        width: PAD_W, height: PAD_H,
        backgroundColor: fixed ? '#111827' : colors.fill,
        borderColor: ringColor,
        borderWidth: selected || (hover && clickable) ? 2.5 : isBound ? 2 : 1,
        opacity: fixed ? 0.5 : 1,
        cursor: isPicking && clickable ? 'crosshair' : clickable ? 'pointer' : 'default',
        transform: (hover && clickable) ? 'scale(1.1)' : 'scale(1)',
        transformOrigin: 'center center',
        borderStyle: uartRole ? 'dashed' : 'solid',
        boxShadow: (isPicking && hover && clickable) ? '0 0 8px 2px rgba(234,179,8,0.5)' : undefined,
      }}
      className={[
        'rounded flex flex-col items-center justify-center select-none shrink-0 relative',
        clickable ? 'transition-transform duration-150' : '',
      ].join(' ')}
    >
      <span
        style={{ color: fixed ? '#6b7280' : colors.text, fontSize: 10, fontWeight: 700, lineHeight: 1.2 }}
        className="truncate max-w-full px-0.5"
      >
        {config.label}
      </span>
      <span
        style={{ color: fixed ? '#4b5563' : colors.text, fontSize: 9, lineHeight: 1.2 }}
      >
        {fixed ? (config.default_mode === 'fixed' ? '' : '⛔') : label}{valueInd}
      </span>
      {(locked || isReserved) && !fixed && (
        <span style={{ position: 'absolute', top: 1, right: 3, fontSize: 7 }}>🔒</span>
      )}
      {mismatch && (
        <span style={{ position: 'absolute', top: 1, left: 3, fontSize: 7 }}>⚠️</span>
      )}
      {uartRole && (
        <span style={{ position: 'absolute', bottom: 1, right: 2, fontSize: 6, color: colors.text }}>
          {uartRole.toUpperCase()}
        </span>
      )}
    </div>
  );
}
