import React, { useState, useEffect } from 'react';
import {
  X,
  Clock,
  Calendar,
  Bell,
  BellOff,
  Save,
  Loader2,
  AlertCircle,
  Timer,
  Trash2,
} from 'lucide-react';
import { wsService } from '../services/websocket';
import { WSMessageType, type WorkflowSummary, type ScheduleConfig } from '../types';

interface ScheduleTaskDialogProps {
  workflow: WorkflowSummary;
  onClose: () => void;
  onSave?: (config: ScheduleConfig) => void;
}

type FrequencyType = 'daily' | 'weekly' | 'cron';

const WEEKDAYS = [
  { key: 'mon', label: '一' },
  { key: 'tue', label: '二' },
  { key: 'wed', label: '三' },
  { key: 'thu', label: '四' },
  { key: 'fri', label: '五' },
  { key: 'sat', label: '六' },
  { key: 'sun', label: '日' },
];

export const ScheduleTaskDialog: React.FC<ScheduleTaskDialogProps> = ({
  workflow,
  onClose,
  onSave,
}) => {
  const existingConfig = workflow.scheduleConfig;

  const [enabled, setEnabled] = useState(existingConfig?.enabled ?? true);
  const [frequency, setFrequency] = useState<FrequencyType>('daily');
  const [time, setTime] = useState('08:00');
  const [selectedDays, setSelectedDays] = useState<string[]>(['mon', 'tue', 'wed', 'thu', 'fri']);
  const [cronExpression, setCronExpression] = useState('0 8 * * *');
  const [notifyOnComplete, setNotifyOnComplete] = useState(existingConfig?.notifyOnComplete ?? true);
  const [notifyOnFailure, setNotifyOnFailure] = useState(existingConfig?.notifyOnFailure ?? true);
  const [isSaving, setIsSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // 解析现有配置
  useEffect(() => {
    if (existingConfig?.cronExpression) {
      const cron = existingConfig.cronExpression;
      setCronExpression(cron);

      // 尝试解析 cron 表达式
      const parts = cron.split(' ');
      if (parts.length >= 5) {
        const [minute, hour, , , dayOfWeek] = parts;

        // 设置时间
        if (hour !== '*' && minute !== '*') {
          setTime(`${hour.padStart(2, '0')}:${minute.padStart(2, '0')}`);
        }

        // 判断频率类型
        if (dayOfWeek === '*') {
          setFrequency('daily');
        } else if (dayOfWeek.includes(',') || /^[0-6]$/.test(dayOfWeek)) {
          setFrequency('weekly');
          // 解析选中的星期
          const dayMap: Record<string, string> = {
            '1': 'mon', '2': 'tue', '3': 'wed', '4': 'thu', '5': 'fri', '6': 'sat', '0': 'sun',
          };
          const days = dayOfWeek.split(',').map(d => dayMap[d]).filter(Boolean);
          if (days.length > 0) setSelectedDays(days);
        } else {
          setFrequency('cron');
        }
      }
    }
  }, [existingConfig]);

  const generateCronExpression = (): string => {
    const [hour, minute] = time.split(':');

    switch (frequency) {
      case 'daily':
        return `${parseInt(minute)} ${parseInt(hour)} * * *`;
      case 'weekly': {
        const dayMap: Record<string, string> = {
          'mon': '1', 'tue': '2', 'wed': '3', 'thu': '4', 'fri': '5', 'sat': '6', 'sun': '0',
        };
        const days = selectedDays.map(d => dayMap[d]).join(',');
        return `${parseInt(minute)} ${parseInt(hour)} * * ${days}`;
      }
      case 'cron':
        return cronExpression;
      default:
        return '0 8 * * *';
    }
  };

  const validateCron = (cron: string): boolean => {
    const parts = cron.trim().split(/\s+/);
    return parts.length === 5;
  };

  const handleSave = async () => {
    if (frequency === 'cron' && !validateCron(cronExpression)) {
      setError('Cron 表达式格式不正确，需要 5 个字段');
      return;
    }

    if (frequency === 'weekly' && selectedDays.length === 0) {
      setError('请至少选择一天');
      return;
    }

    setIsSaving(true);
    setError(null);

    const config: ScheduleConfig = {
      enabled,
      cronExpression: generateCronExpression(),
      timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
      notifyOnComplete,
      notifyOnFailure,
    };

    try {
      // 发送到后端
      wsService.send(WSMessageType.SCHEDULE_WORKFLOW, {
        workflow_id: workflow.workflowId,
        workflow_db_id: workflow.id,
        schedule_config: config,
      });

      onSave?.(config);
      onClose();
    } catch (err) {
      setError('保存失败，请重试');
    } finally {
      setIsSaving(false);
    }
  };

  const handleDelete = () => {
    if (confirm('确定要删除定时任务配置吗？')) {
      wsService.send(WSMessageType.UNSCHEDULE_WORKFLOW, {
        workflow_id: workflow.workflowId,
        workflow_db_id: workflow.id,
      });
      onClose();
    }
  };

  const toggleDay = (day: string) => {
    setSelectedDays(prev =>
      prev.includes(day)
        ? prev.filter(d => d !== day)
        : [...prev, day]
    );
  };

  const getNextExecutionTime = (): string => {
    const now = new Date();
    const [hour, minute] = time.split(':').map(Number);

    // 简化计算，只显示大概时间
    const next = new Date(now);
    next.setHours(hour, minute, 0, 0);

    if (frequency === 'daily') {
      if (next <= now) {
        next.setDate(next.getDate() + 1);
      }
    } else if (frequency === 'weekly') {
      // 找到下一个选中的日期
      const dayMap: Record<string, number> = {
        'sun': 0, 'mon': 1, 'tue': 2, 'wed': 3, 'thu': 4, 'fri': 5, 'sat': 6,
      };
      const selectedDayNums = selectedDays.map(d => dayMap[d]).sort((a, b) => a - b);
      const currentDay = now.getDay();

      let nextDay = selectedDayNums.find(d => d > currentDay || (d === currentDay && next > now));
      if (nextDay === undefined) {
        nextDay = selectedDayNums[0];
        next.setDate(next.getDate() + (7 - currentDay + nextDay));
      } else {
        next.setDate(next.getDate() + (nextDay - currentDay));
      }
    }

    return next.toLocaleString('zh-CN', {
      month: 'long',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
      weekday: 'short',
    });
  };

  return (
    <div className="fixed inset-0 bg-black/40 backdrop-blur-sm flex items-center justify-center z-50">
      <div className="bg-white rounded-2xl shadow-xl border border-slate-200/50 w-[520px] overflow-hidden">
        {/* 头部 */}
        <div className="flex items-center justify-between px-6 py-5 border-b border-slate-100">
          <div className="flex items-center gap-4">
            <div className="w-11 h-11 rounded-xl bg-gradient-to-br from-purple-500 to-violet-600 flex items-center justify-center shadow-lg shadow-purple-500/20">
              <Timer className="w-5 h-5 text-white" />
            </div>
            <div>
              <h2 className="text-lg font-semibold text-slate-800">配置定时任务</h2>
              <p className="text-xs text-slate-500 mt-0.5">设置工作流自动执行计划</p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="p-2 hover:bg-slate-100 rounded-xl transition-colors"
          >
            <X className="w-5 h-5 text-slate-400" />
          </button>
        </div>

        {/* 工作流信息 */}
        <div className="px-6 py-4 bg-slate-50 border-b border-slate-100">
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 rounded-lg bg-blue-100 flex items-center justify-center">
              <Calendar className="w-4 h-4 text-blue-600" />
            </div>
            <div className="flex-1 min-w-0">
              <p className="text-sm font-medium text-slate-700 truncate">{workflow.name}</p>
              <p className="text-xs text-slate-500 truncate">{workflow.description || '暂无描述'}</p>
            </div>
          </div>
        </div>

        {/* 配置表单 */}
        <div className="p-6 space-y-6">
          {/* 启用开关 */}
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm font-medium text-slate-700">启用定时任务</p>
              <p className="text-xs text-slate-500 mt-0.5">开启后将按计划自动执行</p>
            </div>
            <button
              onClick={() => setEnabled(!enabled)}
              className={`relative w-12 h-6 rounded-full transition-colors ${
                enabled ? 'bg-purple-500' : 'bg-slate-200'
              }`}
            >
              <span
                className={`absolute top-1 w-4 h-4 bg-white rounded-full shadow transition-transform ${
                  enabled ? 'left-7' : 'left-1'
                }`}
              />
            </button>
          </div>

          {enabled && (
            <>
              {/* 执行频率 */}
              <div>
                <label className="block text-sm font-medium text-slate-700 mb-3">执行频率</label>
                <div className="space-y-3">
                  {/* 每天 */}
                  <label className="flex items-center gap-3 p-4 rounded-xl border border-slate-200 hover:border-purple-200 hover:bg-purple-50/30 cursor-pointer transition-all">
                    <input
                      type="radio"
                      name="frequency"
                      checked={frequency === 'daily'}
                      onChange={() => setFrequency('daily')}
                      className="w-4 h-4 text-purple-600 focus:ring-purple-500"
                    />
                    <div className="flex-1">
                      <p className="text-sm font-medium text-slate-700">每天</p>
                      <p className="text-xs text-slate-500">在固定时间执行</p>
                    </div>
                    {frequency === 'daily' && (
                      <input
                        type="time"
                        value={time}
                        onChange={(e) => setTime(e.target.value)}
                        className="px-3 py-1.5 rounded-lg border border-slate-200 text-sm focus:outline-none focus:ring-2 focus:ring-purple-500/20 focus:border-purple-300"
                      />
                    )}
                  </label>

                  {/* 每周 */}
                  <label className="flex items-start gap-3 p-4 rounded-xl border border-slate-200 hover:border-purple-200 hover:bg-purple-50/30 cursor-pointer transition-all">
                    <input
                      type="radio"
                      name="frequency"
                      checked={frequency === 'weekly'}
                      onChange={() => setFrequency('weekly')}
                      className="w-4 h-4 text-purple-600 focus:ring-purple-500 mt-1"
                    />
                    <div className="flex-1">
                      <p className="text-sm font-medium text-slate-700">每周</p>
                      <p className="text-xs text-slate-500 mb-2">选择执行的日期</p>
                      {frequency === 'weekly' && (
                        <div className="flex items-center gap-2">
                          <div className="flex gap-1">
                            {WEEKDAYS.map((day) => (
                              <button
                                key={day.key}
                                type="button"
                                onClick={(e) => {
                                  e.preventDefault();
                                  toggleDay(day.key);
                                }}
                                className={`w-8 h-8 rounded-lg text-xs font-medium transition-all ${
                                  selectedDays.includes(day.key)
                                    ? 'bg-purple-500 text-white'
                                    : 'bg-slate-100 text-slate-600 hover:bg-slate-200'
                                }`}
                              >
                                {day.label}
                              </button>
                            ))}
                          </div>
                          <input
                            type="time"
                            value={time}
                            onChange={(e) => setTime(e.target.value)}
                            className="ml-2 px-3 py-1.5 rounded-lg border border-slate-200 text-sm focus:outline-none focus:ring-2 focus:ring-purple-500/20 focus:border-purple-300"
                          />
                        </div>
                      )}
                    </div>
                  </label>

                  {/* Cron 表达式 */}
                  <label className="flex items-start gap-3 p-4 rounded-xl border border-slate-200 hover:border-purple-200 hover:bg-purple-50/30 cursor-pointer transition-all">
                    <input
                      type="radio"
                      name="frequency"
                      checked={frequency === 'cron'}
                      onChange={() => setFrequency('cron')}
                      className="w-4 h-4 text-purple-600 focus:ring-purple-500 mt-1"
                    />
                    <div className="flex-1">
                      <p className="text-sm font-medium text-slate-700">Cron 表达式</p>
                      <p className="text-xs text-slate-500 mb-2">高级定时配置</p>
                      {frequency === 'cron' && (
                        <input
                          type="text"
                          value={cronExpression}
                          onChange={(e) => setCronExpression(e.target.value)}
                          placeholder="0 8 * * *"
                          className="w-full px-3 py-2 rounded-lg border border-slate-200 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-purple-500/20 focus:border-purple-300"
                        />
                      )}
                    </div>
                  </label>
                </div>
              </div>

              {/* 下次执行时间预览 */}
              <div className="flex items-center gap-3 p-4 bg-purple-50 rounded-xl">
                <Clock className="w-5 h-5 text-purple-500" />
                <div>
                  <p className="text-xs text-purple-600 font-medium">预计下次执行</p>
                  <p className="text-sm text-purple-700">{getNextExecutionTime()}</p>
                </div>
              </div>

              {/* 通知设置 */}
              <div>
                <label className="block text-sm font-medium text-slate-700 mb-3">通知设置</label>
                <div className="space-y-2">
                  <label className="flex items-center gap-3 p-3 rounded-xl hover:bg-slate-50 cursor-pointer transition-colors">
                    <input
                      type="checkbox"
                      checked={notifyOnComplete}
                      onChange={(e) => setNotifyOnComplete(e.target.checked)}
                      className="w-4 h-4 text-purple-600 rounded focus:ring-purple-500"
                    />
                    <Bell className="w-4 h-4 text-slate-400" />
                    <span className="text-sm text-slate-700">执行完成后发送通知</span>
                  </label>
                  <label className="flex items-center gap-3 p-3 rounded-xl hover:bg-slate-50 cursor-pointer transition-colors">
                    <input
                      type="checkbox"
                      checked={notifyOnFailure}
                      onChange={(e) => setNotifyOnFailure(e.target.checked)}
                      className="w-4 h-4 text-purple-600 rounded focus:ring-purple-500"
                    />
                    <BellOff className="w-4 h-4 text-slate-400" />
                    <span className="text-sm text-slate-700">仅在失败时通知</span>
                  </label>
                </div>
              </div>
            </>
          )}

          {/* 错误提示 */}
          {error && (
            <div className="flex items-center gap-2 p-3 bg-red-50 text-red-600 rounded-xl">
              <AlertCircle className="w-4 h-4" />
              <span className="text-sm">{error}</span>
            </div>
          )}
        </div>

        {/* 底部按钮 */}
        <div className="flex items-center justify-between px-6 py-4 border-t border-slate-100 bg-slate-50/50">
          <div>
            {existingConfig?.enabled && (
              <button
                onClick={handleDelete}
                className="flex items-center gap-2 px-4 py-2 text-sm text-red-600 hover:bg-red-50 rounded-lg transition-colors"
              >
                <Trash2 className="w-4 h-4" />
                删除配置
              </button>
            )}
          </div>
          <div className="flex items-center gap-3">
            <button
              onClick={onClose}
              className="px-4 py-2 text-sm font-medium text-slate-600 hover:bg-slate-100 rounded-lg transition-colors"
            >
              取消
            </button>
            <button
              onClick={handleSave}
              disabled={isSaving}
              className="flex items-center gap-2 px-5 py-2 text-sm font-medium text-white bg-gradient-to-r from-purple-500 to-violet-600 hover:from-purple-600 hover:to-violet-700 disabled:opacity-50 disabled:cursor-not-allowed rounded-lg shadow-sm transition-all"
            >
              {isSaving ? (
                <>
                  <Loader2 className="w-4 h-4 animate-spin" />
                  保存中...
                </>
              ) : (
                <>
                  <Save className="w-4 h-4" />
                  保存配置
                </>
              )}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};
