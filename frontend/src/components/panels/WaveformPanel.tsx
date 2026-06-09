import { useRef, useEffect, useState, useCallback } from 'react';
import { useDeviceStore } from '../../stores/deviceStore';

type EdgeEvent = { gpio: number; edge_type: number; timestamp_us: number };

const PIN_COLORS = ['#eab308', '#22d3ee', '#a78bfa', '#f472b6', '#34d399', '#fb923c', '#f87171', '#60a5fa'];

export function WaveformPanel() {
  const edgeEvents = useDeviceStore((s) => s.edgeEvents);
  const clearEdgeEvents = useDeviceStore((s) => s.clearEdgeEvents);
  const pinStates = useDeviceStore((s) => s.pinStates);
  const monitoredPins = useDeviceStore((s) => s.monitoredPins);
  const toggleMonitoredPin = useDeviceStore((s) => s.toggleMonitoredPin);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const [collapsed, setCollapsed] = useState(false);
  const animRef = useRef(0);

  // Find all pins in INTERRUPT mode
  const interruptPins = Object.entries(pinStates)
    .filter(([, s]) => s.mode === 'INTERRUPT')
    .map(([gpio]) => Number(gpio));

  // Pins to actually render: monitored pins that are also in INTERRUPT mode
  const activeMonitoredPins = Object.keys(monitoredPins)
    .map(Number)
    .filter((gpio) => interruptPins.includes(gpio));

  const draw = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    const w = canvas.width;
    const h = canvas.height;
    ctx.clearRect(0, 0, w, h);

    // Background
    ctx.fillStyle = '#0f172a';
    ctx.fillRect(0, 0, w, h);

    // Grid lines
    const pinnedGpios = activeMonitoredPins.length > 0 ? activeMonitoredPins : interruptPins;
    const nPins = pinnedGpios.length;
    if (nPins === 0) {
      ctx.fillStyle = '#475569';
      ctx.font = '12px monospace';
      ctx.textAlign = 'center';
      ctx.fillText('No INT pins — set a pin to INTERRUPT mode to see waveform', w / 2, h / 2);
      return;
    }

    const bandH = h / nPins;
    ctx.strokeStyle = '#1e293b';
    ctx.lineWidth = 0.5;
    for (let i = 1; i < nPins; i++) {
      const y = bandH * i;
      ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(w, y); ctx.stroke();
    }

    // Build per-pin event lists
    const perPin: Record<number, EdgeEvent[]> = {};
    for (const gpio of pinnedGpios) perPin[gpio] = [];
    for (const ev of edgeEvents) {
      if (perPin[ev.gpio]) perPin[ev.gpio].push(ev);
    }

    // Global time domain (union of all events)
    const allEvents = pinnedGpios.flatMap((g) => perPin[g]);
    if (allEvents.length < 2) {
      for (let i = 0; i < nPins; i++) {
        const yTop = bandH * i;
        ctx.fillStyle = COLORS_BY_GPIO[pinnedGpios[i]] ?? PIN_COLORS[i % PIN_COLORS.length];
        ctx.globalAlpha = 0.6;
        ctx.fillRect(4, yTop + bandH * 0.25, 80, bandH * 0.5);
        ctx.globalAlpha = 1;
        ctx.fillStyle = '#94a3b8';
        ctx.font = '10px monospace';
        ctx.textAlign = 'left';
        ctx.fillText(`GPIO${pinnedGpios[i]}`, 90, yTop + bandH * 0.6);
      }
      return;
    }

    const minTs = Math.min(...allEvents.map((e) => e.timestamp_us));
    const maxTs = Math.max(...allEvents.map((e) => e.timestamp_us));
    const timeRange = Math.max(maxTs - minTs, 1);

    for (let i = 0; i < nPins; i++) {
      const gpio = pinnedGpios[i];
      const evts = perPin[gpio];
      const yTop = bandH * i;
      const yMid = yTop + bandH / 2;
      const color = COLORS_BY_GPIO[gpio] ?? PIN_COLORS[i % PIN_COLORS.length];

      if (evts.length < 2) continue;

      ctx.strokeStyle = color;
      ctx.lineWidth = 1.5;
      ctx.beginPath();

      let level = evts[0].edge_type === 0 ? 1 : 0; // first event: falling means was HIGH
      const x0 = ((evts[0].timestamp_us - minTs) / timeRange) * w;
      ctx.moveTo(x0, level ? yTop + 4 : yTop + bandH - 4);

      for (const ev of evts) {
        const x = ((ev.timestamp_us - minTs) / timeRange) * w;
        // transition: vertical line
        ctx.lineTo(x, level ? yTop + 4 : yTop + bandH - 4);
        // new level
        level = ev.edge_type === 1 ? 1 : 0;
        ctx.lineTo(x, level ? yTop + 4 : yTop + bandH - 4);
      }
      // Extend to end
      ctx.lineTo(w, level ? yTop + 4 : yTop + bandH - 4);
      ctx.stroke();

      // Label
      ctx.fillStyle = color;
      ctx.font = 'bold 10px monospace';
      ctx.textAlign = 'left';
      ctx.fillText(`GPIO${gpio}`, 4, yMid + 3);
    }

    // Time label
    ctx.fillStyle = '#64748b';
    ctx.font = '9px monospace';
    ctx.textAlign = 'right';
    ctx.fillText(`${(timeRange / 1000).toFixed(1)}ms`, w - 4, h - 2);
  }, [edgeEvents, interruptPins, activeMonitoredPins]);

  // Render on every frame when visible
  useEffect(() => {
    let raf = 0;
    const loop = () => {
      draw();
      raf = requestAnimationFrame(loop);
    };
    raf = requestAnimationFrame(loop);
    return () => cancelAnimationFrame(raf);
  }, [draw]);

  if (interruptPins.length === 0 && edgeEvents.length === 0) return null;

  return (
    <div ref={containerRef} className="border-t border-gray-700 bg-gray-950">
      {/* Header */}
      <div className="flex items-center justify-between px-3 py-1.5 border-b border-gray-800 bg-gray-900">
        <button
          onClick={() => setCollapsed(!collapsed)}
          className="text-gray-400 text-xs font-medium flex items-center gap-2"
        >
          <span className="w-1.5 h-1.5 rounded-full bg-yellow-500" />
          📈 Waveform
          <span className="text-gray-600">{collapsed ? '▶' : '▼'}</span>
        </button>
        <div className="flex items-center gap-2">
          {interruptPins.map((gpio) => {
            const active = monitoredPins[gpio] != null;
            return (
              <button
                key={gpio}
                onClick={() => toggleMonitoredPin(gpio)}
                className={`text-[10px] px-1.5 py-0.5 rounded border ${
                  active
                    ? 'bg-yellow-500/20 border-yellow-500/50 text-yellow-400'
                    : 'bg-gray-800 border-gray-700 text-gray-600 hover:text-gray-400'
                }`}
              >
                GPIO{gpio}
              </button>
            );
          })}
          <button
            onClick={() => clearEdgeEvents()}
            className="text-[10px] text-gray-600 hover:text-gray-400 bg-gray-800 rounded px-1.5 py-0.5"
          >
            clear
          </button>
        </div>
      </div>

      {!collapsed && (
        <canvas
          ref={canvasRef}
          width={800}
          height={Math.max(60, activeMonitoredPins.length * 50 || interruptPins.length * 50)}
          className="w-full block"
        />
      )}
    </div>
  );
}

// Color mapping for specific GPIOs
const COLORS_BY_GPIO: Record<number, string> = {};
