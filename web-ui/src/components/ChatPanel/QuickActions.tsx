import { Check, Undo, Play, Pause, Square, SkipForward, Save } from 'lucide-react';

interface QuickActionsProps {
  mode: 'idle' | 'building' | 'executing' | 'completed';
  onAction: (action: string) => void;
}

export function QuickActions({ mode, onAction }: QuickActionsProps) {
  // 根据模式显示不同的操作
  const getActions = () => {
    if (mode === 'executing') {
      return [
        { id: 'pause', label: '暂停', icon: Pause, color: 'text-yellow-600' },
        { id: 'stop', label: '停止', icon: Square, color: 'text-red-600' },
        { id: 'skip_node', label: '跳过', icon: SkipForward, color: 'text-blue-600' },
      ];
    }
    
    if (mode === 'building') {
      return [
        { id: 'approve', label: '确认', icon: Check, color: 'text-green-600' },
        { id: 'rollback', label: '撤销', icon: Undo, color: 'text-orange-600' },
        { id: 'execute', label: '执行', icon: Play, color: 'text-blue-600' },
        { id: 'save', label: '保存', icon: Save, color: 'text-gray-600' },
      ];
    }
    
    if (mode === 'completed') {
      return [
        { id: 'execute', label: '重新执行', icon: Play, color: 'text-blue-600' },
        { id: 'save', label: '保存', icon: Save, color: 'text-gray-600' },
      ];
    }
    
    return [];
  };

  const actions = getActions();

  if (actions.length === 0) return null;

  return (
    <div className="px-4 py-2 border-t bg-gray-50">
      <div className="text-xs text-gray-500 mb-2">快捷操作</div>
      <div className="flex flex-wrap gap-2">
        {actions.map(({ id, label, icon: Icon, color }) => (
          <button
            key={id}
            onClick={() => onAction(id)}
            className={`
              flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium
              bg-white border rounded-md hover:bg-gray-50 transition-colors
              ${color}
            `}
          >
            <Icon className="w-3.5 h-3.5" />
            {label}
          </button>
        ))}
      </div>
    </div>
  );
}
