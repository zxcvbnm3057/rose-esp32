import { PAD_W, PAD_H } from './chipLayout';
import { getPinColors, getModeLabel } from './pinColors';
import type { PinConfig, PinState } from '../../types';

interface Props {
  x: number;
  y: number;
  config: PinConfig;
  state?: PinState;
  uartRole?: 'tx' | 'rx' | null;
  onClick: (gpio: number) => void;
  onContextMenu: (gpio: number, e: React.MouseEvent) => void;
}

export function PinPad({ x, y, config, state, uartRole, onClick, onContextMenu }: Props) {
  const reserved = config.reserved;
  const colors = getPinColors(state, reserved, uartRole);

  const displayLabel = uartRole
    ? `UART ${uartRole.toUpperCase()}`
    : state?.mode === 'ADC' && state.adc_voltage_mv != null
      ? `${state.adc_voltage_mv}mV`
      : state?.mode === 'ADC' && state.adc_value != null
        ? String(state.adc_value)
        : getModeLabel(state?.mode);

  const valueIndicator = !uartRole && state?.mode === 'OUTPUT'
    ? ` ${state.value === 1 ? '●' : '○'}`
    : '';

  return (
    <g
      transform={`translate(${x}, ${y})`}
      onClick={() => !reserved && onClick(config.gpio)}
      onContextMenu={(e) => {
        e.preventDefault();
        onContextMenu(config.gpio, e);
      }}
      style={{ cursor: reserved ? 'not-allowed' : 'pointer' }}
      className="transition-transform duration-150 hover:scale-110"
    >
      <rect
        width={PAD_W}
        height={PAD_H}
        rx={6}
        stroke={colors.border}
        fill={colors.fill}
        strokeWidth={state?.bound || uartRole ? 2.5 : 1.5}
        strokeDasharray={uartRole ? '4 2' : undefined}
      />
      <text x={PAD_W / 2} y={13} textAnchor="middle" fill={colors.text} fontSize={10} fontWeight="bold">
        {config.label}
      </text>
      <text x={PAD_W / 2} y={27} textAnchor="middle" fill={colors.text} fontSize={9}>
        {displayLabel}{valueIndicator}
      </text>
      {reserved && (
        <text x={PAD_W - 8} y={10} fontSize={8}>
          🔒
        </text>
      )}
      {uartRole && (
        <text x={PAD_W - 10} y={10} fontSize={7} fill={colors.text}>
          {uartRole.toUpperCase()}
        </text>
      )}
    </g>
  );
}
