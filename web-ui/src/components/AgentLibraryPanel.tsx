import React, { useEffect, useState } from 'react';
import {
  X,
  Search,
  Bot,
  Star,
  Wrench,
  Activity,
  Filter,
  Cpu,
  Database,
  Microscope,
  DollarSign,
  Heart,
  Loader2,
  Sparkles,
  Workflow,
  FileText,
  Shield,
  AlertTriangle,
  BarChart3,
  Zap,
} from 'lucide-react';
import { useAppStore } from '../stores/appStore';
import { wsService } from '../services/websocket';
import { WSMessageType, type AgentLibraryItem } from '../types';

interface AgentLibraryPanelProps {
  onClose: () => void;
}

type TabType = 'all' | 'templates';

export const AgentLibraryPanel: React.FC<AgentLibraryPanelProps> = ({ onClose }) => {
  const [activeTab, setActiveTab] = useState<TabType>('all');
  const [searchQuery, setSearchQuery] = useState('');
  const [domainFilter, setDomainFilter] = useState<string>('');

  const {
    agentLibrary,
    agentTemplates,
    agentLibraryLoading,
    setAgentLibraryLoading,
  } = useAppStore();

  // 加载智能体列表
  useEffect(() => {
    setAgentLibraryLoading(true);
    wsService.send(WSMessageType.LIST_AGENTS, {});
    wsService.send(WSMessageType.GET_AGENT_TEMPLATES, {});
  }, [setAgentLibraryLoading]);

  const handleReuseAgent = (agent: AgentLibraryItem) => {
    wsService.send(WSMessageType.REUSE_AGENT, {
      agent_id: agent.agentId,
    });
    onClose();
  };

  const filteredAgents = (activeTab === 'templates' ? agentTemplates : agentLibrary)
    .filter(agent => {
      if (searchQuery) {
        const query = searchQuery.toLowerCase();
        if (!agent.name.toLowerCase().includes(query) &&
          !agent.displayName.toLowerCase().includes(query) &&
          !agent.description.toLowerCase().includes(query)) {
          return false;
        }
      }
      if (domainFilter && agent.domainType !== domainFilter) {
        return false;
      }
      return true;
    });

  const uniqueDomains = Array.from(new Set(agentLibrary.map(a => a.domainType)));

  const getDomainIcon = (domain: string) => {
    const iconMap: Record<string, React.ComponentType<{ className?: string }>> = {
      // 新版后端枚举
      financial_analysis: BarChart3,
      data_integration: Database,
      data_verification: Shield,
      risk_assessment: AlertTriangle,
      signal_detection: Zap,
      report_generation: FileText,
      // 旧版/通用枚举
      finance: DollarSign,
      healthcare: Heart,
      research: Microscope,
      data: Database,
      general: Bot,
    };
    return iconMap[domain] || Wrench;
  };

  const getDomainColor = (domain: string) => {
    const colorMap: Record<string, { bg: string; icon: string; text: string }> = {
      // 新版后端枚举
      financial_analysis: { bg: 'bg-amber-50', icon: 'text-amber-500', text: 'text-amber-700' },
      data_integration: { bg: 'bg-indigo-50', icon: 'text-indigo-500', text: 'text-indigo-700' },
      data_verification: { bg: 'bg-emerald-50', icon: 'text-emerald-500', text: 'text-emerald-700' },
      risk_assessment: { bg: 'bg-orange-50', icon: 'text-orange-500', text: 'text-orange-700' },
      signal_detection: { bg: 'bg-yellow-50', icon: 'text-yellow-500', text: 'text-yellow-700' },
      report_generation: { bg: 'bg-purple-50', icon: 'text-purple-500', text: 'text-purple-700' },
      // 旧版/通用枚举
      finance: { bg: 'bg-amber-50', icon: 'text-amber-500', text: 'text-amber-700' },
      healthcare: { bg: 'bg-rose-50', icon: 'text-rose-500', text: 'text-rose-700' },
      research: { bg: 'bg-cyan-50', icon: 'text-cyan-500', text: 'text-cyan-700' },
      data: { bg: 'bg-indigo-50', icon: 'text-indigo-500', text: 'text-indigo-700' },
      general: { bg: 'bg-blue-50', icon: 'text-blue-500', text: 'text-blue-700' },
    };
    return colorMap[domain] || { bg: 'bg-slate-50', icon: 'text-slate-500', text: 'text-slate-700' };
  };

  const getDomainLabel = (domain: string) => {
    const labelMap: Record<string, string> = {
      // 新版后端枚举
      financial_analysis: '金融分析',
      data_integration: '数据集成',
      data_verification: '数据验证',
      risk_assessment: '风险评估',
      signal_detection: '信号检测',
      report_generation: '报告生成',
      // 旧版/通用枚举
      finance: '金融',
      healthcare: '医疗',
      research: '研究',
      data: '数据',
      general: '通用',
    };
    return labelMap[domain] || domain;
  };

  const getExecutionTypeLabel = (type: string) => {
    const labelMap: Record<string, string> = {
      reasoning_executor: '推理执行',
      executor: '快速执行',
      deep_search: '深度搜索',
      flow_agent: '流程编排',
      html_generator: 'HTML 生成',
      markdown_generator: 'Markdown 生成',
    };
    return labelMap[type] || type;
  };

  const getStatusConfig = (status: string) => {
    switch (status) {
      case 'active':
        return { label: '活跃', bg: 'bg-emerald-50', text: 'text-emerald-600', dot: 'bg-emerald-500' };
      case 'draft':
        return { label: '草稿', bg: 'bg-amber-50', text: 'text-amber-600', dot: 'bg-amber-500' };
      case 'inactive':
        return { label: '停用', bg: 'bg-slate-100', text: 'text-slate-500', dot: 'bg-slate-400' };
      default:
        return { label: status, bg: 'bg-slate-50', text: 'text-slate-500', dot: 'bg-slate-400' };
    }
  };

  return (
    <div className="fixed inset-0 bg-black/40 backdrop-blur-sm flex items-center justify-center z-50">
      <div className="bg-white rounded-2xl shadow-xl border border-slate-200/50 w-[760px] max-h-[85vh] flex flex-col overflow-hidden">
        {/* 头部 */}
        <div className="flex items-center justify-between px-6 py-5 border-b border-slate-100">
          <div className="flex items-center gap-4">
            <div className="w-11 h-11 rounded-xl bg-gradient-to-br from-violet-500 to-purple-600 flex items-center justify-center shadow-lg shadow-violet-500/20">
              <Bot className="w-5 h-5 text-white" />
            </div>
            <div>
              <h2 className="text-lg font-semibold text-slate-800">智能体库</h2>
              <p className="text-xs text-slate-500 mt-0.5">浏览和复用已有的智能体</p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="p-2 hover:bg-slate-100 rounded-xl transition-colors"
          >
            <X className="w-5 h-5 text-slate-400" />
          </button>
        </div>

        {/* 标签页和筛选 */}
        <div className="px-6 py-4 border-b border-slate-100 space-y-4">
          {/* 标签页 */}
          <div className="flex gap-2">
            <button
              onClick={() => setActiveTab('all')}
              className={`px-4 py-2 rounded-xl text-sm font-medium transition-all ${activeTab === 'all'
                ? 'bg-blue-50 text-blue-700 shadow-sm'
                : 'text-slate-500 hover:bg-slate-50 hover:text-slate-700'
                }`}
            >
              <span className="flex items-center gap-2">
                <Bot className="w-4 h-4" />
                全部智能体
                <span className={`px-1.5 py-0.5 text-xs rounded-full ${activeTab === 'all' ? 'bg-blue-100' : 'bg-slate-100'
                  }`}>
                  {agentLibrary.length}
                </span>
              </span>
            </button>
            <button
              onClick={() => setActiveTab('templates')}
              className={`px-4 py-2 rounded-xl text-sm font-medium transition-all ${activeTab === 'templates'
                ? 'bg-purple-50 text-purple-700 shadow-sm'
                : 'text-slate-500 hover:bg-slate-50 hover:text-slate-700'
                }`}
            >
              <span className="flex items-center gap-2">
                <Star className="w-4 h-4" />
                模板
                <span className={`px-1.5 py-0.5 text-xs rounded-full ${activeTab === 'templates' ? 'bg-purple-100' : 'bg-slate-100'
                  }`}>
                  {agentTemplates.length}
                </span>
              </span>
            </button>
          </div>

          {/* 搜索和筛选 */}
          <div className="flex gap-3">
            <div className="flex-1 relative">
              <input
                type="text"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                placeholder="搜索智能体名称或描述..."
                className="w-full pl-10 pr-4 py-2.5 rounded-xl border border-slate-200 bg-slate-50 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-300 focus:bg-white transition-all"
              />
              <Search className="w-4 h-4 absolute left-3.5 top-1/2 -translate-y-1/2 text-slate-400" />
            </div>
            <div className="relative">
              <select
                value={domainFilter}
                onChange={(e) => setDomainFilter(e.target.value)}
                className="h-full pl-10 pr-8 py-2.5 rounded-xl border border-slate-200 bg-slate-50 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-300 focus:bg-white transition-all appearance-none cursor-pointer"
              >
                <option value="">全部领域</option>
                {uniqueDomains.map((domain) => (
                  <option key={domain} value={domain}>
                    {getDomainLabel(domain)}
                  </option>
                ))}
              </select>
              <Filter className="w-4 h-4 absolute left-3.5 top-1/2 -translate-y-1/2 text-slate-400 pointer-events-none" />
            </div>
          </div>
        </div>

        {/* 内容 */}
        <div className="flex-1 overflow-y-auto p-4">
          {agentLibraryLoading ? (
            <div className="flex flex-col items-center justify-center py-16">
              <Loader2 className="w-10 h-10 text-violet-500 animate-spin mb-4" />
              <span className="text-slate-500">加载中...</span>
            </div>
          ) : filteredAgents.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-16 text-slate-400">
              <Search className="w-16 h-16 mb-4 opacity-40" />
              <p className="text-slate-600 font-medium">未找到匹配的智能体</p>
              {searchQuery && (
                <button
                  onClick={() => setSearchQuery('')}
                  className="mt-4 px-4 py-2 text-sm text-blue-600 hover:bg-blue-50 rounded-lg transition-colors"
                >
                  清除搜索条件
                </button>
              )}
            </div>
          ) : (
            <div className="grid grid-cols-2 gap-4">
              {filteredAgents.map((agent) => {
                const DomainIcon = getDomainIcon(agent.domainType);
                const domainColors = getDomainColor(agent.domainType);
                const statusConfig = getStatusConfig(agent.status);

                const displayTitle = agent.displayName || agent.name;
                const showAgentId = agent.displayName && agent.displayName !== agent.agentId;

                return (
                  <div
                    key={agent.id}
                    onClick={() => handleReuseAgent(agent)}
                    className="p-5 rounded-2xl border border-slate-100 bg-white hover:border-violet-200 hover:shadow-lg hover:shadow-violet-500/5 cursor-pointer transition-all duration-200 group"
                  >
                    <div className="flex items-start gap-4">
                      {/* 图标 */}
                      <div className={`w-12 h-12 rounded-xl ${domainColors.bg} flex items-center justify-center flex-shrink-0 group-hover:scale-105 transition-transform`}>
                        <DomainIcon className={`w-6 h-6 ${domainColors.icon}`} />
                      </div>

                      <div className="flex-1 min-w-0">
                        {/* 标题行 */}
                        <div className="flex items-center gap-2 flex-wrap">
                          <h3 className="font-semibold text-slate-800 truncate group-hover:text-violet-600 transition-colors">
                            {displayTitle}
                          </h3>
                          {agent.isTemplate && (
                            <span className="flex items-center gap-1 px-2 py-0.5 text-xs font-medium text-purple-600 bg-purple-50 rounded-full">
                              <Sparkles className="w-3 h-3" />
                              模板
                            </span>
                          )}
                        </div>

                        {/* 智能体 ID（仅当有 displayName 时显示） */}
                        {showAgentId && (
                          <p className="text-xs text-slate-400 mt-0.5 font-mono truncate">
                            {agent.agentId}
                          </p>
                        )}

                        {/* 描述 */}
                        <p className="text-sm text-slate-500 mt-1.5 line-clamp-2">
                          {agent.description || '暂无描述'}
                        </p>

                        {/* 元信息 */}
                        <div className="flex items-center gap-3 mt-3 flex-wrap">
                          {/* 状态 */}
                          <span className={`flex items-center gap-1.5 px-2 py-1 text-xs font-medium rounded-lg ${statusConfig.bg} ${statusConfig.text}`}>
                            <span className={`w-1.5 h-1.5 rounded-full ${statusConfig.dot}`} />
                            {statusConfig.label}
                          </span>

                          {/* 执行类型（中文） */}
                          <span className="flex items-center gap-1 text-xs text-slate-400">
                            <Activity className="w-3 h-3" />
                            {getExecutionTypeLabel(agent.executionType)}
                          </span>

                          {/* 领域 */}
                          <span className={`text-xs font-medium ${domainColors.text}`}>
                            {getDomainLabel(agent.domainType)}
                          </span>
                        </div>

                        {/* 模型信息 */}
                        {agent.modelName && (
                          <div className="flex items-center gap-1.5 mt-2 text-xs text-slate-400">
                            <Cpu className="w-3 h-3" />
                            <span className="truncate">{agent.modelName}</span>
                          </div>
                        )}

                        {/* 工作流使用情况 */}
                        {agent.usedInWorkflows && agent.usedInWorkflows.length > 0 && (
                          <div className="flex items-center gap-1.5 mt-2 text-xs text-slate-400">
                            <Workflow className="w-3 h-3 flex-shrink-0" />
                            <span className="truncate">
                              用于 {agent.usedInWorkflows.slice(0, 3).map(w => w.name).join('、')}
                              {agent.usedInWorkflows.length > 3 && ` 等 ${agent.usedInWorkflows.length} 个工作流`}
                            </span>
                          </div>
                        )}

                        {/* 标签 */}
                        {agent.tags.length > 0 && (
                          <div className="flex gap-1.5 mt-3 flex-wrap">
                            {agent.tags.slice(0, 2).map((tag) => (
                              <span
                                key={tag}
                                className="px-2 py-0.5 text-xs text-slate-500 bg-slate-100 rounded-md"
                              >
                                {tag}
                              </span>
                            ))}
                            {agent.tags.length > 2 && (
                              <span className="text-xs text-slate-400">+{agent.tags.length - 2}</span>
                            )}
                          </div>
                        )}
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>

        {/* 底部提示 */}
        <div className="px-6 py-4 border-t border-slate-100 bg-slate-50/50 flex items-center justify-between">
          <p className="text-sm text-slate-500">
            共 {filteredAgents.length} 个智能体
            {searchQuery && ` (搜索: "${searchQuery}")`}
          </p>
          <div className="flex items-center gap-2 text-xs text-slate-400">
            <Sparkles className="w-3.5 h-3.5" />
            点击智能体将其添加到当前工作流中
          </div>
        </div>
      </div>
    </div>
  );
};
