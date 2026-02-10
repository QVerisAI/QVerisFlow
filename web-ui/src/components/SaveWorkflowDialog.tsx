import React, { useState } from 'react';
import { X, Save, Loader2, Tag, FileText, AlignLeft } from 'lucide-react';
import { wsService } from '../services/websocket';
import { WSMessageType } from '../types';

interface SaveWorkflowDialogProps {
  onClose: () => void;
  defaultName?: string;
  defaultDescription?: string;
}

export const SaveWorkflowDialog: React.FC<SaveWorkflowDialogProps> = ({
  onClose,
  defaultName = '',
  defaultDescription = '',
}) => {
  const [name, setName] = useState(defaultName);
  const [description, setDescription] = useState(defaultDescription);
  const [tags, setTags] = useState('');
  const [isSaving, setIsSaving] = useState(false);

  const handleSave = () => {
    if (!name.trim()) {
      alert('请输入工作流名称');
      return;
    }

    setIsSaving(true);
    wsService.send(WSMessageType.SAVE_WORKFLOW, {
      name: name.trim(),
      description: description.trim(),
      tags: tags.split(',').map(t => t.trim()).filter(Boolean),
    });

    // 保存成功后会通过 WebSocket 消息关闭对话框
    // 这里设置一个超时以防止无限等待
    setTimeout(() => {
      setIsSaving(false);
    }, 10000);
  };

  return (
    <div className="fixed inset-0 bg-black/40 backdrop-blur-sm flex items-center justify-center z-50">
      <div className="bg-white rounded-2xl shadow-xl border border-slate-200/50 w-[500px] overflow-hidden">
        {/* 头部 */}
        <div className="flex items-center justify-between px-6 py-5 border-b border-slate-100">
          <div className="flex items-center gap-4">
            <div className="w-11 h-11 rounded-xl bg-gradient-to-br from-emerald-500 to-teal-600 flex items-center justify-center shadow-lg shadow-emerald-500/20">
              <Save className="w-5 h-5 text-white" />
            </div>
            <div>
              <h2 className="text-lg font-semibold text-slate-800">保存工作流</h2>
              <p className="text-xs text-slate-500 mt-0.5">将当前工作流保存到库中</p>
            </div>
          </div>
          <button
            onClick={onClose}
            disabled={isSaving}
            className="p-2 hover:bg-slate-100 rounded-xl transition-colors disabled:opacity-50"
          >
            <X className="w-5 h-5 text-slate-400" />
          </button>
        </div>

        {/* 表单 */}
        <div className="p-6 space-y-5">
          {/* 名称 */}
          <div>
            <label className="flex items-center gap-2 text-sm font-medium text-slate-700 mb-2">
              <FileText className="w-4 h-4 text-slate-400" />
              工作流名称
              <span className="text-red-500">*</span>
            </label>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="例如：芯海科技董事长早晚报工作流"
              className="w-full px-4 py-3 rounded-xl border border-slate-200 bg-slate-50 text-slate-800 placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-emerald-500/20 focus:border-emerald-300 focus:bg-white transition-all"
              disabled={isSaving}
              autoFocus
            />
          </div>

          {/* 描述 */}
          <div>
            <label className="flex items-center gap-2 text-sm font-medium text-slate-700 mb-2">
              <AlignLeft className="w-4 h-4 text-slate-400" />
              描述
            </label>
            <textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="简要描述这个工作流的用途和功能..."
              rows={3}
              className="w-full px-4 py-3 rounded-xl border border-slate-200 bg-slate-50 text-slate-800 placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-emerald-500/20 focus:border-emerald-300 focus:bg-white transition-all resize-none"
              disabled={isSaving}
            />
          </div>

          {/* 标签 */}
          <div>
            <label className="flex items-center gap-2 text-sm font-medium text-slate-700 mb-2">
              <Tag className="w-4 h-4 text-slate-400" />
              标签
              <span className="text-slate-400 font-normal text-xs">(多个标签用逗号分隔)</span>
            </label>
            <input
              type="text"
              value={tags}
              onChange={(e) => setTags(e.target.value)}
              placeholder="例如：半导体,芯片,财报分析"
              className="w-full px-4 py-3 rounded-xl border border-slate-200 bg-slate-50 text-slate-800 placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-emerald-500/20 focus:border-emerald-300 focus:bg-white transition-all"
              disabled={isSaving}
            />
            {/* 标签预览 */}
            {tags && (
              <div className="flex flex-wrap gap-1.5 mt-2">
                {tags.split(',').map((tag, i) => tag.trim() && (
                  <span
                    key={i}
                    className="px-2 py-0.5 text-xs text-emerald-600 bg-emerald-50 rounded-md"
                  >
                    {tag.trim()}
                  </span>
                ))}
              </div>
            )}
          </div>
        </div>

        {/* 按钮 */}
        <div className="flex items-center justify-end gap-3 px-6 py-4 border-t border-slate-100 bg-slate-50/50">
          <button
            onClick={onClose}
            className="px-4 py-2 text-sm font-medium text-slate-600 hover:bg-slate-100 rounded-lg transition-colors"
            disabled={isSaving}
          >
            取消
          </button>
          <button
            onClick={handleSave}
            disabled={isSaving || !name.trim()}
            className="flex items-center gap-2 px-5 py-2 text-sm font-medium text-white bg-gradient-to-r from-emerald-500 to-teal-600 hover:from-emerald-600 hover:to-teal-700 disabled:opacity-50 disabled:cursor-not-allowed rounded-lg shadow-sm transition-all"
          >
            {isSaving ? (
              <>
                <Loader2 className="w-4 h-4 animate-spin" />
                保存中...
              </>
            ) : (
              <>
                <Save className="w-4 h-4" />
                保存工作流
              </>
            )}
          </button>
        </div>
      </div>
    </div>
  );
};
