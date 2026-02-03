import { useState } from 'react';
import { 
  CheckCircle2, 
  XCircle, 
  ChevronDown, 
  ChevronRight, 
  Wrench,
  Bot,
  AlertTriangle
} from 'lucide-react';
import type { GenerationSummary, GeneratedAgentInfo, FailedAgentInfo } from '../../types';

interface GenerationSummaryCardProps {
  summary: GenerationSummary;
}

function AgentSummaryItem({ agent, index }: { agent: GeneratedAgentInfo; index: number }) {
  const [expanded, setExpanded] = useState(false);
  const hasTools = agent.tools && agent.tools.length > 0;
  
  return (
    <div className="bg-white rounded-xl border border-slate-200 overflow-hidden">
      <div 
        className={`flex items-start gap-3 p-3 ${hasTools ? 'cursor-pointer hover:bg-slate-50' : ''} transition-colors`}
        onClick={() => hasTools && setExpanded(!expanded)}
      >
        {/* 状态图标 */}
        <div className="flex-shrink-0 mt-0.5">
          {agent.status === 'success' ? (
            <CheckCircle2 className="w-5 h-5 text-green-500" />
          ) : (
            <XCircle className="w-5 h-5 text-red-500" />
          )}
        </div>
        
        {/* 内容 */}
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <h4 className="font-medium text-slate-800 text-sm">
              {agent.display_name}
            </h4>
            <span className="text-[10px] text-slate-400 font-mono">
              {agent.name}
            </span>
          </div>
          <p className="text-xs text-slate-500 mt-1 break-words leading-relaxed">
            {agent.description}
          </p>
          
          {/* 领域标签 */}
          <div className="flex items-center gap-2 mt-2">
            <span className="px-2 py-0.5 text-[10px] bg-blue-50 text-blue-600 rounded-full">
              {agent.domain_type}
            </span>
            {agent.tools_count > 0 && (
              <span className="text-[10px] text-slate-400">
                {agent.tools_count} 个工具
              </span>
            )}
          </div>
        </div>
        
        {/* 展开按钮 */}
        {hasTools && (
          <div className="flex-shrink-0 text-slate-400 mt-0.5">
            {expanded ? <ChevronDown className="w-4 h-4" /> : <ChevronRight className="w-4 h-4" />}
          </div>
        )}
      </div>
      
      {/* 工具详情 */}
      {expanded && hasTools && (
        <div className="px-3 pb-3 pt-0 border-t border-slate-100">
          <div className="flex items-start gap-2 pt-2">
            <Wrench className="w-3.5 h-3.5 text-slate-400 mt-0.5 flex-shrink-0" />
            <div className="flex flex-wrap gap-1">
              {agent.tools.map((tool, i) => (
                <span 
                  key={i}
                  className="px-2 py-0.5 text-[10px] bg-slate-100 text-slate-600 rounded-full"
                >
                  {tool}
                </span>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function FailedAgentItem({ agent }: { agent: FailedAgentInfo }) {
  return (
    <div className="bg-red-50 rounded-xl border border-red-200 p-3">
      <div className="flex items-start gap-3">
        <XCircle className="w-5 h-5 text-red-500 flex-shrink-0 mt-0.5" />
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <h4 className="font-medium text-red-700 text-sm">
              {agent.display_name}
            </h4>
            <span className="text-[10px] text-red-400 font-mono">
              {agent.name}
            </span>
          </div>
          <p className="text-xs text-red-600 mt-1">
            失败原因: {agent.reason}
          </p>
        </div>
      </div>
    </div>
  );
}

export default function GenerationSummaryCard({ summary }: GenerationSummaryCardProps) {
  const hasFailures = summary.failed_count > 0;
  
  return (
    <div className="mt-3 bg-slate-50 rounded-2xl overflow-hidden border border-slate-200">
      {/* 标题栏 */}
      <div className={`px-4 py-3 flex items-center justify-between border-b ${
        hasFailures ? 'bg-amber-50 border-amber-200' : 'bg-green-50 border-green-200'
      }`}>
        <h3 className={`font-medium flex items-center gap-2 text-sm ${
          hasFailures ? 'text-amber-800' : 'text-green-800'
        }`}>
          {hasFailures ? (
            <>
              <AlertTriangle className="w-4 h-4" />
              生成完成（部分失败）
            </>
          ) : (
            <>
              <CheckCircle2 className="w-4 h-4" />
              全部生成完成
            </>
          )}
        </h3>
        <div className="flex items-center gap-2">
          <Bot className="w-4 h-4 text-slate-400" />
          <span className="text-xs text-slate-600">
            {summary.total_agents} 个 Agent
            {hasFailures && (
              <span className="text-red-500 ml-1">
                （{summary.failed_count} 个失败）
              </span>
            )}
          </span>
        </div>
      </div>
      
      {/* Agent 列表 */}
      <div className="p-3 space-y-2">
        {/* 成功的 Agents */}
        {summary.agents.map((agent, index) => (
          <AgentSummaryItem key={agent.name} agent={agent} index={index} />
        ))}
        
        {/* 失败的 Agents */}
        {summary.failed_agents && summary.failed_agents.length > 0 && (
          <div className="mt-3 pt-3 border-t border-slate-200">
            <h4 className="text-xs font-medium text-red-600 mb-2 flex items-center gap-1">
              <XCircle className="w-3 h-3" />
              生成失败
            </h4>
            <div className="space-y-2">
              {summary.failed_agents.map((agent) => (
                <FailedAgentItem key={agent.name} agent={agent} />
              ))}
            </div>
          </div>
        )}
      </div>
      
      {/* 下一步提示 */}
      {summary.next_step && (
        <div className="px-4 py-3 bg-blue-50 border-t border-blue-100">
          <p className="text-xs text-blue-700">
            💡 {summary.next_step}
          </p>
        </div>
      )}
    </div>
  );
}
