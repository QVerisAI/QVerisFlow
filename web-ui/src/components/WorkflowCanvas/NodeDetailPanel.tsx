import { useState } from 'react';
import { 
  X, 
  Bot, 
  Wrench, 
  Clock, 
  CheckCircle, 
  XCircle, 
  SkipForward,
  ChevronDown,
  ChevronUp,
  Cpu,
  FileText,
  Info,
  Sparkles,
  Edit3,
  Plus,
  Trash2,
  Save,
  Loader2,
  ToggleLeft,
  ToggleRight,
  Copy,
  Check
} from 'lucide-react';
import type { NodeInfo, AgentInfo, AgentDefinition, ToolInfo, ModelInfo, NodeExecutionResult } from '../../types';

interface NodeDetailPanelProps {
  node?: NodeInfo;
  agent?: AgentInfo;
  agentDefinition?: AgentDefinition;
  availableTools?: ToolInfo[];
  availableModels?: ModelInfo[];
  state?: { status: string; duration?: number };
  executionResult?: NodeExecutionResult;  // 执行结果（查看历史时）
  isHistoryMode?: boolean;  // 是否在查看历史模式
  onClose: () => void;
  onEdit?: (field: string, value: unknown) => void;
  onOptimize?: (field: string, currentValue: string) => void;
}

// 可折叠的配置卡片
function ConfigCard({ 
  title, 
  icon: Icon, 
  children, 
  defaultExpanded = false,
  badge,
}: { 
  title: string; 
  icon: React.ComponentType<{ className?: string }>;
  children: React.ReactNode;
  defaultExpanded?: boolean;
  badge?: React.ReactNode;
}) {
  const [expanded, setExpanded] = useState(defaultExpanded);
  
  return (
    <div className="bg-white rounded-2xl border border-slate-100 shadow-sm overflow-hidden">
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center justify-between px-5 py-4 hover:bg-slate-50/50 transition-colors"
      >
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-xl bg-gradient-to-br from-slate-50 to-slate-100 flex items-center justify-center">
            <Icon className="w-4 h-4 text-slate-600" />
          </div>
          <span className="text-[15px] font-medium text-slate-800">{title}</span>
          {badge}
        </div>
        {expanded ? (
          <ChevronUp className="w-4 h-4 text-slate-400" />
        ) : (
          <ChevronDown className="w-4 h-4 text-slate-400" />
        )}
      </button>
      <div className={`transition-all duration-200 ease-in-out ${
        expanded ? 'max-h-[2000px] opacity-100' : 'max-h-0 opacity-0 overflow-hidden'
      }`}>
        <div className="px-5 pb-5 pt-1">
          {children}
        </div>
      </div>
    </div>
  );
}

