import { useState } from 'react';
import { ChevronDown, ChevronRight, Wrench, GitBranch } from 'lucide-react';
import type { WorkflowPlan, AgentSpec } from '../../types';

interface PlanDetailCardProps {
  plan: WorkflowPlan;
}

function AgentSpecCard({ spec, index }: { spec: AgentSpec; index: number }) {
  const [expanded, setExpanded] = useState(false);
  
  const hasDetails = (spec.suggested_tools && spec.suggested_tools.length > 0) ||
                     (spec.dependencies && spec.dependencies.length > 0);
  
  return (
    <div className="bg-white rounded-xl border border-slate-200 overflow-hidden">
      {/* 头部 - 始终显示 */}
      <div 
        className={`flex items-start gap-3 p-3 ${hasDetails ? 'cursor-pointer hover:bg-slate-50' : ''} transition-colors`}
        onClick={() => hasDetails && setExpanded(!expanded)}
      >
        {/* 序号 */}
        <span className="flex-shrink-0 flex items-center justify-center w-6 h-6 rounded-lg bg-blue-500 text-white text-xs font-medium mt-0.5">
          {index + 1}
        </span>
        
        {/* 名称和描述 - 自适应宽度 */}
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <h4 className="font-medium text-slate-800 text-sm break-words">
              {spec.display_name || spec.name}
            </h4>
            {spec.display_name && spec.display_name !== spec.name && (
              <span className="text-[10px] text-slate-400 font-mono">{spec.name}</span>
            )}
          </div>
          <p className="text-xs text-slate-500 mt-1 break-words leading-relaxed">{spec.task}</p>
        </div>
        
        {/* 展开按钮 */}
        {hasDetails && (
          <div className="flex-shrink-0 text-slate-400 mt-0.5">
            {expanded ? <ChevronDown className="w-4 h-4" /> : <ChevronRight className="w-4 h-4" />}
          </div>
        )}
      </div>
      
      {/* 详情 - 折叠 */}
      {expanded && hasDetails && (
        <div className="px-3 pb-3 pt-0 space-y-2 border-t border-slate-100">
          {/* 工具 */}
          {spec.suggested_tools && spec.suggested_tools.length > 0 && (
            <div className="flex items-start gap-2 pt-2">
              <Wrench className="w-3.5 h-3.5 text-slate-400 mt-0.5 flex-shrink-0" />
              <div className="flex flex-wrap gap-1">
                {spec.suggested_tools.map((tool, i) => (
                  <span 
                    key={i}
                    className="px-2 py-0.5 text-[10px] bg-slate-100 text-slate-600 rounded-full break-all"
                  >
                    {tool}
                  </span>
                ))}
              </div>
            </div>
          )}
          
          {/* 依赖 */}
          {spec.dependencies && spec.dependencies.length > 0 && (
            <div className="flex items-start gap-2">
              <GitBranch className="w-3.5 h-3.5 text-slate-400 mt-0.5 flex-shrink-0" />
              <div className="flex flex-wrap gap-1">
                {spec.dependencies.map((dep, i) => (
                  <span 
                    key={i}
                    className="px-2 py-0.5 text-[10px] bg-amber-50 text-amber-700 rounded-full break-all"
                  >
                    {dep}
                  </span>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export default function PlanDetailCard({ plan }: PlanDetailCardProps) {
  return (
    <div className="mt-3 bg-slate-50 rounded-2xl overflow-hidden border border-slate-200">
      {/* 标题栏 */}
      <div className="px-4 py-3 flex items-center justify-between border-b border-slate-200 bg-white">
        <h3 className="font-medium text-slate-800 flex items-center gap-2 text-sm">
          <span className="text-base">📋</span>
          工作流规划详情
        </h3>
        {plan.agent_specs && (
          <span className="text-xs text-slate-500">
            {plan.agent_specs.length} 个 Agent
          </span>
        )}
      </div>
      
      {/* Agent 列表 */}
      <div className="p-3 space-y-2">
        {plan.agent_specs?.map((spec, index) => (
          <AgentSpecCard key={index} spec={spec} index={index} />
        ))}
      </div>
    </div>
  );
}
