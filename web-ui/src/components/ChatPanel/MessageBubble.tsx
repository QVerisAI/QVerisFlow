import { User, Bot, Info, AlertCircle, Play, Loader2, CheckCircle, XCircle, BarChart3, Rocket, SkipForward, Save, FolderOpen } from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import type { Message, WorkflowPlan, GenerationSummary, GenerationProgressEvent, WorkflowInfoCard as WorkflowInfoCardType, WorkflowSearchResult, AgentSearchResult, ExecutionProgress, ExecutionSummary } from '../../types';
import PlanDetailCard from './PlanDetailCard';
import GenerationSummaryCard from './GenerationSummaryCard';
import WorkflowInfoCard from './WorkflowInfoCard';
import WorkflowSearchCard from './WorkflowSearchCard';
import AgentSearchCard from './AgentSearchCard';
import ExecutionProgressCard from './ExecutionProgressCard';
import ExecutionSummaryCard from './ExecutionSummaryCard';

interface MessageBubbleProps {
  message: Message;
}

export function MessageBubble({ message }: MessageBubbleProps) {
  const isUser = message.role === 'user';
  const isSystem = message.role === 'system';
  const isError = message.messageType === 'error';
  const isExecutionEvent = message.messageType === 'execution_event';
  const isProgress = message.messageType === 'progress';

  // 检查是否是生成进度事件（提前检查，用于过期过滤）
  const progressData = message.data?.type === 'agent_generation_progress'
    ? message.data as unknown as GenerationProgressEvent
    : undefined;

  // === 过滤过期的 Agent 生成进度消息 ===
  // 这是最后一道防线，确保即使消息进入了列表，也不会被渲染
  if (progressData) {
    try {
      const msgTime = new Date(message.timestamp).getTime();
      const now = Date.now();
      const MAX_AGE_MS = 5 * 60 * 1000; // 5 分钟
      // 只有当时间戳有效且消息过期时才过滤
      if (!isNaN(msgTime) && (now - msgTime) > MAX_AGE_MS) {
        console.log('[MessageBubble] 跳过过期的进度消息:', {
          timestamp: message.timestamp,
          age: Math.round((now - msgTime) / 1000) + '秒',
          displayName: progressData.display_name
        });
        return null; // 不渲染过期的进度消息
      }
    } catch (e) {
      // 时间戳解析失败，继续渲染
      console.warn('[MessageBubble] 时间戳解析失败:', message.timestamp);
    }
  }

  // 检查是否包含规划数据
  const planData = message.data?.plan as WorkflowPlan | undefined;

  // 检查是否包含生成摘要数据
  const summaryData = message.data?.summary as GenerationSummary | undefined;

  // 检查是否是工作流信息卡片
  const workflowInfoData = message.data?.type === 'workflow_info_card'
    ? message.data as unknown as WorkflowInfoCardType
    : undefined;

  // 检查是否是工作流搜索结果
  const workflowSearchData = message.data?.type === 'workflow_search_result'
    ? message.data as unknown as WorkflowSearchResult
    : undefined;

  // 检查是否是 Agent 搜索结果
  const agentSearchData = message.data?.type === 'agent_search_result'
    ? message.data as unknown as AgentSearchResult
    : undefined;

  // 检查是否是执行进度消息
  const executionProgressData = message.data?.type === 'execution_progress'
    ? message.data as unknown as ExecutionProgress
    : undefined;

  // 检查是否是执行摘要消息
  const executionSummaryData = message.data?.type === 'execution_summary'
    ? message.data as unknown as ExecutionSummary
    : undefined;

  // 根据消息类型和内容智能选择图标
  const getIcon = () => {
    if (isUser) return <User className="w-4 h-4" />;
    if (isError) return <AlertCircle className="w-4 h-4 text-red-500" />;

    // 执行事件：根据消息内容智能匹配图标
    if (isExecutionEvent) {
      const content = message.content;
      if (content.includes('完成') || content.includes('✅')) {
        return <CheckCircle className="w-4 h-4 text-emerald-500" />;
      }
      if (content.includes('失败') || content.includes('❌')) {
        return <XCircle className="w-4 h-4 text-red-500" />;
      }
      if (content.includes('跳过') || content.includes('⏭')) {
        return <SkipForward className="w-4 h-4 text-amber-500" />;
      }
      if (content.includes('进度') || content.includes('📈')) {
        return <BarChart3 className="w-4 h-4 text-slate-500" />;
      }
      if (content.includes('开始执行工作流') || content.includes('🚀')) {
        return <Rocket className="w-4 h-4 text-blue-500" />;
      }
      if (content.includes('开始') || content.includes('执行') || content.includes('📊')) {
        return <Play className="w-4 h-4 text-blue-500" />;
      }
      return <Play className="w-4 h-4 text-blue-500" />;
    }

    // 进度消息：已完成显示✓，进行中显示转圈
    if (progressData) {
      if (progressData.status === 'completed') {
        return <CheckCircle className="w-4 h-4 text-emerald-500" />;
      }
      return <Loader2 className="w-4 h-4 text-blue-500 animate-spin" />;
    }
    // 工作流信息卡片
    if (workflowInfoData) {
      return <Save className="w-4 h-4 text-emerald-500" />;
    }
    // 搜索结果
    if (workflowSearchData) {
      return <FolderOpen className="w-4 h-4 text-blue-500" />;
    }
    if (agentSearchData) {
      return <Bot className="w-4 h-4 text-purple-500" />;
    }
    // 执行进度消息
    if (executionProgressData) {
      if (executionProgressData.status === 'completed') {
        return <CheckCircle className="w-4 h-4 text-emerald-500" />;
      }
      if (executionProgressData.status === 'failed') {
        return <XCircle className="w-4 h-4 text-red-500" />;
      }
      return <Loader2 className="w-4 h-4 text-blue-500 animate-spin" />;
    }
    // 执行摘要消息
    if (executionSummaryData) {
      if (executionSummaryData.status === 'completed') {
        return <CheckCircle className="w-4 h-4 text-emerald-500" />;
      }
      return <XCircle className="w-4 h-4 text-red-500" />;
    }
    if (isProgress) return <Loader2 className="w-4 h-4 text-blue-500 animate-spin" />;
    if (isSystem) return <Info className="w-4 h-4 text-gray-400" />;
    return <Bot className="w-4 h-4" />;
  };

  // 消息样式
  const getBubbleStyle = () => {
    if (isUser) {
      return 'bg-primary text-white ml-8';
    }
    if (isError) {
      return 'bg-red-50 text-red-700 border border-red-200 mr-8';
    }
    // 执行事件：根据内容设置不同样式
    if (isExecutionEvent) {
      const content = message.content;
      if (content.includes('完成') || content.includes('✅')) {
        return 'bg-emerald-50 text-emerald-700 border border-emerald-200 mr-8 text-xs';
      }
      if (content.includes('失败') || content.includes('❌')) {
        return 'bg-red-50 text-red-700 border border-red-200 mr-8 text-xs';
      }
      if (content.includes('跳过') || content.includes('⏭')) {
        return 'bg-amber-50 text-amber-700 border border-amber-200 mr-8 text-xs';
      }
      if (content.includes('进度') || content.includes('📈')) {
        return 'bg-slate-50 text-slate-600 border border-slate-200 mr-8 text-xs';
      }
      if (content.includes('开始执行工作流') || content.includes('🚀')) {
        return 'bg-blue-50 text-blue-700 border border-blue-200 mr-8 text-xs font-medium';
      }
      return 'bg-blue-50 text-blue-700 border border-blue-100 mr-8 text-xs';
    }
    // 进度消息：已完成用绿色，进行中用蓝色
    if (progressData?.status === 'completed') {
      return 'bg-emerald-50 text-emerald-700 border border-emerald-100 mr-8 text-sm';
    }
    if (isProgress || progressData) {
      return 'bg-blue-50 text-blue-700 border border-blue-100 mr-8 text-sm';
    }
    // 工作流信息卡片
    if (workflowInfoData) {
      return 'bg-emerald-50 text-emerald-700 border border-emerald-200 mr-8 text-sm';
    }
    // 搜索结果
    if (workflowSearchData || agentSearchData) {
      return 'bg-slate-50 text-slate-700 border border-slate-200 mr-4 text-sm';
    }
    // 执行进度消息
    if (executionProgressData) {
      if (executionProgressData.status === 'completed') {
        return 'bg-emerald-50 text-emerald-700 border border-emerald-100 mr-4 text-sm';
      }
      if (executionProgressData.status === 'failed') {
        return 'bg-red-50 text-red-700 border border-red-100 mr-4 text-sm';
      }
      return 'bg-blue-50 text-blue-700 border border-blue-100 mr-4 text-sm';
    }
    // 执行摘要消息
    if (executionSummaryData) {
      if (executionSummaryData.status === 'completed') {
        return 'bg-emerald-50 text-emerald-700 border border-emerald-100 mr-4 text-sm';
      }
      return 'bg-red-50 text-red-700 border border-red-100 mr-4 text-sm';
    }
    if (isSystem) {
      return 'bg-gray-100 text-gray-600 mr-8 text-sm';
    }
    return 'bg-white border border-gray-200 mr-8';
  };

  // 获取显示内容
  // 消息类型分类：
  // 1. planData - 工作流规划（构建阶段）
  // 2. summaryData - Agent 生成摘要（构建阶段）
  // 3. progressData (agent_generation_progress) - Agent 生成进度（构建阶段，实时更新）
  // 4. workflowInfoData (workflow_info_card) - 工作流保存成功信息
  // 5. workflowSearchData / agentSearchData - 搜索结果
  // 6. executionProgressData (execution_progress) - 工作流执行进度（执行阶段，包含节点状态卡片）
  // 7. executionSummaryData (execution_summary) - 工作流执行完成摘要（执行阶段）
  const getDisplayContent = () => {
    // === 构建阶段消息 ===

    // 工作流规划
    if (planData) {
      return '工作流规划已更新，请查看下方详情：';
    }

    // Agent 生成摘要（所有 Agent 生成完成后的汇总）
    if (summaryData) {
      return 'Agent 生成完成，请查看下方详情：';
    }

    // Agent 生成进度（单个 Agent 的实时生成状态）
    // 注意：这是针对 Agent 生成的进度，不是工作流执行进度
    if (progressData) {
      const { display_name, current, total, status } = progressData;
      const agentLabel = display_name || 'Agent';
      if (status === 'completed') {
        return `✓ ${agentLabel} 生成完成 (${current}/${total})`;
      }
      return `正在生成 ${agentLabel}... (${current}/${total})`;
    }

    // === 保存/搜索相关消息 ===

    // 工作流保存成功
    if (workflowInfoData) {
      return '工作流保存成功！详情如下：';
    }

    // 搜索结果消息直接使用原始内容（或简短提示）
    if (workflowSearchData) {
      return message.content || '找到以下工作流：';
    }
    if (agentSearchData) {
      return message.content || '找到以下 Agent：';
    }

    // === 执行阶段消息 ===

    // 工作流执行进度（实时节点执行状态卡片）
    if (executionProgressData) {
      const { nodesCompleted, totalNodes, status, workflowName } = executionProgressData;
      const name = workflowName ? `「${workflowName}」` : '工作流';
      if (status === 'completed') {
        return `${name}执行完成 (${nodesCompleted}/${totalNodes} 节点)`;
      }
      if (status === 'failed') {
        return `${name}执行失败 (${nodesCompleted}/${totalNodes} 节点完成)`;
      }
      return `${name}执行中... (${nodesCompleted}/${totalNodes} 节点)`;
    }

    // 工作流执行摘要（执行完成后的最终结果）
    if (executionSummaryData) {
      const name = executionSummaryData.workflowName ? `「${executionSummaryData.workflowName}」` : '工作流';
      if (executionSummaryData.status === 'completed') {
        return `${name}执行完成，查看详细结果：`;
      }
      return `${name}执行失败，查看详情：`;
    }

    // 默认：使用消息的原始内容
    return message.content;
  };

  // 渲染内容
  const renderContent = (content: string) => {
    // 如果是执行事件，保留格式
    if (isExecutionEvent) {
      return content.split('\n').map((line, i) => (
        <div key={i} className="whitespace-pre-wrap">{line}</div>
      ));
    }

    // 如果是用户消息，简单渲染
    if (isUser) {
      return <span>{content}</span>;
    }

    // 使用 Markdown 渲染助手消息
    return (
      <ReactMarkdown
        className="prose prose-sm max-w-none prose-p:my-1 prose-ul:my-1 prose-ol:my-1 prose-li:my-0 prose-headings:my-2"
        components={{
          // 自定义列表样式
          ul: ({ children }) => (
            <ul className="list-disc list-inside space-y-0.5">{children}</ul>
          ),
          ol: ({ children }) => (
            <ol className="list-decimal list-inside space-y-0.5">{children}</ol>
          ),
          // 简化段落
          p: ({ children }) => (
            <p className="mb-1 last:mb-0">{children}</p>
          ),
          // 代码块
          code: ({ children, className }) => {
            const isInline = !className;
            if (isInline) {
              return (
                <code className="bg-gray-100 px-1 py-0.5 rounded text-xs font-mono">
                  {children}
                </code>
              );
            }
            return (
              <code className="block bg-gray-100 p-2 rounded text-xs font-mono overflow-x-auto">
                {children}
              </code>
            );
          },
          // 强调
          strong: ({ children }) => (
            <strong className="font-semibold">{children}</strong>
          ),
        }}
      >
        {content}
      </ReactMarkdown>
    );
  };

  // 如果有规划数据、摘要数据、工作流信息卡片、搜索结果或执行进度/摘要，使用更宽的布局
  const maxWidthClass = (planData || summaryData || workflowInfoData || workflowSearchData || agentSearchData || executionProgressData || executionSummaryData) ? 'max-w-full' : 'max-w-[90%]';

  return (
    <div className={`flex ${isUser ? 'justify-end' : 'justify-start'}`}>
      <div className={`flex items-start gap-2 ${maxWidthClass} ${isUser ? 'flex-row-reverse' : ''}`}>
        {/* 头像 */}
        <div className={`
          flex-shrink-0 w-7 h-7 rounded-full flex items-center justify-center
          ${isUser ? 'bg-primary text-white' :
            isError ? 'bg-red-100' :
              isExecutionEvent ? (
                message.content.includes('完成') || message.content.includes('✅') ? 'bg-emerald-100' :
                  message.content.includes('失败') || message.content.includes('❌') ? 'bg-red-100' :
                    message.content.includes('跳过') || message.content.includes('⏭') ? 'bg-amber-100' :
                      message.content.includes('进度') || message.content.includes('📈') ? 'bg-slate-100' :
                        'bg-blue-100'
              ) :
                workflowInfoData ? 'bg-emerald-100' :
                  workflowSearchData ? 'bg-blue-100' :
                    agentSearchData ? 'bg-purple-100' :
                      executionProgressData ? (
                        executionProgressData.status === 'completed' ? 'bg-emerald-100' :
                          executionProgressData.status === 'failed' ? 'bg-red-100' :
                            'bg-blue-100'
                      ) :
                        executionSummaryData ? (
                          executionSummaryData.status === 'completed' ? 'bg-emerald-100' : 'bg-red-100'
                        ) :
                          (progressData?.status === 'completed') ? 'bg-emerald-100' :
                            (isProgress || progressData) ? 'bg-blue-100' :
                              'bg-gray-100'}
        `}>
          {getIcon()}
        </div>

        {/* 消息内容 */}
        <div className={`rounded-lg px-3 py-2 flex-1 min-w-0 ${getBubbleStyle()}`}>
          <div className="text-sm leading-relaxed">
            {renderContent(getDisplayContent())}
          </div>

          {/* 规划详情卡片 */}
          {planData && <PlanDetailCard plan={planData} />}

          {/* 生成摘要卡片 */}
          {summaryData && <GenerationSummaryCard summary={summaryData} />}

          {/* 工作流信息卡片 */}
          {workflowInfoData && <WorkflowInfoCard info={workflowInfoData} />}

          {/* 工作流搜索结果卡片 */}
          {workflowSearchData && <WorkflowSearchCard data={workflowSearchData} />}

          {/* Agent 搜索结果卡片 */}
          {agentSearchData && <AgentSearchCard data={agentSearchData} />}

          {/* 执行进度卡片 */}
          {executionProgressData && <ExecutionProgressCard progress={executionProgressData} />}

          {/* 执行摘要卡片 */}
          {executionSummaryData && <ExecutionSummaryCard summary={executionSummaryData} />}

          {/* 进度条（用于进度消息） */}
          {progressData && progressData.status !== 'completed' && (
            <div className="mt-2">
              <div className="w-full bg-blue-200 rounded-full h-1.5">
                <div
                  className="bg-blue-600 h-1.5 rounded-full transition-all duration-300"
                  style={{ width: `${(progressData.current / progressData.total) * 100}%` }}
                />
              </div>
            </div>
          )}

          {/* 时间戳 */}
          <div className={`
            text-[10px] mt-1 opacity-60
            ${isUser ? 'text-right' : 'text-left'}
          `}>
            {new Date(message.timestamp).toLocaleTimeString('zh-CN', {
              hour: '2-digit',
              minute: '2-digit',
            })}
          </div>
        </div>
      </div>
    </div>
  );
}
