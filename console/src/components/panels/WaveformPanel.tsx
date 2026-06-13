import { useRef, useEffect, useState, useMemo } from 'react';
import { useDeviceStore } from '../../stores/deviceStore';

type EdgeEvent = { gpio: number; edge_type: number; timestamp_us: number };

const PIN_COLORS = ['#eab308', '#22d3ee', '#a78bfa', '#f472b6', '#34d399', '#fb923c', '#f87171', '#60a5fa'];

const LS_KEY = 'waveform_monitored_pins';

function loadMonitoredPins(): Set<number> {
  try {
    const raw = localStorage.getItem(LS_KEY);
    if (!raw) return new Set();
    return new Set(JSON.parse(raw) as number[]);
  } catch {
    return new Set();
  }
}

function saveMonitoredPins(pins: Set<number>) {
  try {
    localStorage.setItem(LS_KEY, JSON.stringify([...pins]));
  } catch { /* ignore */ }
}

export function WaveformPanel() {
  const edgeEvents = useDeviceStore((s) => s.edgeEvents);
  const clearEdgeEvents = useDeviceStore((s) => s.clearEdgeEvents);
  const pinStates = useDeviceStore((s) => s.pinStates);
  const monitoredPins = useDeviceStore((s) => s.monitoredPins);
  const toggleMonitoredPin = useDeviceStore((s) => s.toggleMonitoredPin);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const [collapsed, setCollapsed] = useState(false);
  const edgeEventsRef = useRef(edgeEvents);
  edgeEventsRef.current = edgeEvents;
  const pinStatesRef = useRef(pinStates);
  pinStatesRef.current = pinStates;
  const liveBaseRef = useRef<{ eventMaxTs: number; perfMs: number } | null>(null);

  // Restore monitored pins from localStorage on mount
  useEffect(() => {
    const saved = loadMonitoredPins();
    if (saved.size > 0) {
      const store = useDeviceStore.getState();
      for (const gpio of saved) {
        if (!store.monitoredPins.has(gpio)) {
          store.toggleMonitoredPin(gpio);
        }
      }
    }
  }, []);

  // Save monitored pins to localStorage whenever they change
  useEffect(() => {
    saveMonitoredPins(monitoredPins);
  }, [monitoredPins]);

  // Find all pins in INTERRUPT mode — stable via useMemo
  const interruptPins = useMemo(
    () => Object.entries(pinStates)
      .filter(([, s]) => s.mode === 'INTERRUPT')
      .map(([gpio]) => Number(gpio)),
    [pinStates],
  );

  // Pins to actually render — stable via useMemo
  const activeMonitoredPins = useMemo(
    () => [...monitoredPins].filter((gpio) => interruptPins.includes(gpio)),
    [monitoredPins, interruptPins],
  );

  const pinnedGpios = activeMonitoredPins.length > 0 ? activeMonitoredPins : interruptPins;
  const pinnedGpiosRef = useRef(pinnedGpios);
  pinnedGpiosRef.current = pinnedGpios;

  // Single rAF loop — runs forever, reads everything from refs
  useEffect(() => {
    const draw = () => {
      const canvas = canvasRef.current;
      if (!canvas) return;
      const ctx = canvas.getContext('2d');
      if (!ctx) return;

      const w = canvas.width;
      const h = canvas.height;
      ctx.clearRect(0, 0, w, h);
      ctx.fillStyle = '#0f172a';
      ctx.fillRect(0, 0, w, h);

      const gpios = pinnedGpiosRef.current;
      const nPins = gpios.length;
      if (nPins === 0) {
        return;
      }

      const events = edgeEventsRef.current;
      const states = pinStatesRef.current;

      const bandH = h / nPins;
      ctx.strokeStyle = '#1e293b';
      ctx.lineWidth = 0.5;
      for (let i = 1; i < nPins; i++) {
        const y = bandH * i;
        ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(w, y); ctx.stroke();
      }

      const perPin: Record<number, EdgeEvent[]> = {};
      for (const gpio of gpios) perPin[gpio] = [];
      for (const ev of events) {
        if (perPin[ev.gpio]) perPin[ev.gpio].push(ev);
      }

      const allEvents = gpios.flatMap((g) => perPin[g]);
      if (allEvents.length < 2) {
        for (let i = 0; i < nPins; i++) {
          const gpio = gpios[i];
          const yTop = bandH * i;
          const yMid = yTop + bandH / 2;
          const color = COLORS_BY_GPIO[gpio] ?? PIN_COLORS[i % PIN_COLORS.length];
          const val = states[gpio]?.value;
          if (val === 0 || val === 1) {
            const yLine = val === 1 ? yTop + 4 : yTop + bandH - 4;
            ctx.strokeStyle = color; ctx.lineWidth = 2; ctx.globalAlpha = 0.5;
            ctx.beginPath(); ctx.moveTo(0, yLine); ctx.lineTo(w, yLine); ctx.stroke();
            ctx.globalAlpha = 1;
            ctx.fillStyle = color; ctx.font = '10px monospace'; ctx.textAlign = 'left';
            ctx.fillText(`GPIO${gpio} ${val === 1 ? 'HIGH' : 'LOW'}`, 8, yMid + 3);
          } else {
            ctx.fillStyle = color; ctx.globalAlpha = 0.15;
            ctx.fillRect(4, yTop + bandH * 0.15, w - 8, bandH * 0.7);
            ctx.globalAlpha = 1;
            ctx.fillStyle = color; ctx.font = '10px monospace'; ctx.textAlign = 'left';
            ctx.fillText(`GPIO${gpio} (-- unknown)`, 12, yMid + 3);
          }
        }
        return;
      }

      const minTs = Math.min(...allEvents.map((e: EdgeEvent) => e.timestamp_us));
      const eventMaxTs = Math.max(...allEvents.map((e: EdgeEvent) => e.timestamp_us));
      const base2 = liveBaseRef.current;
      if (!base2 || base2.eventMaxTs !== eventMaxTs) {
        liveBaseRef.current = { eventMaxTs, perfMs: performance.now() };
      }
      const liveMaxTs = eventMaxTs + Math.max(0, (performance.now() - liveBaseRef.current!.perfMs) * 1000);
      const timeRange = Math.max(liveMaxTs - minTs, 1);

      for (let i = 0; i < nPins; i++) {
        const gpio = gpios[i];
        const evts = perPin[gpio];
        const yTop = bandH * i;
        const yMid = yTop + bandH / 2;
        const color = COLORS_BY_GPIO[gpio] ?? PIN_COLORS[i % PIN_COLORS.length];
        const curVal: number | null | undefined = states[gpio]?.value;

        if (evts.length < 2 && (curVal === 0 || curVal === 1)) {
          const yLine = curVal === 1 ? yTop + 4 : yTop + bandH - 4;
          ctx.strokeStyle = color; ctx.lineWidth = 2; ctx.globalAlpha = 0.5;
          ctx.beginPath(); ctx.moveTo(0, yLine); ctx.lineTo(w, yLine); ctx.stroke();
          ctx.globalAlpha = 1;
          ctx.fillStyle = color; ctx.font = '10px monospace'; ctx.textAlign = 'left';
          ctx.fillText(`GPIO${gpio} ${curVal === 1 ? 'HIGH' : 'LOW'}`, 8, yMid + 3);
          continue;
        }
        if (evts.length < 2) {
          ctx.fillStyle = color; ctx.globalAlpha = 0.15;
          ctx.fillRect(4, yTop + bandH * 0.15, w - 8, bandH * 0.7);
          ctx.globalAlpha = 1;
          ctx.fillStyle = color; ctx.font = '10px monospace'; ctx.textAlign = 'left';
          ctx.fillText(`GPIO${gpio} (-- unknown)`, 12, yMid + 3);
          continue;
        }

        ctx.strokeStyle = color; ctx.lineWidth = 1.5; ctx.beginPath();
        let level = evts[0].edge_type === 1 ? 0 : 1;
        ctx.moveTo(0, level ? yTop + 4 : yTop + bandH - 4);
        for (const ev of evts) {
          const x = ((ev.timestamp_us - minTs) / timeRange) * w;
          ctx.lineTo(x, level ? yTop + 4 : yTop + bandH - 4);
          level = ev.edge_type === 1 ? 1 : 0;
          ctx.lineTo(x, level ? yTop + 4 : yTop + bandH - 4);
        }
        ctx.lineTo(w, level ? yTop + 4 : yTop + bandH - 4); ctx.stroke();
        ctx.fillStyle = color; ctx.font = 'bold 10px monospace'; ctx.textAlign = 'left';
        ctx.fillText(`GPIO${gpio}`, 4, yMid + 3);
      }
      ctx.fillStyle = '#64748b'; ctx.font = '9px monospace'; ctx.textAlign = 'right';
      ctx.fillText(`${(timeRange / 1000).toFixed(1)}ms`, w - 4, h - 2);
    };
    let raf = 0;
    const loop = () => { draw(); raf = requestAnimationFrame(loop); };
    raf = requestAnimationFrame(loop);
    return () => cancelAnimationFrame(raf);
  }, []);

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
            const active = monitoredPins.has(gpio);
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
          height={Math.max(60, pinnedGpios.length * 50)}
          className="w-full block"
        />
      )}
    </div>
  );
}

// Color mapping for specific GPIOs
const COLORS_BY_GPIO: Record<number, string> = {};
