import { useState } from 'react';
import {
  Save,
  X,
  Sparkles,
  Loader2,
  ChevronDown,
  ChevronRight,
  AlertCircle
} from 'lucide-react';
import type { AgentDefinition } from '../../types';

interface AgentEditorProps {
  agent: AgentDefinition;
  onSave: (updates: Partial<AgentDefinition>) => void;
  onOptimize: (field: string, currentValue: string) => Promise<string>;
  onClose: () => void;
}

interface EditableSectionProps {
  title: string;
  children: React.ReactNode;
  defaultExpanded?: boolean;
}

function EditableSection({ title, children, defaultExpanded = true }: EditableSectionProps) {
  const [expanded, setExpanded] = useState(defaultExpanded);

  return (
    <div className="border border-slate-200 rounded-xl overflow-hidden mb-4">
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center justify-between px-4 py-3 bg-slate-50 hover:bg-slate-100 transition-colors"
      >
        <span className="font-medium text-slate-700">{title}</span>
        {expanded ? (
          <ChevronDown className="w-4 h-4 text-slate-400" />
        ) : (
          <ChevronRight className="w-4 h-4 text-slate-400" />
        )}
      </button>
      {expanded && (
        <div className="p-4 space-y-4">
          {children}
        </div>
      )}
    </div>
  );
}

interface OptimizableFieldProps {
  label: string;
  value: string;
  onChange: (value: string) => void;
  onOptimize: () => void;
  isOptimizing?: boolean;
  multiline?: boolean;
  rows?: number;
  placeholder?: string;
  hint?: string;
}

function OptimizableField({
  label,
  value,
  onChange,
  onOptimize,
  isOptimizing = false,
  multiline = true,
  rows = 3,
  placeholder,
  hint,
}: OptimizableFieldProps) {
  return (
    <div>
      <div className="flex items-center justify-between mb-1.5">
        <label className="text-sm font-medium text-slate-700">{label}</label>
        <button
          onClick={onOptimize}
          disabled={isOptimizing}
          className="flex items-center gap-1 px-2 py-1 text-xs text-purple-600 hover:bg-purple-50 rounded-lg transition-colors disabled:opacity-50"
          title="使用 LLM 优化"
        >
          {isOptimizing ? (
            <Loader2 className="w-3 h-3 animate-spin" />
          ) : (
            <Sparkles className="w-3 h-3" />
          )}
          <span>AI 优化</span>
        </button>
      </div>
      {multiline ? (
        <textarea
          value={value}
          onChange={(e) => onChange(e.target.value)}
          rows={rows}
          placeholder={placeholder}
          className="w-full p-3 text-sm border border-slate-200 rounded-lg resize-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500 transition-shadow"
        />
      ) : (
        <input
          type="text"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder={placeholder}
          className="w-full p-3 text-sm border border-slate-200 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 transition-shadow"
        />
      )}
      {hint && (
        <p className="text-xs text-slate-400 mt-1">{hint}</p>
      )}
    </div>
  );
}

