import { useState, useRef, useEffect } from 'react';
import { ChevronDown, CheckCircle, XCircle, Loader2, Clock, Settings } from 'lucide-react';
import { useAppStore } from '../stores/appStore';
import { wsService } from '../services/websocket';
import { WSMessageType, type ExecutionRecord } from '../types';

interface ExecutionSelectorProps {
  className?: string;
}

export function ExecutionSelector({ className = '' }: ExecutionSelectorProps) {
  const { 
    mode, 
    executionHistory, 
    selectedExecutionId, 
    selectExecution,
    executionProgress,
  } = useAppStore();
  
  const [isOpen, setIsOpen] = useState(false);
  const dropdownRef = useRef<HTMLDivElement>(null);

  // 点击外部关闭下拉菜单
  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (dropdownRef.current && !dropdownRef.current.contains(event.target as Node)) {
        setIsOpen(false);
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);
  
  // 组件挂载时请求执行历史
  useEffect(() => {
    // 检查 WebSocket 是否已连接
    if (wsService.isConnected) {
      wsService.send(WSMessageType.GET_EXECUTION_HISTORY, { limit: 10 });
    }
  }, []);

  // 获取当前模式的显示信息
  const getCurrentModeDisplay = () => {
    if (selectedExecutionId) {
      const execution = executionHistory.find(e => e.executionId === selectedExecutionId);
      if (execution) {
        return {
          label: `执行 #${executionHistory.indexOf(execution) + 1}`,
          icon: execution.status === 'success' ? (
            <CheckCircle className="w-4 h-4 text-emerald-500" />
          ) : execution.status === 'failed' ? (
            <XCircle className="w-4 h-4 text-red-500" />
          ) : (
            <Loader2 className="w-4 h-4 text-blue-500 animate-spin" />
          ),
          bgColor: execution.status === 'success' ? 'bg-emerald-50 border-emerald-200' :
                   execution.status === 'failed' ? 'bg-red-50 border-red-200' :
                   'bg-blue-50 border-blue-200',
          textColor: execution.status === 'success' ? 'text-emerald-700' :
                     execution.status === 'failed' ? 'text-red-700' :
                     'text-blue-700',
        };
      }
    }
    
    switch (mode) {
      case 'executing':
        return {
          label: `执行中 ${executionProgress.nodesCompleted}/${executionProgress.totalNodes}`,
          icon: (
            <span className="relative flex h-2.5 w-2.5">
              <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75"></span>
              <span className="relative inline-flex rounded-full h-2.5 w-2.5 bg-emerald-500"></span>
            </span>
          ),
          bgColor: 'bg-emerald-50 border-emerald-200',
          textColor: 'text-emerald-700',
        };
      case 'building':
        return {
          label: '构建中',
          icon: <Settings className="w-4 h-4 animate-pulse" />,
          bgColor: 'bg-blue-50 border-blue-200',
          textColor: 'text-blue-700',
        };
      case 'completed':
        return {
          label: '已完成',
          icon: <CheckCircle className="w-4 h-4 text-emerald-500" />,
          bgColor: 'bg-slate-50 border-slate-200',
          textColor: 'text-slate-700',
        };
      default:
        return {
          label: '就绪',
          icon: <Clock className="w-4 h-4 text-slate-400" />,
          bgColor: 'bg-gray-50 border-gray-200',
          textColor: 'text-gray-500',
        };
    }
  };

  const currentDisplay = getCurrentModeDisplay();

  // 格式化时间
  const formatTime = (dateStr: string) => {
    const date = new Date(dateStr);
    const now = new Date();
    const isToday = date.toDateString() === now.toDateString();
    
    if (isToday) {
      return date.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' });
    }
    return date.toLocaleDateString('zh-CN', { month: 'numeric', day: 'numeric' }) + ' ' +
           date.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' });
  };

  // 格式化耗时
  const formatDuration = (ms?: number) => {
    if (!ms) return '-';
    if (ms < 1000) return `${ms}ms`;
    if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`;
    const minutes = Math.floor(ms / 60000);
    const seconds = Math.floor((ms % 60000) / 1000);
    return `${minutes}分${seconds}秒`;
  };

  const handleSelect = (executionId: string | null) => {
    selectExecution(executionId);
    setIsOpen(false);
  };

  return (
    <div ref={dropdownRef} className={`${className}`}>
      {/* 相对定位容器，用于下拉菜单定位 */}
      <div className="relative">
        {/* 当前状态按钮 */}
        <button
          onClick={() => setIsOpen(!isOpen)}
          className={`
            flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium
            shadow-sm border transition-all duration-200
            hover:shadow-md
            ${currentDisplay.bgColor} ${currentDisplay.textColor}
          `}
        >
          {currentDisplay.icon}
          <span>{currentDisplay.label}</span>
          <ChevronDown className={`w-4 h-4 transition-transform ${isOpen ? 'rotate-180' : ''}`} />
        </button>

        {/* 下拉菜单 */}
        {isOpen && (
          <div className="absolute top-full right-0 mt-2 w-64 bg-white rounded-xl shadow-lg border border-slate-200 overflow-hidden z-50 animate-in slide-in-from-top-2 duration-200">
          {/* 当前构建选项 */}
          <button
            onClick={() => handleSelect(null)}
            className={`
              w-full px-4 py-3 flex items-center gap-3 text-left
              hover:bg-slate-50 transition-colors
              ${!selectedExecutionId ? 'bg-blue-50' : ''}
            `}
          >
            <span className={`w-2 h-2 rounded-full ${!selectedExecutionId ? 'bg-blue-500' : 'bg-slate-300'}`} />
            <span className="font-medium text-sm text-slate-700">当前构建</span>
            {mode === 'executing' && (
              <span className="ml-auto text-xs text-emerald-600">执行中...</span>
            )}
          </button>

          {/* 分隔线 */}
          {executionHistory.length > 0 && (
            <div className="border-t border-slate-100 my-1" />
          )}

          {/* 历史执行列表 */}
          {executionHistory.length > 0 ? (
            <div className="max-h-64 overflow-y-auto">
              {executionHistory.map((execution, index) => (
                <button
                  key={execution.executionId}
                  onClick={() => handleSelect(execution.executionId)}
                  className={`
                    w-full px-4 py-3 flex items-center gap-3 text-left
                    hover:bg-slate-50 transition-colors
                    ${selectedExecutionId === execution.executionId ? 'bg-slate-50' : ''}
                  `}
                >
                  {/* 状态图标 */}
                  {execution.status === 'success' ? (
                    <CheckCircle className="w-4 h-4 text-emerald-500 flex-shrink-0" />
                  ) : execution.status === 'failed' ? (
                    <XCircle className="w-4 h-4 text-red-500 flex-shrink-0" />
                  ) : execution.status === 'running' ? (
                    <Loader2 className="w-4 h-4 text-blue-500 animate-spin flex-shrink-0" />
                  ) : (
                    <Clock className="w-4 h-4 text-slate-400 flex-shrink-0" />
                  )}
                  
                  {/* 执行信息 */}
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="text-sm font-medium text-slate-700">
                        #{executionHistory.length - index}
                      </span>
                      <span className="text-xs text-slate-400">
                        {formatTime(execution.startedAt)}
                      </span>
                    </div>
                    <div className="text-xs text-slate-500 mt-0.5">
                      {execution.status === 'success' ? (
                        <span className="text-emerald-600">{formatDuration(execution.totalDurationMs)}</span>
                      ) : execution.status === 'failed' ? (
                        <span className="text-red-600">
                          失败于节点 {execution.nodesFailed > 0 ? `(${execution.nodesFailed}个)` : ''}
                        </span>
                      ) : execution.status === 'running' ? (
                        <span className="text-blue-600">
                          {execution.nodesCompleted}/{execution.nodesTotal} 节点
                        </span>
                      ) : (
                        <span>已取消</span>
                      )}
                    </div>
                  </div>
                </button>
              ))}
            </div>
          ) : (
            <div className="px-4 py-6 text-center text-slate-400 text-sm">
              <Clock className="w-8 h-8 mx-auto mb-2 opacity-50" />
              <p>暂无执行记录</p>
              <p className="text-xs mt-1">点击"执行"开始第一次运行</p>
            </div>
          )}
        </div>
        )}
      </div>
    </div>
  );
}
