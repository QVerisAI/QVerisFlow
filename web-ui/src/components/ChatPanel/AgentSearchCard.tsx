import {
  Bot,
  Cpu,
  Tag,
  Plus,
  Sparkles,
  ChevronRight,
} from 'lucide-react';
import { useAppStore } from '../../stores/appStore';
import { wsService } from '../../services/websocket';
import { WSMessageType, type AgentSearchResult, type AgentSearchItem } from '../../types';

interface AgentSearchCardProps {
  data: AgentSearchResult;
}

// 领域类型映射
const domainTypeLabels: Record<string, { label: string; color: string }> = {
  finance: { label: '金融', color: 'bg-emerald-100 text-emerald-700' },
  data_analysis: { label: '数据分析', color: 'bg-blue-100 text-blue-700' },
  research: { label: '研究', color: 'bg-purple-100 text-purple-700' },
  general: { label: '通用', color: 'bg-slate-100 text-slate-700' },
  automation: { label: '自动化', color: 'bg-amber-100 text-amber-700' },
};

// 执行类型映射
const executionTypeLabels: Record<string, string> = {
  executor: '执行器',
  analyzer: '分析器',
  collector: '收集器',
  generator: '生成器',
  validator: '验证器',
};

function AgentItem({ agent, onAdd }: { agent: AgentSearchItem; onAdd: () => void }) {
  const domainConfig = domainTypeLabels[agent.domain_type] || domainTypeLabels.general;

  return (
    <div
      className="group p-3 bg-white rounded-xl border border-slate-200 hover:border-purple-300 hover:shadow-sm transition-all cursor-pointer"
      onClick={onAdd}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            {/* 名称 */}
            <h4 className="text-sm font-semibold text-slate-800 truncate group-hover:text-purple-600 transition-colors">
              {agent.name}
            </h4>
            {/* 模板标识 */}
            {agent.is_template && (
              <span className="flex items-center gap-0.5 px-1.5 py-0.5 text-[9px] bg-amber-100 text-amber-700 rounded">
                <Sparkles className="w-2.5 h-2.5" />
                模板
              </span>
            )}
          </div>
          {/* 描述 */}
          {agent.description && (
            <p className="text-xs text-slate-500 mt-1 line-clamp-2">
              {agent.description}
            </p>
          )}
          {/* 元信息 */}
          <div className="flex items-center gap-2 mt-2">
            <span className={`px-1.5 py-0.5 text-[10px] font-medium rounded ${domainConfig.color}`}>
              {domainConfig.label}
            </span>
            <span className="text-[10px] text-slate-400 flex items-center gap-1">
              <Cpu className="w-3 h-3" />
              {executionTypeLabels[agent.execution_type] || agent.execution_type}
            </span>
            {agent.model_name && (
              <span className="text-[10px] text-slate-400">
                {agent.model_name.split('/').pop()}
              </span>
            )}
          </div>
          {/* 标签 */}
          {agent.tags && agent.tags.length > 0 && (
            <div className="flex items-center gap-1 mt-2">
              <Tag className="w-3 h-3 text-slate-400" />
              <div className="flex flex-wrap gap-1">
                {agent.tags.slice(0, 3).map((tag, i) => (
                  <span
                    key={i}
                    className="px-1.5 py-0.5 text-[9px] bg-slate-100 text-slate-500 rounded"
                  >
                    {tag}
                  </span>
                ))}
                {agent.tags.length > 3 && (
                  <span className="text-[9px] text-slate-400">+{agent.tags.length - 3}</span>
                )}
              </div>
            </div>
          )}
        </div>
        {/* 添加按钮 */}
        <div className="flex-shrink-0 flex items-center gap-1 px-2 py-1 text-xs text-purple-600 bg-purple-50 rounded-lg opacity-0 group-hover:opacity-100 transition-opacity">
          <Plus className="w-3 h-3" />
          <span>添加</span>
          <ChevronRight className="w-3 h-3" />
        </div>
      </div>
    </div>
  );
}

export default function AgentSearchCard({ data }: AgentSearchCardProps) {
  const { addMessage } = useAppStore();

  const handleAddAgent = (databaseId: string, name: string) => {
    // 使用数据库主键 id 进行精确加载（唯一标识符）
    wsService.send(WSMessageType.REUSE_AGENT, {
      agent_db_id: databaseId,
    });

    // 添加用户消息，保持对话连续性
    addMessage({
      role: 'user',
      content: `添加智能体 ${name}`,
      timestamp: new Date().toISOString(),
      messageType: 'text',
    });
  };

  if (!data.agents || data.agents.length === 0) {
    return (
      <div className="mt-3 p-4 bg-slate-50 rounded-xl border border-slate-200 text-center">
        <Bot className="w-8 h-8 mx-auto text-slate-300 mb-2" />
        <p className="text-sm text-slate-500">没有找到智能体</p>
        <p className="text-xs text-slate-400 mt-1">尝试不同的搜索关键词</p>
      </div>
    );
  }

  return (
    <div className="mt-3 space-y-3">
      {/* 标题栏 */}
      <div className="flex items-center justify-between px-1">
        <div className="flex items-center gap-2">
          <div className="w-6 h-6 rounded-lg bg-purple-100 flex items-center justify-center">
            <Bot className="w-3.5 h-3.5 text-purple-600" />
          </div>
          <span className="text-sm font-medium text-slate-700">
            智能体库
          </span>
          <span className="text-xs text-slate-400">
            ({data.total} 个结果)
          </span>
        </div>
      </div>

      {/* 智能体列表 */}
      <div className="space-y-2 max-h-80 overflow-y-auto">
        {data.agents.map((agent) => (
          <AgentItem
            key={agent.id || agent.agent_id}
            agent={agent}
            onAdd={() => handleAddAgent(agent.id, agent.name)}
          />
        ))}
      </div>

      {/* 提示 */}
      <p className="text-[10px] text-slate-400 text-center">
        点击智能体卡片添加到当前工作流
      </p>
    </div>
  );
}
