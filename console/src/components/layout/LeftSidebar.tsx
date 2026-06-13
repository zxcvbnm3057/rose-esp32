import { useState, useEffect, useCallback } from 'react';
import { api } from '../../services/api';
import { useDeviceStore } from '../../stores/deviceStore';
import type { CustomCommand } from '../../types';

// ── Command definitions ──────────────────────────────

interface CmdDef {
  op: string;
  label: string;
  fields: { name: string; label: string; type?: 'text' | 'select'; options?: { v: string; l: string }[] }[];
}

const CMD_GROUPS: { group: string; icon: string; items: CmdDef[] }[] = [
  {
    group: 'GPIO', icon: '📌',
    items: [
      { op: 'gpio_config', label: 'GPIO 配置', fields: [
        { name: 'gpio', label: 'GPIO' },
        { name: 'mode', label: '模式', type: 'select', options: [
          { v: '0', l: 'INPUT' }, { v: '1', l: 'OUTPUT' },
          { v: '2', l: 'INTERRUPT' }, { v: '3', l: 'ADC' }, { v: '4', l: 'SIGNAL' },
        ]},
        { name: 'pull', label: '上下拉', type: 'select', options: [
          { v: '0', l: '无' }, { v: '1', l: '下拉' }, { v: '2', l: '上拉' },
        ]},
        { name: 'edge', label: '边沿', type: 'select', options: [
          { v: '0', l: '无' }, { v: '1', l: '上升' }, { v: '2', l: '下降' }, { v: '3', l: '双沿' },
        ]},
      ]},
      { op: 'gpio_set', label: 'GPIO 置位', fields: [
        { name: 'gpio', label: 'GPIO' },
        { name: 'value', label: '电平', type: 'select', options: [{ v: '0', l: '低(0)' }, { v: '1', l: '高(1)' }] },
      ]},
      { op: 'gpio_get', label: 'GPIO 读取', fields: [
        { name: 'gpio', label: 'GPIO' },
      ]},
      { op: 'adc_sample', label: 'ADC 采样', fields: [
        { name: 'gpio', label: 'GPIO' },
        { name: 'samples', label: '采样次数' },
      ]},
    ],
  },
  {
    group: 'UART', icon: '📡',
    items: [
      { op: 'uart_config', label: 'UART 配置', fields: [
        { name: 'uart_id', label: 'UART ID' },
        { name: 'baudrate', label: '波特率' },
        { name: 'tx_gpio', label: 'TX GPIO' },
        { name: 'rx_gpio', label: 'RX GPIO' },
      ]},
      { op: 'uart_send', label: 'UART 发送', fields: [
        { name: 'uart_id', label: 'UART ID' },
        { name: 'data', label: '数据' },
      ]},
      { op: 'uart_read', label: 'UART 读取', fields: [
        { name: 'uart_id', label: 'UART ID' },
        { name: 'length', label: '读取长度' },
      ]},
    ],
  },
  {
    group: '端口', icon: '🔌',
    items: [
      { op: 'port_bind', label: '端口绑定', fields: [
        { name: 'resource_type', label: '资源类型' },
        { name: 'id', label: 'ID' },
      ]},
      { op: 'port_unbind', label: '端口解绑', fields: [
        { name: 'resource_type', label: '资源类型' },
        { name: 'id', label: 'ID' },
      ]},
      { op: 'port_status', label: '端口状态', fields: [
        { name: 'resource_type', label: '资源类型' },
        { name: 'id', label: 'ID' },
      ]},
    ],
  },
  {
    group: '系统', icon: '⚙️',
    items: [
      { op: 'ping', label: 'Ping', fields: [] },
      { op: 'heartbeat', label: 'Heartbeat', fields: [] },
      { op: 'sync', label: 'Sync', fields: [] },
    ],
  },
];

// ── Component ─────────────────────────────────────────

interface Props {
  onEditCmd: (slug: string | null) => void;
}

