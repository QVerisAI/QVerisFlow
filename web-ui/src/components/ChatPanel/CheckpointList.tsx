import { History, ChevronRight } from 'lucide-react';
import { useState } from 'react';
import type { CheckpointInfo } from '../../types';

interface CheckpointListProps {
  checkpoints: CheckpointInfo[];
  onRollback: (checkpointId: string) => void;
}

export function CheckpointList({ checkpoints, onRollback }: CheckpointListProps) {
  const [isExpanded, setIsExpanded] = useState(false);

  if (checkpoints.length === 0) return null;

  // 只显示最近5个
  const visibleCheckpoints = checkpoints.slice(-5).reverse();

  return (
    <div className="border-t bg-gray-50">
      {/* 标题 */}
      <button
        onClick={() => setIsExpanded(!isExpanded)}
        className="w-full px-4 py-2 flex items-center justify-between text-xs text-gray-600 hover:bg-gray-100 transition-colors"
      >
        <div className="flex items-center gap-2">
          <History className="w-3.5 h-3.5" />
          <span>检查点 ({checkpoints.length})</span>
        </div>
        <ChevronRight className={`w-4 h-4 transition-transform ${isExpanded ? 'rotate-90' : ''}`} />
      </button>

      {/* 列表 */}
      {isExpanded && (
        <div className="px-4 pb-2 space-y-1">
          {visibleCheckpoints.map((checkpoint) => (
            <button
              key={checkpoint.checkpointId}
              onClick={() => onRollback(checkpoint.checkpointId)}
              className="w-full flex items-center justify-between px-2 py-1.5 text-xs bg-white rounded border hover:bg-blue-50 hover:border-blue-200 transition-colors"
            >
              <div className="flex items-center gap-2">
                <span className="text-gray-400">
                  {new Date(checkpoint.timestamp).toLocaleTimeString('zh-CN', {
                    hour: '2-digit',
                    minute: '2-digit',
                    second: '2-digit',
                  })}
                </span>
                <span className="text-gray-700">{checkpoint.label}</span>
              </div>
              <span className="text-gray-400 text-[10px]">{checkpoint.stage}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