// 可展开的文本字段
function ExpandableTextField({
  label,
  value,
  editable = false,
  onEdit,
  onOptimize,
  optimizable = false,
  placeholder = '暂无内容',
}: {
  label: string;
  value: string;
  editable?: boolean;
  onEdit?: (value: string) => void;
  onOptimize?: () => void;
  optimizable?: boolean;
  placeholder?: string;
}) {
  const [isExpanded, setIsExpanded] = useState(false);
  const [isEditing, setIsEditing] = useState(false);
  const [editValue, setEditValue] = useState(value);
  const [isOptimizing, setIsOptimizing] = useState(false);
  
  const displayValue = value || placeholder;
  const isLongText = displayValue.length > 80;
  const showToggle = isLongText && !isEditing;
  
  const handleSave = () => {
    if (onEdit) {
      onEdit(editValue);
    }
    setIsEditing(false);
  };
  
  const handleOptimize = async () => {
    if (onOptimize) {
      setIsOptimizing(true);
      try {
        await onOptimize();
      } finally {
        setIsOptimizing(false);
      }
    }
  };
  
  return (
    <div className="group relative">
      {/* 标签行 */}
      <div className="flex items-center justify-between mb-2">
        <span className="text-xs font-medium text-slate-500 uppercase tracking-wide">{label}</span>
        <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
          {optimizable && onOptimize && (
            <button
              onClick={handleOptimize}
              disabled={isOptimizing}
              className="flex items-center gap-1 px-2 py-1 text-xs text-purple-600 hover:bg-purple-50 rounded-lg transition-colors"
              title="AI 优化"
            >
              <Sparkles className={`w-3 h-3 ${isOptimizing ? 'animate-pulse' : ''}`} />
              <span className="hidden sm:inline">优化</span>
            </button>
          )}
          {editable && !isEditing && (
            <button
              onClick={() => {
                setEditValue(value);
                setIsEditing(true);
              }}
              className="flex items-center gap-1 px-2 py-1 text-xs text-blue-600 hover:bg-blue-50 rounded-lg transition-colors"
              title="编辑"
            >
              <Edit3 className="w-3 h-3" />
              <span className="hidden sm:inline">编辑</span>
            </button>
          )}
        </div>
      </div>
      
      {/* 内容区 */}
      {isEditing ? (
        <div className="space-y-3">
          <textarea
            value={editValue}
            onChange={(e) => setEditValue(e.target.value)}
            className="w-full p-3 text-sm text-slate-700 bg-slate-50 border border-slate-200 rounded-xl resize-none focus:ring-2 focus:ring-blue-500 focus:border-transparent focus:bg-white transition-all"
            rows={5}
            autoFocus
          />
          <div className="flex justify-end gap-2">
            <button
              onClick={() => setIsEditing(false)}
              className="px-4 py-2 text-sm text-slate-600 hover:bg-slate-100 rounded-lg transition-colors"
            >
              取消
            </button>
            <button
              onClick={handleSave}
              className="px-4 py-2 text-sm text-white bg-blue-500 hover:bg-blue-600 rounded-lg transition-colors flex items-center gap-1"
            >
              <Check className="w-3.5 h-3.5" />
              保存
            </button>
          </div>
        </div>
      ) : (
        <div className="relative">
          <div 
            className={`text-sm text-slate-700 leading-relaxed whitespace-pre-wrap ${
              !isExpanded && isLongText ? 'line-clamp-3' : ''
            } ${!value ? 'text-slate-400 italic' : ''}`}
          >
            {displayValue}
          </div>
          {showToggle && (
            <button
              onClick={() => setIsExpanded(!isExpanded)}
              className="mt-2 text-xs text-blue-500 hover:text-blue-600 font-medium"
            >
              {isExpanded ? '收起' : '展开全部'}
            </button>
          )}
          {/* 可编辑提示 */}
          {editable && !isEditing && (
            <div className="absolute -right-1 -top-1 w-2 h-2 bg-blue-400 rounded-full opacity-0 group-hover:opacity-100 transition-opacity" 
                 title="可编辑" />
          )}
        </div>
      )}
    </div>
  );
}

// 分隔线
function Divider() {
  return <div className="h-px bg-slate-100 my-4" />;
}

// 复制按钮
function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  
  const handleCopy = async () => {
    await navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };
  
  return (
    <button
      onClick={handleCopy}
      className="p-1 text-slate-400 hover:text-slate-600 transition-colors"
      title="复制"
    >
      {copied ? <Check className="w-3 h-3 text-green-500" /> : <Copy className="w-3 h-3" />}
    </button>
  );
}

