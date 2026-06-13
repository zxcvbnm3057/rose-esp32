import { useState, useEffect } from 'react';
import { api } from '../../services/api';
import type { CmdStep } from '../../types';

const STEP_TYPES = [
  'gpio_config', 'gpio_set', 'gpio_get', 'adc_sample',
  'signal_tx', 'signal_rx', 'signal_exchange',
  'uart_config', 'uart_send', 'uart_read',
  'port_bind', 'port_unbind', 'delay',
];

interface Props {
  slug?: string;       // undefined = create new
  onClose: () => void;
  onSaved: () => void;
}

export function CustomCmdEditor({ slug, onClose, onSaved }: Props) {
  const isNew = !slug;

  const [name, setName] = useState('');
  const [cmdSlug, setCmdSlug] = useState('');
  const [description, setDescription] = useState('');
  const [icon, setIcon] = useState('⚡');
  const [steps, setSteps] = useState<CmdStep[]>([
    { step_type: 'gpio_config', config: {}, delay_ms: 0, on_error: 'abort' },
  ]);

  useEffect(() => {
    if (!isNew && slug) {
      api.getCmd(slug).then((res) => {
        const cmd = (res as { data: { name: string; slug: string; description: string; icon: string; steps: CmdStep[] } }).data;
        setName(cmd.name);
        setCmdSlug(cmd.slug);
        setDescription(cmd.description || '');
        setIcon(cmd.icon || '⚡');
        setSteps(cmd.steps || []);
      }).catch(() => onClose());
    }
  }, [slug, isNew, onClose]);

  const addStep = () => {
    setSteps([...steps, { step_type: 'gpio_set', config: {}, delay_ms: 0, on_error: 'abort' }]);
  };

  const removeStep = (idx: number) => {
    setSteps(steps.filter((_, i) => i !== idx));
  };

  const updateStep = (idx: number, partial: Partial<CmdStep>) => {
    const next = [...steps];
    next[idx] = { ...next[idx], ...partial };
    setSteps(next);
  };

  const updateStepConfig = (idx: number, key: string, value: string) => {
    const next = [...steps];
    next[idx] = { ...next[idx], config: { ...next[idx].config, [key]: isNaN(Number(value)) ? value : Number(value) } };
    setSteps(next);
  };

  const handleSave = async () => {
    const data = { name, slug: cmdSlug, description, icon, steps };
    try {
      if (isNew) {
        await api.createCmd(data);
      } else {
        await api.updateCmd(cmdSlug, data);
      }
      onSaved();
    } catch (e: unknown) {
      alert('保存失败: ' + (e as Error).message);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60">
      <div className="bg-gray-900 border border-gray-700 rounded-xl shadow-2xl w-[720px] max-h-[90vh] overflow-y-auto m-4">
        <div className="sticky top-0 bg-gray-900 border-b border-gray-700 px-6 py-4 flex items-center justify-between rounded-t-xl">
          <h2 className="text-lg font-bold">{isNew ? '新建' : '编辑'}自定义指令</h2>
          <button onClick={onClose} className="text-gray-400 hover:text-white text-xl">&times;</button>
        </div>
        <div className="p-6">

      <div className="grid grid-cols-2 gap-3 mb-4">
        <div>
          <label className="text-xs text-gray-500">Slug (URL标识)</label>
          <input value={cmdSlug} onChange={(e) => setCmdSlug(e.target.value)}
            className="w-full bg-gray-800 border border-gray-600 rounded px-2 py-1 text-sm" />
        </div>
        <div>
          <label className="text-xs text-gray-500">名称</label>
          <input value={name} onChange={(e) => setName(e.target.value)}
            className="w-full bg-gray-800 border border-gray-600 rounded px-2 py-1 text-sm" />
        </div>
        <div>
          <label className="text-xs text-gray-500">图标 (emoji)</label>
          <input value={icon} onChange={(e) => setIcon(e.target.value)}
            className="w-full bg-gray-800 border border-gray-600 rounded px-2 py-1 text-sm" maxLength={4} />
        </div>
        <div>
          <label className="text-xs text-gray-500">描述</label>
          <input value={description} onChange={(e) => setDescription(e.target.value)}
            className="w-full bg-gray-800 border border-gray-600 rounded px-2 py-1 text-sm" />
        </div>
      </div>

      {/* Steps */}
      <div className="mb-4">
        <div className="flex justify-between items-center mb-2">
          <span className="text-sm font-medium">步骤列表</span>
          <button onClick={addStep} className="px-2 py-0.5 bg-gray-700 hover:bg-gray-600 rounded text-xs">+ 添加</button>
        </div>
        {steps.map((step, i) => (
          <div key={i} className="bg-gray-800 border border-gray-700 rounded p-3 mb-2">
            <div className="flex justify-between items-center mb-2">
              <span className="text-xs font-medium text-gray-400">步骤 {i + 1}</span>
              <button onClick={() => removeStep(i)} className="text-red-400 hover:text-red-300 text-xs">✕</button>
            </div>
            <div className="grid grid-cols-3 gap-2">
              <div>
                <label className="text-xs text-gray-600">类型</label>
                <select value={step.step_type} onChange={(e) => updateStep(i, { step_type: e.target.value })}
                  className="w-full bg-gray-700 border border-gray-600 rounded px-1 py-0.5 text-xs">
                  {STEP_TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
                </select>
              </div>
              <div>
                <label className="text-xs text-gray-600">延时 (ms)</label>
                <input type="number" value={step.delay_ms} onChange={(e) => updateStep(i, { delay_ms: +e.target.value })}
                  className="w-full bg-gray-700 border border-gray-600 rounded px-1 py-0.5 text-xs" />
              </div>
              <div>
                <label className="text-xs text-gray-600">错误处理</label>
                <select value={step.on_error} onChange={(e) => updateStep(i, { on_error: e.target.value as 'abort' | 'continue' })}
                  className="w-full bg-gray-700 border border-gray-600 rounded px-1 py-0.5 text-xs">
                  <option value="abort">中止</option>
                  <option value="continue">继续</option>
                </select>
              </div>
            </div>
            {/* Config fields */}
            <div className="mt-2">
              <label className="text-xs text-gray-600">参数 (key=value, 每行一个)</label>
              <textarea
                value={Object.entries(step.config).map(([k, v]) => `${k}=${v}`).join('\n')}
                onChange={(e) => {
                  const cfg: Record<string, unknown> = {};
                  e.target.value.split('\n').forEach((line) => {
                    const [k, ...rest] = line.split('=');
                    if (k) cfg[k.trim()] = rest.join('=').trim();
                  });
                  updateStep(i, { config: cfg });
                }}
                rows={3}
                className="w-full bg-gray-700 border border-gray-600 rounded px-2 py-1 text-xs font-mono"
                placeholder="gpio=5&#10;mode=1"
              />
            </div>
          </div>
        ))}
      </div>

      {/* JSON preview */}
      <details className="mb-4">
        <summary className="text-xs text-gray-500 cursor-pointer">JSON 预览</summary>
        <pre className="bg-gray-800 p-2 rounded text-xs text-gray-400 mt-1 overflow-auto max-h-40">
          {JSON.stringify({ name, slug: cmdSlug, description, icon, steps }, null, 2)}
        </pre>
      </details>

          <div className="flex gap-2">
            <button onClick={handleSave} className="px-4 py-2 bg-blue-600 hover:bg-blue-500 rounded text-sm">保存</button>
            <button onClick={onClose} className="px-4 py-2 bg-gray-700 hover:bg-gray-600 rounded text-sm">取消</button>
          </div>
        </div>
      </div>
    </div>
  );
}