export function LeftSidebar({ onEditCmd }: Props) {
  const addHistory = useDeviceStore((s) => s.addHistory);
  const selectGpio = useDeviceStore((s) => s.selectGpio);

  // Collapsed groups
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({});
  // Active command op → shows inline form
  const [activeOp, setActiveOp] = useState<string | null>(null);
  const [formValues, setFormValues] = useState<Record<string, string>>({});

  // Custom commands
  const [cmds, setCmds] = useState<CustomCommand[]>([]);
  const [cmdsCollapsed, setCmdsCollapsed] = useState(false);

  const toggleGroup = (g: string) => setCollapsed((c) => ({ ...c, [g]: !c[g] }));

  const now = () => new Date().toLocaleTimeString();

  // ── Execute command ──
  const handleSend = useCallback(async () => {
    if (!activeOp) return;
    const v = formValues;
    try {
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
          addHistory({ time: now(), op: 'Port Status', result: `→ ${JSON.stringify((r as { data: unknown }).data)}` });
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
  }, [activeOp, formValues, addHistory]);

  // ── Custom commands ──
  const fetchCmds = useCallback(async () => {
    try {
      const res = await api.listCmds() as { data: { commands: CustomCommand[] } };
      setCmds(res.data.commands);
    } catch { /* ignore */ }
  }, []);

  useEffect(() => { fetchCmds(); }, [fetchCmds]);

  const handleExecuteCmd = async (slug: string) => {
    try {
      await api.executeCmd(slug);
      addHistory({ time: now(), op: `执行: ${slug}`, result: '✓' });
    } catch (e: unknown) {
      addHistory({ time: now(), op: `执行: ${slug}`, result: `✗ ${(e as Error).message}` });
    }
  };

  const handleDeleteCmd = async (slug: string) => {
    if (!confirm('确认删除?')) return;
    try {
      await api.deleteCmd(slug);
      fetchCmds();
    } catch { /* ignore */ }
  };

  const activeCmdDef = CMD_GROUPS.flatMap((g) => g.items).find((c) => c.op === activeOp);

  return (
    <div className="w-64 border-r border-gray-700 bg-gray-900 flex flex-col overflow-hidden shrink-0">
      {/* Command tree */}
      <div className="flex-1 overflow-y-auto">
        {CMD_GROUPS.map((group) => (
          <div key={group.group} className="border-b border-gray-800">
            <button
              onClick={() => toggleGroup(group.group)}
              className="w-full flex items-center gap-2 px-3 py-2 text-xs font-semibold text-gray-400 hover:bg-gray-800"
            >
              <span>{collapsed[group.group] ? '▶' : '▼'}</span>
              <span>{group.icon}</span>
              <span>{group.group}</span>
            </button>
            {!collapsed[group.group] && group.items.map((cmd) => (
              <button
                key={cmd.op}
                onClick={() => {
                  setActiveOp(activeOp === cmd.op ? null : cmd.op);
                  setFormValues({});
                }}
                className={`w-full text-left pl-9 pr-3 py-1.5 text-xs ${
                  activeOp === cmd.op
                    ? 'bg-blue-600/30 text-blue-300 border-l-2 border-blue-500'
                    : 'text-gray-400 hover:bg-gray-800 hover:text-gray-200'
                }`}
              >
                {cmd.label}
              </button>
            ))}
          </div>
        ))}
      </div>

      {/* Inline command form (when a command is active) */}
      {activeOp && activeCmdDef && (
        <div className="border-t border-gray-700 bg-gray-800 p-3 max-h-60 overflow-y-auto">
          <div className="flex items-center justify-between mb-2">
            <span className="text-xs font-medium text-blue-300">{activeCmdDef.label}</span>
            <button
              onClick={() => setActiveOp(null)}
              className="text-gray-500 hover:text-gray-300 text-xs"
            >
              ✕
            </button>
          </div>
          <div className="space-y-1.5">
            {activeCmdDef.fields.map((f) => (
              <div key={f.name}>
                <label className="text-[10px] text-gray-500 block">{f.label}</label>
                {f.type === 'select' && f.options ? (
                  <select
                    value={formValues[f.name] || f.options[0]?.v || ''}
                    onChange={(e) => setFormValues({ ...formValues, [f.name]: e.target.value })}
                    className="w-full bg-gray-700 border border-gray-600 rounded px-1.5 py-0.5 text-xs text-gray-200"
                  >
                    {f.options.map((o) => (
                      <option key={o.v} value={o.v}>{o.l}</option>
                    ))}
                  </select>
                ) : (
                  <input
                    type="text"
                    value={formValues[f.name] || ''}
                    onChange={(e) => setFormValues({ ...formValues, [f.name]: e.target.value })}
                    className="w-full bg-gray-700 border border-gray-600 rounded px-1.5 py-0.5 text-xs text-gray-200"
                  />
                )}
              </div>
            ))}
          </div>
          <button
            onClick={handleSend}
            className="w-full mt-2 py-1 bg-blue-600 hover:bg-blue-500 rounded text-xs font-medium"
          >
            ⚡ 发送
          </button>
        </div>
      )}

      {/* Custom commands section */}
      <div className="border-t border-gray-700">
        <button
          onClick={() => setCmdsCollapsed(!cmdsCollapsed)}
          className="w-full flex items-center justify-between px-3 py-2 text-xs font-semibold text-gray-400 hover:bg-gray-800"
        >
          <span className="flex items-center gap-2">
            <span>{cmdsCollapsed ? '▶' : '▼'}</span>
            <span>📋 自定义指令</span>
          </span>
          <button
            onClick={(e) => { e.stopPropagation(); onEditCmd(''); }}
            className="text-blue-400 hover:text-blue-300 text-lg leading-none"
            title="新建"
          >
            +
          </button>
        </button>
        {!cmdsCollapsed && (
          <div className="max-h-40 overflow-y-auto">
            {cmds.length === 0 ? (
              <div className="px-3 py-2 text-xs text-gray-600">暂无指令</div>
            ) : (
              cmds.map((cmd) => (
                <div key={cmd.id} className="px-3 py-1.5 hover:bg-gray-800 group flex items-center justify-between">
                  <button
                    onClick={() => handleExecuteCmd(cmd.slug)}
                    className="text-xs text-gray-300 hover:text-white truncate flex-1 text-left"
                    title={cmd.name}
                  >
                    {cmd.icon} {cmd.name}
                  </button>
                  <span className="hidden group-hover:flex gap-0.5 shrink-0">
                    <button
                      onClick={(e) => { e.stopPropagation(); onEditCmd(cmd.slug); }}
                      className="text-gray-500 hover:text-blue-400 text-xs px-0.5"
                      title="编辑"
                    >
                      ✎
                    </button>
                    <button
                      onClick={(e) => { e.stopPropagation(); handleDeleteCmd(cmd.slug); }}
                      className="text-gray-500 hover:text-red-400 text-xs px-0.5"
                      title="删除"
                    >
                      ✕
                    </button>
                  </span>
                </div>
              ))
            )}
          </div>
        )}
      </div>
    </div>
  );
}