// 执行结果面板
function ExecutionResultPanel({ result }: { result?: import('../../types').NodeExecutionResult }) {
  const [showInput, setShowInput] = useState(false);
  const [showOutput, setShowOutput] = useState(true);
  
  if (!result) {
    return (
      <div className="flex flex-col items-center justify-center py-12 text-slate-400">
        <Clock className="w-12 h-12 mb-3 opacity-40" />
        <p className="text-sm">暂无执行记录</p>
        <p className="text-xs mt-1">执行工作流后可查看结果</p>
      </div>
    );
  }
  
  const statusConfig: Record<string, { label: string; color: string; icon: React.ComponentType<{ className?: string }> }> = {
    success: { label: '成功', color: 'text-emerald-600 bg-emerald-50', icon: CheckCircle },
    failed: { label: '失败', color: 'text-red-600 bg-red-50', icon: XCircle },
    skipped: { label: '跳过', color: 'text-amber-600 bg-amber-50', icon: SkipForward },
    running: { label: '运行中', color: 'text-blue-600 bg-blue-50', icon: Loader2 },
    pending: { label: '等待', color: 'text-slate-500 bg-slate-50', icon: Clock },
  };
  
  const status = statusConfig[result.status] || statusConfig.pending;
  const StatusIcon = status.icon;
  
  const formatJson = (obj: unknown) => {
    try {
      return JSON.stringify(obj, null, 2);
    } catch {
      return String(obj);
    }
  };
  
  const formatTime = (dateStr?: string) => {
    if (!dateStr) return '-';
    const date = new Date(dateStr);
    return date.toLocaleString('zh-CN', {
      month: 'numeric',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
    });
  };
  
  return (
    <div className="space-y-4">
      {/* 执行状态卡片 */}
      <div className="bg-white rounded-2xl border border-slate-100 p-5">
        <div className="flex items-center justify-between mb-4">
          <span className="text-sm font-medium text-slate-600">执行状态</span>
          <span className={`inline-flex items-center gap-1.5 px-3 py-1 text-xs font-medium rounded-full ${status.color}`}>
            <StatusIcon className={`w-3.5 h-3.5 ${result.status === 'running' ? 'animate-spin' : ''}`} />
            {status.label}
          </span>
        </div>
        
        <div className="grid grid-cols-2 gap-4">
          <div>
            <p className="text-xs text-slate-400 mb-1">开始时间</p>
            <p className="text-sm text-slate-700">{formatTime(result.startedAt)}</p>
          </div>
          <div>
            <p className="text-xs text-slate-400 mb-1">完成时间</p>
            <p className="text-sm text-slate-700">{formatTime(result.completedAt)}</p>
          </div>
          <div>
            <p className="text-xs text-slate-400 mb-1">耗时</p>
            <p className="text-sm text-slate-700">
              {result.durationMs ? `${(result.durationMs / 1000).toFixed(2)}s` : '-'}
            </p>
          </div>
          <div>
            <p className="text-xs text-slate-400 mb-1">节点 ID</p>
            <p className="text-sm text-slate-700 font-mono truncate" title={result.nodeId}>
              {result.nodeId}
            </p>
          </div>
        </div>
        
        {result.error && (
          <div className="mt-4 p-3 bg-red-50 rounded-xl">
            <p className="text-xs font-medium text-red-600 mb-1">错误信息</p>
            <p className="text-sm text-red-700">{result.error}</p>
          </div>
        )}
      </div>
      
      {/* 输入 */}
      {result.input !== undefined && (
        <div className="bg-white rounded-2xl border border-slate-100 overflow-hidden">
          <button
            onClick={() => setShowInput(!showInput)}
            className="w-full flex items-center justify-between px-5 py-4 hover:bg-slate-50/50 transition-colors"
          >
            <div className="flex items-center gap-3">
              <div className="w-8 h-8 rounded-xl bg-gradient-to-br from-blue-50 to-blue-100 flex items-center justify-center">
                <FileText className="w-4 h-4 text-blue-600" />
              </div>
              <span className="text-[15px] font-medium text-slate-800">输入数据</span>
            </div>
            {showInput ? (
              <ChevronUp className="w-4 h-4 text-slate-400" />
            ) : (
              <ChevronDown className="w-4 h-4 text-slate-400" />
            )}
          </button>
          {showInput && (
            <div className="px-5 pb-5">
              <pre className="p-4 bg-slate-50 rounded-xl text-xs font-mono text-slate-700 overflow-x-auto max-h-64 overflow-y-auto">
                {formatJson(result.input)}
              </pre>
            </div>
          )}
        </div>
      )}
      
      {/* 输出 */}
      {result.output !== undefined && (
        <div className="bg-white rounded-2xl border border-slate-100 overflow-hidden">
          <button
            onClick={() => setShowOutput(!showOutput)}
            className="w-full flex items-center justify-between px-5 py-4 hover:bg-slate-50/50 transition-colors"
          >
            <div className="flex items-center gap-3">
              <div className="w-8 h-8 rounded-xl bg-gradient-to-br from-emerald-50 to-emerald-100 flex items-center justify-center">
                <CheckCircle className="w-4 h-4 text-emerald-600" />
              </div>
              <span className="text-[15px] font-medium text-slate-800">输出结果</span>
            </div>
            {showOutput ? (
              <ChevronUp className="w-4 h-4 text-slate-400" />
            ) : (
              <ChevronDown className="w-4 h-4 text-slate-400" />
            )}
          </button>
          {showOutput && (
            <div className="px-5 pb-5">
              <pre className="p-4 bg-slate-50 rounded-xl text-xs font-mono text-slate-700 overflow-x-auto max-h-96 overflow-y-auto">
                {formatJson(result.output)}
              </pre>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export function NodeDetailPanel({ 
  node, 
  agent, 
  agentDefinition,
  availableTools = [],
  availableModels = [],
  state, 
  executionResult,
  isHistoryMode = false,
  onClose,
  onEdit,
  onOptimize,
}: NodeDetailPanelProps) {
  // 本地编辑状态
  const [pendingChanges, setPendingChanges] = useState<Record<string, unknown>>({});
  const [isSaving, setIsSaving] = useState(false);
  const [showAddTool, setShowAddTool] = useState(false);
  // Tab 状态
  const [activeTab, setActiveTab] = useState<'config' | 'result'>(isHistoryMode ? 'result' : 'config');
  
  if (!node) return null;

  const status = state?.status || node.status || 'pending';
  const duration = state?.duration;
  const def = agentDefinition;
  
  // 检查是否有待保存的更改
  const hasChanges = Object.keys(pendingChanges).length > 0;
  
  // 保存所有更改
  const handleSaveAll = async () => {
    if (!onEdit || !hasChanges) return;
    setIsSaving(true);
    try {
      for (const [field, value] of Object.entries(pendingChanges)) {
        onEdit(field, value);
      }
      setPendingChanges({});
    } finally {
      setIsSaving(false);
    }
  };
  
  // 更新本地更改
  const updatePendingChange = (field: string, value: unknown) => {
    setPendingChanges(prev => ({ ...prev, [field]: value }));
  };
  
  // 获取字段值
  const getFieldValue = <T,>(field: string, defaultValue: T): T => {
    if (field in pendingChanges) {
      return pendingChanges[field] as T;
    }
    const parts = field.split('.');
    let value: unknown = def;
    for (const part of parts) {
      if (value && typeof value === 'object') {
        value = (value as Record<string, unknown>)[part];
      } else {
        return defaultValue;
      }
    }
    return (value as T) ?? defaultValue;
  };

  // 状态映射
  const statusConfig: Record<string, { label: string; color: string; icon: React.ComponentType<{ className?: string }> }> = {
    completed: { label: '已完成', color: 'bg-emerald-50 text-emerald-600 border-emerald-100', icon: CheckCircle },
    failed: { label: '失败', color: 'bg-red-50 text-red-600 border-red-100', icon: XCircle },
    running: { label: '运行中', color: 'bg-blue-50 text-blue-600 border-blue-100', icon: Clock },
    skipped: { label: '已跳过', color: 'bg-amber-50 text-amber-600 border-amber-100', icon: SkipForward },
    pending: { label: '等待中', color: 'bg-slate-50 text-slate-500 border-slate-100', icon: Clock },
    preview: { label: '预览', color: 'bg-violet-50 text-violet-600 border-violet-100', icon: Clock },
  };

  const currentStatus = statusConfig[status] || statusConfig.pending;
  const StatusIcon = currentStatus.icon;

  return (
    <div className="w-[420px] border-l border-slate-200 bg-slate-50 overflow-hidden flex flex-col h-full">
      {/* 头部 */}
      <div className="px-6 py-5 bg-white border-b border-slate-100 flex-shrink-0">
        <div className="flex items-start justify-between">
          <div className="flex-1 min-w-0 pr-4">
            {/* Agent 名称 */}
            <h2 className="text-lg font-semibold text-slate-800 truncate">
              {def?.display_name || node.displayName || node.name}
            </h2>
            {/* Agent ID */}
            <div className="mt-1 text-xs text-slate-400 font-mono truncate">
              {def?.agent_id || node.agentId || node.nodeId}
            </div>
            {/* 状态和版本 */}
            <div className="flex items-center gap-2 mt-2">
              <span className={`inline-flex items-center gap-1 px-2.5 py-1 text-xs font-medium rounded-full border ${currentStatus.color}`}>
                <StatusIcon className="w-3 h-3" />
                {currentStatus.label}
              </span>
              {def?.version && (
                <span className="px-2 py-1 text-xs font-mono text-slate-500 bg-slate-100 rounded-full">
                  v{def.version}
                </span>
              )}
              {duration !== undefined && (
                <span className="text-xs text-slate-400">
                  耗时 {(duration / 1000).toFixed(1)}s
                </span>
              )}
            </div>
          </div>
          <button
            onClick={onClose}
            className="p-2 hover:bg-slate-100 rounded-xl transition-colors flex-shrink-0"
          >
            <X className="w-5 h-5 text-slate-400" />
          </button>
        </div>
        
        {/* 描述 */}
        {(def?.description || node.description) && (
          <p className="mt-3 text-sm text-slate-600 leading-relaxed">
            {def?.description || node.description}
          </p>
        )}
      </div>

      {/* Tab 切换 - 仅在历史模式或有执行结果时显示 */}
      {(isHistoryMode || executionResult) && (
        <div className="px-4 pt-4 pb-2 bg-white border-b border-slate-100 flex gap-2">
          <button
            onClick={() => setActiveTab('config')}
            className={`px-4 py-2 text-sm font-medium rounded-lg transition-colors ${
              activeTab === 'config'
                ? 'bg-blue-50 text-blue-700'
                : 'text-slate-500 hover:bg-slate-50'
            }`}
          >
            配置
          </button>
          <button
            onClick={() => setActiveTab('result')}
            className={`px-4 py-2 text-sm font-medium rounded-lg transition-colors ${
              activeTab === 'result'
                ? 'bg-blue-50 text-blue-700'
                : 'text-slate-500 hover:bg-slate-50'
            }`}
          >
            执行结果
          </button>
        </div>
      )}

      {/* 内容区 */}
      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {/* 执行结果 Tab */}
        {activeTab === 'result' && (isHistoryMode || executionResult) && (
          <ExecutionResultPanel result={executionResult} />
        )}

        {/* 配置 Tab */}
        {activeTab === 'config' && def && (
          <>
            {/* Prompt 配置 */}
            <ConfigCard 
              title="提示词配置" 
              icon={FileText} 
              defaultExpanded={true}
              badge={
                !isHistoryMode && (
                  <span className="ml-2 px-2 py-0.5 text-[10px] font-medium text-purple-600 bg-purple-50 rounded-full">
                    可编辑
                  </span>
                )
              }
            >
              <div className="space-y-6">
                <ExpandableTextField
                  label="角色描述"
                  value={def.background_instruction?.role_description || ''}
                  editable={!!onEdit}
                  onEdit={(v) => onEdit?.('background_instruction.role_description', v)}
                  onOptimize={() => onOptimize?.('role_description', def.background_instruction?.role_description || '')}
                  optimizable
                  placeholder="定义 Agent 的角色身份..."
                />
                
                <Divider />
                
                <ExpandableTextField
                  label="核心能力"
                  value={def.background_instruction?.core_capability || ''}
                  editable={!!onEdit}
                  onEdit={(v) => onEdit?.('background_instruction.core_capability', v)}
                  onOptimize={() => onOptimize?.('core_capability', def.background_instruction?.core_capability || '')}
                  optimizable
                  placeholder="描述 Agent 的核心能力..."
                />
                
                <Divider />
                
                <ExpandableTextField
                  label="任务上下文"
                  value={def.background_instruction?.task_context || ''}
                  editable={!!onEdit}
                  onEdit={(v) => onEdit?.('background_instruction.task_context', v)}
                  onOptimize={() => onOptimize?.('task_context', def.background_instruction?.task_context || '')}
                  optimizable
                  placeholder="描述任务执行的背景信息..."
                />
              </div>
            </ConfigCard>

            {/* 输出配置 */}
            <ConfigCard title="输出配置" icon={FileText}>
              <div className="space-y-4">
                <div className="flex items-center justify-between">
                  <span className="text-xs font-medium text-slate-500 uppercase tracking-wide">输出格式</span>
                  <span className="px-3 py-1 text-xs font-medium text-emerald-600 bg-emerald-50 rounded-full">
                    {def.output_instruction?.format_type || 'json'}
                  </span>
                </div>
                
                {def.output_instruction?.format_requirements?.length ? (
                  <>
                    <Divider />
                    <div>
                      <span className="text-xs font-medium text-slate-500 uppercase tracking-wide block mb-2">格式要求</span>
                      <div className="flex flex-wrap gap-2">
                        {def.output_instruction.format_requirements.map((req, i) => (
                          <span key={i} className="px-2.5 py-1 text-xs text-slate-600 bg-slate-100 rounded-lg">
                            {req}
                          </span>
                        ))}
                      </div>
                    </div>
                  </>
                ) : null}
                
                {def.output_instruction?.quality_standards?.length ? (
                  <>
                    <Divider />
                    <div>
                      <span className="text-xs font-medium text-slate-500 uppercase tracking-wide block mb-2">质量标准</span>
                      <div className="flex flex-wrap gap-2">
                        {def.output_instruction.quality_standards.map((std, i) => (
                          <span key={i} className="px-2.5 py-1 text-xs text-blue-600 bg-blue-50 rounded-lg">
                            {std}
                          </span>
                        ))}
                      </div>
                    </div>
                  </>
                ) : null}
              </div>
            </ConfigCard>

            {/* 模型配置 */}
            <ConfigCard title="模型配置" icon={Cpu} defaultExpanded>
              <div className="space-y-5">
                {/* 模型选择 */}
                <div>
                  <label className="text-xs font-medium text-slate-500 uppercase tracking-wide block mb-2">模型</label>
                  <select
                    value={getFieldValue('llm_config.model_name', def.llm_config?.model_name || '')}
                    onChange={(e) => updatePendingChange('llm_config.model_name', e.target.value)}
                    className="w-full px-4 py-2.5 text-sm text-slate-700 bg-white border border-slate-200 rounded-xl focus:ring-2 focus:ring-blue-500 focus:border-transparent transition-all cursor-pointer appearance-none"
                    style={{ backgroundImage: `url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' fill='none' viewBox='0 0 20 20'%3E%3Cpath stroke='%236b7280' stroke-linecap='round' stroke-linejoin='round' stroke-width='1.5' d='m6 8 4 4 4-4'/%3E%3C/svg%3E")`, backgroundPosition: 'right 0.75rem center', backgroundRepeat: 'no-repeat', backgroundSize: '1.25rem' }}
                  >
                    {availableModels.length > 0 ? (
                      availableModels.map(model => (
                        <option key={model.value} value={model.value}>
                          {model.label}
                          {model.costTier && ` (${model.costTier === 'low' ? '低成本' : model.costTier === 'high' ? '高性能' : '标准'})`}
                        </option>
                      ))
                    ) : (
                      // 如果没有配置的模型列表，显示当前模型
                      <option value={def.llm_config?.model_name || ''}>
                        {def.llm_config?.model_name || '未配置'}
                      </option>
                    )}
                  </select>
                </div>
                
                {/* 温度 */}
                <div>
                  <div className="flex items-center justify-between mb-2">
                    <label className="text-xs font-medium text-slate-500 uppercase tracking-wide">温度</label>
                    <span className="text-sm font-semibold text-amber-600 tabular-nums">
                      {getFieldValue('llm_config.temperature', def.llm_config?.temperature ?? 0.3)}
                    </span>
                  </div>
                  <div className="relative pt-1">
                    <input
                      type="range"
                      min="0"
                      max="1"
                      step="0.1"
                      value={getFieldValue('llm_config.temperature', def.llm_config?.temperature ?? 0.3)}
                      onChange={(e) => updatePendingChange('llm_config.temperature', parseFloat(e.target.value))}
                      className="w-full h-2 bg-gradient-to-r from-blue-200 via-amber-200 to-red-200 rounded-full appearance-none cursor-pointer [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:w-5 [&::-webkit-slider-thumb]:h-5 [&::-webkit-slider-thumb]:rounded-full [&::-webkit-slider-thumb]:bg-white [&::-webkit-slider-thumb]:border-2 [&::-webkit-slider-thumb]:border-amber-400 [&::-webkit-slider-thumb]:shadow-md [&::-webkit-slider-thumb]:cursor-pointer"
                    />
                    <div className="flex justify-between text-[10px] text-slate-400 mt-1">
                      <span>精确</span>
                      <span>创意</span>
                    </div>
                  </div>
                </div>
                
                {/* 参数网格 */}
                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <label className="text-xs font-medium text-slate-500 uppercase tracking-wide block mb-2">最大 Tokens</label>
                    <input
                      type="number"
                      value={getFieldValue('llm_config.max_tokens', def.llm_config?.max_tokens || 4096)}
                      onChange={(e) => updatePendingChange('llm_config.max_tokens', parseInt(e.target.value) || 4096)}
                      className="w-full px-4 py-2.5 text-sm text-slate-700 bg-white border border-slate-200 rounded-xl focus:ring-2 focus:ring-blue-500 focus:border-transparent transition-all tabular-nums"
                      min="256"
                      max="128000"
                      step="256"
                    />
                  </div>
                  <div>
                    <label className="text-xs font-medium text-slate-500 uppercase tracking-wide block mb-2">最大迭代</label>
                    <input
                      type="number"
                      value={getFieldValue('llm_config.max_iterations', def.llm_config?.max_iterations || 10)}
                      onChange={(e) => updatePendingChange('llm_config.max_iterations', parseInt(e.target.value) || 10)}
                      className="w-full px-4 py-2.5 text-sm text-slate-700 bg-white border border-slate-200 rounded-xl focus:ring-2 focus:ring-blue-500 focus:border-transparent transition-all tabular-nums"
                      min="1"
                      max="50"
                    />
                  </div>
                </div>
              </div>
            </ConfigCard>

            {/* 工具配置 */}
            <ConfigCard 
              title="工具配置" 
              icon={Wrench} 
              defaultExpanded
              badge={
                (getFieldValue('tool_references', def.tool_references) || []).length > 0 && (
                  <span className="ml-2 px-2 py-0.5 text-[10px] font-medium text-blue-600 bg-blue-50 rounded-full">
                    {(getFieldValue('tool_references', def.tool_references) || []).filter((t: { enabled: boolean }) => t.enabled).length} 个已启用
                  </span>
                )
              }
            >
              <div className="space-y-3">
                {/* 工具列表 */}
                {(getFieldValue('tool_references', def.tool_references) || []).map((tool: { tool_id: string; alias?: string; tool_type?: string; enabled: boolean }, i: number) => (
                  <div 
                    key={i} 
                    className={`flex items-center justify-between p-3 rounded-xl transition-all ${
                      tool.enabled 
                        ? 'bg-white border border-slate-200 shadow-sm' 
                        : 'bg-slate-100 border border-transparent opacity-60'
                    }`}
                  >
                    <div className="flex-1 min-w-0">
                      <span className="text-sm font-medium text-slate-700 block truncate">
                        {tool.alias || tool.tool_id}
                      </span>
                      {tool.tool_type && (
                        <span className="text-[11px] text-slate-400">
                          {tool.tool_type === 'qveris' ? '搜索工具' : 
                           tool.tool_type === 'builtin' ? '内置工具' : tool.tool_type}
                        </span>
                      )}
                    </div>
                    <div className="flex items-center gap-2 ml-3">
                      {/* 启用/禁用切换 */}
                      <button
                        onClick={() => {
                          const tools = [...(getFieldValue('tool_references', def.tool_references) || [])];
                          tools[i] = { ...tools[i], enabled: !tools[i].enabled };
                          updatePendingChange('tool_references', tools);
                        }}
                        className="text-slate-400 hover:text-slate-600 transition-colors"
                        title={tool.enabled ? '点击禁用' : '点击启用'}
                      >
                        {tool.enabled ? (
                          <ToggleRight className="w-6 h-6 text-emerald-500" />
                        ) : (
                          <ToggleLeft className="w-6 h-6" />
                        )}
                      </button>
                      {/* 删除按钮 */}
                      <button
                        onClick={() => {
                          const tools = (getFieldValue('tool_references', def.tool_references) || []).filter((_: unknown, idx: number) => idx !== i);
                          updatePendingChange('tool_references', tools);
                        }}
                        className="p-1.5 text-slate-400 hover:text-red-500 hover:bg-red-50 rounded-lg transition-colors"
                        title="移除工具"
                      >
                        <Trash2 className="w-4 h-4" />
                      </button>
                    </div>
                  </div>
                ))}
                
                {/* 添加工具 */}
                {showAddTool ? (
                  <div className="p-4 bg-blue-50 border-2 border-dashed border-blue-200 rounded-xl">
                    <label className="text-xs font-medium text-slate-500 uppercase tracking-wide block mb-2">选择工具</label>
                    <select
                      className="w-full px-4 py-2.5 text-sm bg-white border border-slate-200 rounded-xl focus:ring-2 focus:ring-blue-500"
                      onChange={(e) => {
                        if (e.target.value) {
                          const selectedTool = availableTools.find(t => t.tool_id === e.target.value);
                          if (selectedTool) {
                            const tools = [...(getFieldValue('tool_references', def.tool_references) || [])];
                            if (!tools.some((t: { tool_id: string }) => t.tool_id === selectedTool.tool_id)) {
                              tools.push({
                                tool_id: selectedTool.tool_id,
                                alias: selectedTool.alias || selectedTool.name,
                                tool_type: selectedTool.tool_type,
                                enabled: true,
                              });
                              updatePendingChange('tool_references', tools);
                            }
                          }
                          setShowAddTool(false);
                        }
                      }}
                      defaultValue=""
                    >
                      <option value="" disabled>选择要添加的工具...</option>
                      {availableTools
                        .filter(t => !(getFieldValue('tool_references', def.tool_references) || []).some(
                          (existing: { tool_id: string }) => existing.tool_id === t.tool_id
                        ))
                        .map(tool => (
                          <option key={tool.tool_id} value={tool.tool_id}>
                            {tool.name || tool.tool_id}
                          </option>
                        ))
                      }
                    </select>
                    <button
                      onClick={() => setShowAddTool(false)}
                      className="mt-3 text-xs text-slate-500 hover:text-slate-700"
                    >
                      取消
                    </button>
                  </div>
                ) : (
                  <button
                    onClick={() => setShowAddTool(true)}
                    className="w-full flex items-center justify-center gap-2 p-3 border-2 border-dashed border-slate-200 rounded-xl text-slate-500 hover:text-blue-600 hover:border-blue-300 hover:bg-blue-50/50 transition-all"
                  >
                    <Plus className="w-4 h-4" />
                    <span className="text-sm font-medium">添加工具</span>
                  </button>
                )}
              </div>
            </ConfigCard>

            {/* 元信息 - 折叠显示 */}
            <ConfigCard title="元信息" icon={Info}>
              <div className="space-y-3">
                <div className="flex items-center justify-between">
                  <span className="text-xs font-medium text-slate-500">Agent ID</span>
                  <div className="flex items-center gap-1">
                    <span className="text-xs font-mono text-slate-600 truncate max-w-[180px]">{def.agent_id}</span>
                    <CopyButton text={def.agent_id} />
                  </div>
                </div>
                <Divider />
                <div className="flex items-center justify-between">
                  <span className="text-xs font-medium text-slate-500">作者</span>
                  <span className="text-xs text-slate-600">{def.author || '系统'}</span>
                </div>
                {def.created_at && (
                  <>
                    <Divider />
                    <div className="flex items-center justify-between">
                      <span className="text-xs font-medium text-slate-500">创建时间</span>
                      <span className="text-xs text-slate-600">{def.created_at}</span>
                    </div>
                  </>
                )}
                {def.tags?.length ? (
                  <>
                    <Divider />
                    <div>
                      <span className="text-xs font-medium text-slate-500 block mb-2">标签</span>
                      <div className="flex flex-wrap gap-1.5">
                        {def.tags.map((tag, i) => (
                          <span key={i} className="px-2 py-0.5 text-[11px] text-slate-500 bg-slate-100 rounded">
                            {tag}
                          </span>
                        ))}
                      </div>
                    </div>
                  </>
                ) : null}
              </div>
            </ConfigCard>
          </>
        )}

        {/* 配置 Tab - 简单信息（没有完整定义时） */}
        {activeTab === 'config' && !def && agent && (
          <ConfigCard title="Agent 信息" icon={Bot} defaultExpanded>
            {agent.description && (
              <p className="text-sm text-slate-700 leading-relaxed">{agent.description}</p>
            )}
            <div className="flex flex-wrap gap-2 mt-4">
              {agent.domainType && (
                <span className="px-3 py-1 text-xs font-medium text-blue-600 bg-blue-50 rounded-full">
                  {agent.domainType}
                </span>
              )}
              {agent.executionType && (
                <span className="px-3 py-1 text-xs font-medium text-emerald-600 bg-emerald-50 rounded-full">
                  {agent.executionType}
                </span>
              )}
            </div>
            {agent.tools?.length ? (
              <div className="mt-4">
                <span className="text-xs font-medium text-slate-500 block mb-2">工具</span>
                <div className="flex flex-wrap gap-1.5">
                  {agent.tools.map((tool, i) => (
                    <span key={i} className="px-2 py-0.5 text-[11px] text-slate-600 bg-slate-100 rounded">
                      {tool}
                    </span>
                  ))}
                </div>
              </div>
            ) : null}
          </ConfigCard>
        )}
      </div>
      
      {/* 保存按钮 - 固定在底部（仅在非历史模式下显示） */}
      {def && hasChanges && !isHistoryMode && (
        <div className="p-4 bg-white border-t border-slate-200 flex-shrink-0">
          <div className="flex items-center justify-between mb-3">
            <div className="flex items-center gap-2">
              <span className="text-xs text-slate-500">版本</span>
              <span className="text-xs font-mono text-slate-600">v{def.version}</span>
              <span className="text-slate-300">→</span>
              <span className="text-xs font-mono text-blue-600 font-semibold">
                v{(() => {
                  try {
                    const parts = def.version.split('.');
                    parts[parts.length - 1] = String(parseInt(parts[parts.length - 1]) + 1);
                    return parts.join('.');
                  } catch {
                    return '1.0.1';
                  }
                })()}
              </span>
            </div>
            <span className="px-2 py-0.5 text-[11px] font-medium text-amber-600 bg-amber-50 rounded-full">
              {Object.keys(pendingChanges).length} 项更改
            </span>
          </div>
          <button
            onClick={handleSaveAll}
            disabled={isSaving}
            className="w-full flex items-center justify-center gap-2 px-4 py-3 bg-gradient-to-r from-blue-500 to-blue-600 text-white text-sm font-medium rounded-xl hover:from-blue-600 hover:to-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-all shadow-sm"
          >
            {isSaving ? (
              <Loader2 className="w-4 h-4 animate-spin" />
            ) : (
              <Save className="w-4 h-4" />
            )}
            <span>{isSaving ? '保存中...' : '保存更改'}</span>
          </button>
        </div>
      )}
    </div>
  );
}
