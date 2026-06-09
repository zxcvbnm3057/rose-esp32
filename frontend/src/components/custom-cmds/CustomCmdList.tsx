import { useState, useEffect } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { api } from '../../services/api';
import type { CustomCommand } from '../../types';

export function CustomCmdList() {
  const [cmds, setCmds] = useState<CustomCommand[]>([]);
  const [loading, setLoading] = useState(true);
  const navigate = useNavigate();

  const fetchCmds = async () => {
    setLoading(true);
    try {
      const res = await api.listCmds() as { data: { commands: CustomCommand[] } };
      setCmds(res.data.commands);
    } catch { /* ignore */ }
    setLoading(false);
  };

  useEffect(() => { fetchCmds(); }, []);

  const handleExecute = async (slug: string) => {
    try {
      await api.executeCmd(slug);
      alert('执行完成');
    } catch (e: unknown) {
      alert('执行失败: ' + (e as Error).message);
    }
  };

  const handleDelete = async (slug: string) => {
    if (!confirm('确认删除?')) return;
    try {
      await api.deleteCmd(slug);
      fetchCmds();
    } catch { /* ignore */ }
  };

  return (
    <div className="p-4">
      <div className="flex justify-between items-center mb-4">
        <h2 className="text-lg font-bold">自定义指令</h2>
        <button onClick={() => navigate('/custom-commands/new/edit')}
          className="px-3 py-1.5 bg-blue-600 hover:bg-blue-500 rounded text-sm">
          + 新建指令
        </button>
      </div>

      {loading ? (
        <div className="text-gray-500">加载中…</div>
      ) : cmds.length === 0 ? (
        <div className="text-gray-500 text-sm">暂无自定义指令，点击"新建指令"创建</div>
      ) : (
        <div className="space-y-3">
          {cmds.map((cmd) => (
            <div key={cmd.id} className="bg-gray-800 border border-gray-700 rounded-lg p-4">
              <div className="flex justify-between items-start">
                <div>
                  <div className="font-medium">
                    {cmd.name}
                    <span className={`ml-2 text-xs px-1.5 py-0.5 rounded ${cmd.enabled ? 'bg-green-900 text-green-300' : 'bg-gray-700 text-gray-400'}`}>
                      {cmd.enabled ? '启用' : '禁用'}
                    </span>
                  </div>
                  <div className="text-xs text-gray-500 mt-1">
                    {cmd.description} · {cmd.step_count} 步骤 · 执行 {cmd.execution_count} 次
                  </div>
                  <div className="text-xs text-gray-600 mt-1 font-mono">
                    外部URL: POST {cmd.external_url}
                  </div>
                </div>
                <div className="flex gap-1">
                  <button onClick={() => handleExecute(cmd.slug)}
                    className="px-2 py-1 bg-green-700 hover:bg-green-600 rounded text-xs">▶ 执行</button>
                  <button onClick={() => navigate(`/custom-commands/${cmd.slug}/edit`)}
                    className="px-2 py-1 bg-gray-600 hover:bg-gray-500 rounded text-xs">✎ 编辑</button>
                  <button onClick={() => handleDelete(cmd.slug)}
                    className="px-2 py-1 bg-red-700 hover:bg-red-600 rounded text-xs">✕</button>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
