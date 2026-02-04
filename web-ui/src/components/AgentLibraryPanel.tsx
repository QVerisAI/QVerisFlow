import React, { useEffect, useState } from 'react';
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

  // 加载 Agent 列表
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
    const icons: Record<string, string> = {
      finance: '💰',
      healthcare: '🏥',
      research: '🔬',
      data: '📊',
      general: '🤖',
      default: '🔧',
    };
    return icons[domain] || icons.default;
  };

  const getStatusColor = (status: string) => {
    switch (status) {
      case 'active':
        return 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400';
      case 'draft':
        return 'bg-yellow-100 text-yellow-700 dark:bg-yellow-900/30 dark:text-yellow-400';
      case 'inactive':
        return 'bg-gray-100 text-gray-700 dark:bg-gray-900/30 dark:text-gray-400';
      default:
        return 'bg-gray-100 text-gray-600';
    }
  };

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
      <div className="bg-white dark:bg-gray-800 rounded-xl shadow-2xl w-[700px] max-h-[80vh] flex flex-col">
        {/* 头部 */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-200 dark:border-gray-700">
          <h2 className="text-lg font-semibold text-gray-900 dark:text-white">
            🤖 Agent 库
          </h2>
          <button
            onClick={onClose}
            className="text-gray-400 hover:text-gray-600 dark:hover:text-gray-300"
          >
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        {/* 标签页和筛选 */}
        <div className="px-6 py-3 border-b border-gray-200 dark:border-gray-700 space-y-3">
          {/* 标签页 */}
          <div className="flex gap-2">
            <button
              onClick={() => setActiveTab('all')}
              className={`px-4 py-1.5 rounded-lg text-sm font-medium transition-colors ${activeTab === 'all'
                  ? 'bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400'
                  : 'text-gray-600 hover:bg-gray-100 dark:text-gray-400 dark:hover:bg-gray-700'
                }`}
            >
              全部 Agent ({agentLibrary.length})
            </button>
            <button
              onClick={() => setActiveTab('templates')}
              className={`px-4 py-1.5 rounded-lg text-sm font-medium transition-colors ${activeTab === 'templates'
                  ? 'bg-purple-100 text-purple-700 dark:bg-purple-900/30 dark:text-purple-400'
                  : 'text-gray-600 hover:bg-gray-100 dark:text-gray-400 dark:hover:bg-gray-700'
                }`}
            >
              ⭐ 模板 ({agentTemplates.length})
            </button>
          </div>

          {/* 搜索和筛选 */}
          <div className="flex gap-3">
            <div className="flex-1 relative">
              <input
                type="text"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                placeholder="搜索 Agent..."
                className="w-full pl-9 pr-4 py-2 rounded-lg border border-gray-200 dark:border-gray-600 bg-white dark:bg-gray-700 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              />
              <svg className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
              </svg>
            </div>
            <select
              value={domainFilter}
              onChange={(e) => setDomainFilter(e.target.value)}
              className="px-3 py-2 rounded-lg border border-gray-200 dark:border-gray-600 bg-white dark:bg-gray-700 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            >
              <option value="">全部领域</option>
              {uniqueDomains.map((domain) => (
                <option key={domain} value={domain}>
                  {getDomainIcon(domain)} {domain}
                </option>
              ))}
            </select>
          </div>
        </div>

        {/* 内容 */}
        <div className="flex-1 overflow-y-auto p-4">
          {agentLibraryLoading ? (
            <div className="flex items-center justify-center py-12">
              <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-500"></div>
              <span className="ml-3 text-gray-500">加载中...</span>
            </div>
          ) : filteredAgents.length === 0 ? (
            <div className="text-center py-12 text-gray-500">
              <div className="text-4xl mb-3">🔍</div>
              <p>未找到匹配的 Agent</p>
              {searchQuery && (
                <button
                  onClick={() => setSearchQuery('')}
                  className="mt-2 text-blue-500 hover:underline text-sm"
                >
                  清除搜索条件
                </button>
              )}
            </div>
          ) : (
            <div className="grid grid-cols-2 gap-3">
              {filteredAgents.map((agent) => (
                <div
                  key={agent.id}
                  onClick={() => handleReuseAgent(agent)}
                  className="p-4 rounded-lg border border-gray-200 dark:border-gray-700 hover:border-blue-300 dark:hover:border-blue-600 hover:bg-blue-50 dark:hover:bg-blue-900/20 cursor-pointer transition-all"
                >
                  <div className="flex items-start gap-3">
                    <div className="text-2xl">
                      {getDomainIcon(agent.domainType)}
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2">
                        <h3 className="font-medium text-gray-900 dark:text-white truncate">
                          {agent.name}
                        </h3>
                        {agent.isTemplate && (
                          <span className="text-xs px-1.5 py-0.5 bg-purple-100 text-purple-600 dark:bg-purple-900/30 dark:text-purple-400 rounded">
                            模板
                          </span>
                        )}
                      </div>
                      <p className="text-xs text-gray-500 dark:text-gray-400 mt-1 line-clamp-2">
                        {agent.description || '暂无描述'}
                      </p>
                      <div className="flex items-center gap-2 mt-2">
                        <span className={`text-xs px-2 py-0.5 rounded ${getStatusColor(agent.status)}`}>
                          {agent.status}
                        </span>
                        <span className="text-xs text-gray-400">
                          {agent.executionType}
                        </span>
                      </div>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* 底部提示 */}
        <div className="px-6 py-3 border-t border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-900 rounded-b-xl">
          <p className="text-xs text-gray-500 text-center">
            点击 Agent 将其添加到当前工作流中
          </p>
        </div>
      </div>
    </div>
  );
};
