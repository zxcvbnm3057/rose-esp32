import { useState } from 'react';
import { api } from '../../services/api';
import { useDeviceStore } from '../../stores/deviceStore';

const COMMANDS = [
  { group: 'GPIO', items: [
    { op: 'gpio_config', label: 'GPIO Config', fields: ['gpio', 'mode', 'pull', 'edge'] },
    { op: 'gpio_set', label: 'GPIO Set', fields: ['gpio', 'value'] },
    { op: 'gpio_get', label: 'GPIO Get', fields: ['gpio'] },
    { op: 'adc_sample', label: 'ADC Sample', fields: ['gpio', 'samples'] },
  ]},
  { group: 'UART', items: [
    { op: 'uart_config', label: 'UART Config', fields: ['uart_id', 'baudrate', 'tx_gpio', 'rx_gpio'] },
    { op: 'uart_send', label: 'UART Send', fields: ['uart_id', 'data'] },
    { op: 'uart_read', label: 'UART Read', fields: ['uart_id', 'length'] },
  ]},
  { group: '端口', items: [
    { op: 'port_bind', label: 'Port Bind', fields: ['resource_type', 'id'] },
    { op: 'port_unbind', label: 'Port Unbind', fields: ['resource_type', 'id'] },
    { op: 'port_status', label: 'Port Status', fields: ['resource_type', 'id'] },
  ]},
  { group: '系统', items: [
    { op: 'ping', label: 'Ping', fields: [] },
    { op: 'heartbeat', label: 'Heartbeat', fields: [] },
    { op: 'sync', label: 'Sync', fields: [] },
  ]},
];

export function CommandPanel() {
  const [activeOp, setActiveOp] = useState<string | null>(null);
  const [formValues, setFormValues] = useState<Record<string, string>>({});
  const addHistory = useDeviceStore((s) => s.addHistory);
  const history = useDeviceStore((s) => s.history);

  const now = () => new Date().toLocaleTimeString();

  const handleSend = async () => {
    if (!activeOp) return;
    try {
      const v = formValues;
      switch (activeOp) {
        case 'gpio_config':
          await api.gpioConfig(+v.gpio, +v.mode, +(v.pull || 0), +(v.edge || 0)); break;
        case 'gpio_set':
          await api.gpioSet(+v.gpio, +v.value); break;
        case 'gpio_get': {
          const r = await api.gpioGet(+v.gpio);
          addHistory({ time: now(), op: `GPIO${v.gpio} GET`, result: `→ ${(r as { data: { value: number } }).data.value}` });
          return;
        }
        case 'adc_sample': {
          const r = await api.gpioAdc(+v.gpio, +(v.samples || 1));
          addHistory({ time: now(), op: `GPIO${v.gpio} ADC`, result: `→ ${(r as { data: { value: number } }).data.value}` });
          return;
        }
        case 'uart_config':
          await api.uartConfig(+v.uart_id, { baudrate: +v.baudrate, tx_gpio: +(v.tx_gpio || 1), rx_gpio: +(v.rx_gpio || 3) }); break;
        case 'uart_send':
          await api.uartSend(+v.uart_id, v.data || ''); break;
        case 'uart_read': {
          const r = await api.uartRead(+v.uart_id, +(v.length || 256));
          addHistory({ time: now(), op: `UART${v.uart_id} READ`, result: `→ ${(r as { data: { length: number } }).data.length}B` });
          return;
        }
        case 'port_bind':
          await api.portBind(+v.resource_type, +v.id); break;
        case 'port_unbind':
          await api.portUnbind(+v.resource_type, +v.id); break;
        case 'port_status': {
          const r = await api.portStatus(+v.resource_type, +v.id);
          addHistory({ time: now(), op: `Port Status`, result: `→ ${JSON.stringify((r as { data: unknown }).data)}` });
          return;
        }
        case 'ping':
          await api.ping(); break;
        case 'heartbeat':
          await api.heartbeat(); break;
        case 'sync':
          await api.sync(); break;
      }
      addHistory({ time: now(), op: activeOp, result: '✓' });
    } catch (e: unknown) {
      addHistory({ time: now(), op: activeOp || '?', result: `✗ ${(e as Error).message}` });
    }
  };

  const cmdDef = COMMANDS.flatMap((g) => g.items).find((c) => c.op === activeOp);

  return (
    <div className="flex h-full">
      {/* Command list */}
      <div className="w-56 border-r border-gray-700 p-3 overflow-y-auto">
        {COMMANDS.map((group) => (
          <div key={group.group} className="mb-4">
            <div className="text-xs font-semibold text-gray-500 mb-1">{group.group}</div>
            {group.items.map((cmd) => (
              <button
                key={cmd.op}
                onClick={() => { setActiveOp(cmd.op); setFormValues({}); }}
                className={`block w-full text-left px-2 py-1 text-sm rounded mb-0.5 ${activeOp === cmd.op ? 'bg-blue-600 text-white' : 'text-gray-300 hover:bg-gray-700'}`}
              >
                {cmd.label}
              </button>
            ))}
          </div>
        ))}
      </div>

      {/* Form + History */}
      <div className="flex-1 flex flex-col">
        <div className="p-4 border-b border-gray-700">
          {cmdDef ? (
            <div>
              <h3 className="font-medium mb-3">{cmdDef.label}</h3>
              <div className="grid grid-cols-2 gap-2 mb-3">
                {cmdDef.fields.map((f) => (
                  <div key={f}>
                    <label className="text-xs text-gray-500 block">{f}</label>
                    <input
                      type="text"
                      value={formValues[f] || ''}
                      onChange={(e) => setFormValues({ ...formValues, [f]: e.target.value })}
                      className="w-full bg-gray-800 border border-gray-600 rounded px-2 py-1 text-sm text-gray-200"
                    />
                  </div>
                ))}
              </div>
              <button onClick={handleSend} className="px-4 py-1.5 bg-blue-600 hover:bg-blue-500 rounded text-sm">
                ⚡ 发送
              </button>
            </div>
          ) : (
            <div className="text-gray-500 text-sm">← 选择一条指令</div>
          )}
        </div>
        <div className="flex-1 p-3 overflow-y-auto">
          <div className="text-xs text-gray-500 mb-2">历史记录</div>
          {history.map((h, i) => (
            <div key={i} className="text-xs text-gray-400 py-0.5 font-mono">
              {h.time} {h.op} {h.result}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