export function AgentEditor({ agent, onSave, onOptimize, onClose }: AgentEditorProps) {
  // 编辑状态
  const [editedAgent, setEditedAgent] = useState<Partial<AgentDefinition>>({
    display_name: agent.display_name,
    description: agent.description,
    background_instruction: { ...agent.background_instruction },
    output_instruction: { ...agent.output_instruction },
    user_instruction: { ...agent.user_instruction },
    llm_config: { ...agent.llm_config },
  });

  const [optimizingField, setOptimizingField] = useState<string | null>(null);
  const [hasChanges, setHasChanges] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // 更新嵌套字段
  const updateField = (path: string, value: unknown) => {
    setHasChanges(true);
    setEditedAgent(prev => {
      const parts = path.split('.');
      const newState = { ...prev };

      let current: Record<string, unknown> = newState;
      for (let i = 0; i < parts.length - 1; i++) {
        if (!current[parts[i]]) {
          current[parts[i]] = {};
        }
        current[parts[i]] = { ...(current[parts[i]] as Record<string, unknown>) };
        current = current[parts[i]] as Record<string, unknown>;
      }
      current[parts[parts.length - 1]] = value;

      return newState;
    });
  };

  // 获取嵌套字段值
  const getField = (path: string): string => {
    const parts = path.split('.');
    let current: unknown = editedAgent;

    for (const part of parts) {
      if (current && typeof current === 'object' && part in current) {
        current = (current as Record<string, unknown>)[part];
      } else {
        return '';
      }
    }

    return current as string || '';
  };

  // 优化字段
  const handleOptimize = async (field: string) => {
    setOptimizingField(field);
    setError(null);

    try {
      const currentValue = getField(field);
      const optimizedValue = await onOptimize(field, currentValue);
      updateField(field, optimizedValue);
    } catch (err) {
      setError(`优化失败: ${err instanceof Error ? err.message : '未知错误'}`);
    } finally {
      setOptimizingField(null);
    }
  };

  // 保存
  const handleSave = () => {
    onSave(editedAgent);
    setHasChanges(false);
  };

  return (
    <div className="h-full flex flex-col bg-white">
      {/* 头部 */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-slate-200 flex-shrink-0">
        <div>
          <h3 className="font-semibold text-slate-800">编辑智能体</h3>
          <p className="text-xs text-slate-500 mt-0.5">{agent.name}</p>
        </div>
        <div className="flex items-center gap-2">
          {hasChanges && (
            <button
              onClick={handleSave}
              className="flex items-center gap-1.5 px-3 py-1.5 text-sm text-white bg-blue-500 hover:bg-blue-600 rounded-lg transition-colors"
            >
              <Save className="w-4 h-4" />
              <span>保存</span>
            </button>
          )}
          <button
            onClick={onClose}
            className="p-1.5 hover:bg-slate-100 rounded-lg transition-colors"
          >
            <X className="w-4 h-4 text-slate-500" />
          </button>
        </div>
      </div>

      {/* 错误提示 */}
      {error && (
        <div className="mx-4 mt-4 p-3 bg-red-50 border border-red-200 rounded-lg flex items-center gap-2 text-sm text-red-700">
          <AlertCircle className="w-4 h-4 flex-shrink-0" />
          <span>{error}</span>
        </div>
      )}

      {/* 编辑内容 */}
      <div className="flex-1 overflow-y-auto p-4">
        {/* 基本信息 */}
        <EditableSection title="基本信息">
          <div>
            <label className="text-sm font-medium text-slate-700 mb-1.5 block">显示名称</label>
            <input
              type="text"
              value={editedAgent.display_name || ''}
              onChange={(e) => updateField('display_name', e.target.value)}
              className="w-full p-3 text-sm border border-slate-200 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
              placeholder="用户友好的名称"
            />
          </div>
          <div>
            <label className="text-sm font-medium text-slate-700 mb-1.5 block">描述</label>
            <textarea
              value={editedAgent.description || ''}
              onChange={(e) => updateField('description', e.target.value)}
              rows={2}
              className="w-full p-3 text-sm border border-slate-200 rounded-lg resize-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
              placeholder="智能体的简要描述"
            />
          </div>
        </EditableSection>

        {/* Prompt 配置 */}
        <EditableSection title="Prompt 配置">
          <OptimizableField
            label="角色描述"
            value={getField('background_instruction.role_description')}
            onChange={(v) => updateField('background_instruction.role_description', v)}
            onOptimize={() => handleOptimize('background_instruction.role_description')}
            isOptimizing={optimizingField === 'background_instruction.role_description'}
            placeholder="描述智能体的角色定位..."
            hint="例如：你是一位资深的金融分析师，擅长..."
          />
          <OptimizableField
            label="核心能力"
            value={getField('background_instruction.core_capability')}
            onChange={(v) => updateField('background_instruction.core_capability', v)}
            onOptimize={() => handleOptimize('background_instruction.core_capability')}
            isOptimizing={optimizingField === 'background_instruction.core_capability'}
            placeholder="描述智能体的核心能力..."
            hint="明确智能体能够完成什么任务"
          />
          <OptimizableField
            label="任务上下文"
            value={getField('background_instruction.task_context')}
            onChange={(v) => updateField('background_instruction.task_context', v)}
            onOptimize={() => handleOptimize('background_instruction.task_context')}
            isOptimizing={optimizingField === 'background_instruction.task_context'}
            rows={4}
            placeholder="描述任务执行的上下文..."
            hint="提供任务执行需要的背景信息"
          />
        </EditableSection>

        {/* 输出配置 */}
        <EditableSection title="输出配置" defaultExpanded={false}>
          <div>
            <label className="text-sm font-medium text-slate-700 mb-1.5 block">输出格式</label>
            <select
              value={editedAgent.output_instruction?.format_type || 'json'}
              onChange={(e) => updateField('output_instruction.format_type', e.target.value)}
              className="w-full p-3 text-sm border border-slate-200 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
            >
              <option value="json">JSON</option>
              <option value="text">纯文本</option>
              <option value="markdown">Markdown</option>
              <option value="html">HTML</option>
            </select>
          </div>
        </EditableSection>

        {/* 模型配置 */}
        <EditableSection title="模型配置" defaultExpanded={false}>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="text-sm font-medium text-slate-700 mb-1.5 block">模型</label>
              <select
                value={editedAgent.llm_config?.model_name || 'deepseek/deepseek-v3'}
                onChange={(e) => updateField('llm_config.model_name', e.target.value)}
                className="w-full p-3 text-sm border border-slate-200 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
              >
                <option value="deepseek/deepseek-v3">DeepSeek V3</option>
                <option value="deepseek-r1">DeepSeek R1</option>
                <option value="qwen-plus">Qwen Plus</option>
                <option value="qwen-max">Qwen Max</option>
                <option value="glm-4-air">GLM 4 Air</option>
              </select>
            </div>
            <div>
              <label className="text-sm font-medium text-slate-700 mb-1.5 block">
                温度 ({editedAgent.llm_config?.temperature ?? 0.3})
              </label>
              <input
                type="range"
                min="0"
                max="1"
                step="0.1"
                value={editedAgent.llm_config?.temperature ?? 0.3}
                onChange={(e) => updateField('llm_config.temperature', parseFloat(e.target.value))}
                className="w-full"
              />
            </div>
            <div>
              <label className="text-sm font-medium text-slate-700 mb-1.5 block">最大 Tokens</label>
              <input
                type="number"
                value={editedAgent.llm_config?.max_tokens ?? 4096}
                onChange={(e) => updateField('llm_config.max_tokens', parseInt(e.target.value))}
                className="w-full p-3 text-sm border border-slate-200 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
              />
            </div>
            <div>
              <label className="text-sm font-medium text-slate-700 mb-1.5 block">最大迭代</label>
              <input
                type="number"
                value={editedAgent.llm_config?.max_iterations ?? 10}
                onChange={(e) => updateField('llm_config.max_iterations', parseInt(e.target.value))}
                className="w-full p-3 text-sm border border-slate-200 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
              />
            </div>
          </div>
        </EditableSection>
      </div>

      {/* 底部操作栏 */}
      {hasChanges && (
        <div className="flex-shrink-0 px-4 py-3 border-t border-slate-200 bg-slate-50 flex items-center justify-between">
          <span className="text-xs text-amber-600 flex items-center gap-1">
            <AlertCircle className="w-3 h-3" />
            有未保存的更改
          </span>
          <div className="flex items-center gap-2">
            <button
              onClick={() => {
                setEditedAgent({
                  display_name: agent.display_name,
                  description: agent.description,
                  background_instruction: { ...agent.background_instruction },
                  output_instruction: { ...agent.output_instruction },
                  user_instruction: { ...agent.user_instruction },
                  llm_config: { ...agent.llm_config },
                });
                setHasChanges(false);
              }}
              className="px-3 py-1.5 text-sm text-slate-600 hover:bg-slate-200 rounded-lg transition-colors"
            >
              重置
            </button>
            <button
              onClick={handleSave}
              className="px-3 py-1.5 text-sm text-white bg-blue-500 hover:bg-blue-600 rounded-lg transition-colors"
            >
              保存更改
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
