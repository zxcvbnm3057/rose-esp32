import { useState, useEffect, useCallback } from 'react';
import { api } from '../../services/api';
import { useDeviceStore } from '../../stores/deviceStore';
import type { CustomCommand } from '../../types';

interface Props {
  onEdit: (slug: string) => void;
  onCreate: () => void;
  /** Increment to trigger re-fetch (e.g. when editor closes) */
  refreshKey?: number;
}

export function CustomCmdListPanel({ onEdit, onCreate, refreshKey }: Props) {
  const [cmds, setCmds] = useState<CustomCommand[]>([]);
  const [loading, setLoading] = useState(true);
  const addHistory = useDeviceStore((s) => s.addHistory);
  const now = () => new Date().toLocaleTimeString();

  const fetchCmds = useCallback(async () => {
    setLoading(true);
    try {
      const res = await api.listCmds() as { data: { commands: CustomCommand[] } };
      setCmds(res.data.commands);
    } catch { /* ignore */ }
    setLoading(false);
  }, []);

  useEffect(() => { fetchCmds(); }, [fetchCmds, refreshKey]);

  const handleExecute = async (slug: string) => {
    try {
      await api.executeCmd(slug);
      addHistory({ time: now(), op: `执行: ${slug}`, result: '✓' });
    } catch (e: unknown) {
      addHistory({ time: now(), op: `执行: ${slug}`, result: `✗ ${(e as Error).message}` });
    }
  };

  const handleDelete = async (slug: string) => {
    if (!confirm('确认删除此指令?')) return;
    try {
      await api.deleteCmd(slug);
      fetchCmds();
    } catch { /* ignore */ }
  };

  return (
    <div className="flex-1 overflow-y-auto">
      {/* Header with create button */}
      <div className="flex items-center justify-between px-3 py-2 border-b border-gray-800">
        <span className="text-xs text-gray-500">{cmds.length} 条指令</span>
        <button
          onClick={onCreate}
          className="px-2 py-0.5 bg-blue-600 hover:bg-blue-500 rounded text-xs"
        >
          + 新建
        </button>
      </div>

      {loading ? (
        <div className="p-3 text-xs text-gray-600">加载中…</div>
      ) : cmds.length === 0 ? (
        <div className="p-3 text-xs text-gray-600">
          暂无自定义指令
          <div className="mt-2">点击「+ 新建」创建跨协议组合指令</div>
        </div>
      ) : (
        <div className="divide-y divide-gray-800">
          {cmds.map((cmd) => (
            <div key={cmd.id} className="px-3 py-2.5 hover:bg-gray-800/50 group">
              <div className="flex items-start justify-between">
                <div className="flex-1 min-w-0">
                  <div className="text-sm font-medium text-gray-200 truncate">
                    {cmd.icon} {cmd.name}
                  </div>
                  <div className="text-[10px] text-gray-500 mt-0.5">
                    {cmd.step_count} 步骤 · 执行 {cmd.execution_count} 次
                  </div>
                  {cmd.description && (
                    <div className="text-[10px] text-gray-600 mt-0.5 truncate">{cmd.description}</div>
                  )}
                </div>
                <div className="hidden group-hover:flex gap-1 shrink-0 ml-2">
                  <button
                    onClick={() => handleExecute(cmd.slug)}
                    className="px-1.5 py-0.5 bg-green-800 hover:bg-green-700 rounded text-[10px] text-green-300"
                    title="执行"
                  >
                    ▶
                  </button>
                  <button
                    onClick={() => onEdit(cmd.slug)}
                    className="px-1.5 py-0.5 bg-gray-700 hover:bg-gray-600 rounded text-[10px] text-gray-300"
                    title="编辑"
                  >
                    ✎
                  </button>
                  <button
                    onClick={() => handleDelete(cmd.slug)}
                    className="px-1.5 py-0.5 bg-red-900 hover:bg-red-800 rounded text-[10px] text-red-300"
                    title="删除"
                  >
                    ✕
                  </button>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
