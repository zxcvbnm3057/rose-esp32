import { useMemo } from 'react';
import { useDeviceStore, getUartForGpio } from '../../stores/deviceStore';
import { computePadPositions, CHIP_X, CHIP_Y, CHIP_W, CHIP_H, SVG_W, SVG_H } from './chipLayout';
import { PinPad } from './PinPad';

export function ChipView() {
  const config = useDeviceStore((s) => s.hardwareConfig);
  const pinStates = useDeviceStore((s) => s.pinStates);
  const uartStates = useDeviceStore((s) => s.uartStates);
  const selectGpio = useDeviceStore((s) => s.selectGpio);

  const positions = useMemo(() => {
    if (!config) return {};
    return computePadPositions(config.pins);
  }, [config]);

  if (!config) {
    return <div className="flex items-center justify-center h-96 text-gray-500">加载硬件配置中…</div>;
  }

  return (
    <div className="flex justify-center overflow-auto p-4">
      <svg width={SVG_W} height={SVG_H} viewBox={`0 0 ${SVG_W} ${SVG_H}`}>
        {/* Chip body */}
        <rect
          x={CHIP_X}
          y={CHIP_Y}
          width={CHIP_W}
          height={CHIP_H}
          rx={12}
          fill="#1e293b"
          stroke="#334155"
          strokeWidth={2}
        />
        {/* Chip label */}
        <text
          x={CHIP_X + CHIP_W / 2}
          y={CHIP_Y + CHIP_H / 2 + 8}
          textAnchor="middle"
          fill="#94a3b8"
          fontSize={24}
          fontWeight="bold"
        >
          {config.chip.name}
        </text>

        {/* Pin pads */}
        {config.pins.map((pin) => {
          const pos = positions[pin.gpio];
          if (!pos) return null;
          const uartInfo = getUartForGpio(uartStates, pin.gpio);
          return (
            <PinPad
              key={pin.gpio}
              x={pos.x}
              y={pos.y}
              config={pin}
              state={pinStates[pin.gpio]}
              uartRole={uartInfo?.role ?? null}
              onClick={() => selectGpio(pin.gpio)}
              onContextMenu={() => selectGpio(pin.gpio)}
            />
          );
        })}
      </svg>
    </div>
  );
}
