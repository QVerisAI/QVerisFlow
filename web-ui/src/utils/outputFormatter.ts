/**
 * 输出格式化工具
 * 将各种类型的节点输出转换为可读的 Markdown 格式
 */

// 特殊字段名称映射（用于智能识别）
const HIGHLIGHT_FIELDS = ['recommendation', 'suggestion', '建议', '推荐'];
const SUMMARY_FIELDS = ['summary', 'conclusion', 'result', '摘要', '结论', '结果'];
const ERROR_FIELDS = ['error', 'exception', '错误', '异常'];

// 技术字段黑名单（对用户无意义，应在展示时过滤）
const TECHNICAL_FIELDS = new Set([
  'agent_id', 'task_id', 'workspace_path', '_workspace_path',
  'duration_ms', 'success', 'verification_score', 'iterations',
  'output_files', 'agentid', 'taskid', 'workspacepath',
  'durationms', 'verificationscore', 'outputfiles'
]);

/**
 * 过滤对象中的技术字段
 */
function filterTechnicalFields(obj: Record<string, unknown>): Record<string, unknown> {
  return Object.fromEntries(
    Object.entries(obj).filter(([key]) => {
      const normalizedKey = key.toLowerCase().replace(/_/g, '');
      return !TECHNICAL_FIELDS.has(normalizedKey) && !key.startsWith('_');
    })
  );
}

/**
 * 检查值是否为简单值（非嵌套对象）
 */
function isSimpleValue(value: unknown): boolean {
  if (value === null || value === undefined) return true;
  if (typeof value !== 'object') return true;
  if (Array.isArray(value)) {
    return value.every(item => typeof item !== 'object' || item === null);
  }
  return false;
}

/**
 * 检查对象是否为简单对象（所有值都是简单值）
 */
function isSimpleObject(obj: object): boolean {
  if (Array.isArray(obj)) return false;
  return Object.values(obj).every(isSimpleValue);
}

/**
 * 格式化键名（将 snake_case 或 camelCase 转为可读形式）
 */
function formatKeyName(key: string): string {
  // 如果是中文，直接返回
  if (/[\u4e00-\u9fa5]/.test(key)) {
    return key;
  }
  // 转换 snake_case 和 camelCase
  return key
    .replace(/_/g, ' ')
    .replace(/([a-z])([A-Z])/g, '$1 $2')
    .replace(/\b\w/g, c => c.toUpperCase());
}

/**
 * 格式化简单值
 */
function formatSimpleValue(value: unknown): string {
  if (value === null || value === undefined) {
    return '*无*';
  }
  if (typeof value === 'boolean') {
    return value ? '是' : '否';
  }
  if (typeof value === 'number') {
    // 格式化数字，保留最多4位小数
    if (Number.isInteger(value)) {
      return value.toLocaleString();
    }
    return value.toFixed(4).replace(/\.?0+$/, '');
  }
  if (typeof value === 'string') {
    return value;
  }
  // 处理数组
  if (Array.isArray(value)) {
    if (value.length === 0) return '(空列表)';
    if (value.length <= 3 && value.every(item => typeof item !== 'object' || item === null)) {
      return value.map(formatSimpleValue).join(', ');
    }
    return `[${value.length} 项]`;
  }
  // 处理对象
  if (typeof value === 'object') {
    const keys = Object.keys(value as object);
    if (keys.length === 0) return '(空)';
    if (keys.length <= 2) {
      // 递归格式化，但避免无限递归
      return keys.map(k => {
        const v = (value as Record<string, unknown>)[k];
        if (typeof v === 'object' && v !== null) {
          return `${k}: {${Object.keys(v as object).length} 字段}`;
        }
        return `${k}: ${formatSimpleValue(v)}`;
      }).join(', ');
    }
    return `{${keys.length} 字段}`;
  }
  return String(value);
}

/**
 * 格式化数组为 Markdown 列表
 */
function formatArrayToMarkdown(arr: unknown[], indent: number = 0): string {
  if (arr.length === 0) {
    return '*空列表*';
  }

  const prefix = '  '.repeat(indent);

  // 简单值数组：无序列表
  if (arr.every(item => typeof item !== 'object' || item === null)) {
    return arr.map(item => `${prefix}- ${formatSimpleValue(item)}`).join('\n');
  }

  // 对象数组：编号列表
  return arr.map((item, index) => {
    if (typeof item === 'object' && item !== null) {
      const objMarkdown = formatObjectToMarkdown(item as object, indent + 1);
      return `${prefix}${index + 1}. \n${objMarkdown}`;
    }
    return `${prefix}${index + 1}. ${formatSimpleValue(item)}`;
  }).join('\n');
}

/**
 * 格式化对象为 Markdown
 */
function formatObjectToMarkdown(obj: object, indent: number = 0): string {
  if (obj === null) {
    return '*无输出*';
  }

  const entries = Object.entries(obj);
  if (entries.length === 0) {
    return '*空对象*';
  }

  const prefix = '  '.repeat(indent);
  const lines: string[] = [];

  // 先处理特殊字段
  const specialFields: string[] = [];
  const normalFields: Array<[string, unknown]> = [];

  for (const [key, value] of entries) {
    const lowerKey = key.toLowerCase();
    if (SUMMARY_FIELDS.some(f => lowerKey.includes(f))) {
      specialFields.unshift(`${prefix}**${formatKeyName(key)}**: ${formatSimpleValue(value)}`);
    } else if (HIGHLIGHT_FIELDS.some(f => lowerKey.includes(f))) {
      specialFields.push(`${prefix}> **${formatKeyName(key)}**: ${formatSimpleValue(value)}`);
    } else if (ERROR_FIELDS.some(f => lowerKey.includes(f))) {
      specialFields.push(`${prefix}⚠️ **${formatKeyName(key)}**: ${formatSimpleValue(value)}`);
    } else {
      normalFields.push([key, value]);
    }
  }

  lines.push(...specialFields);

  // 处理普通字段
  for (const [key, value] of normalFields) {
    if (value === null || value === undefined) {
      continue;
    }

    if (Array.isArray(value)) {
      lines.push(`${prefix}**${formatKeyName(key)}**:`);
      lines.push(formatArrayToMarkdown(value, indent + 1));
    } else if (typeof value === 'object') {
      // 嵌套对象
      if (isSimpleObject(value as object)) {
        lines.push(`${prefix}**${formatKeyName(key)}**:`);
        lines.push(formatObjectToMarkdown(value as object, indent + 1));
      } else {
        // 复杂嵌套对象，使用 JSON 代码块
        lines.push(`${prefix}**${formatKeyName(key)}**:`);
        lines.push(`${prefix}\`\`\`json`);
        lines.push(JSON.stringify(value, null, 2).split('\n').map(l => prefix + l).join('\n'));
        lines.push(`${prefix}\`\`\``);
      }
    } else {
      lines.push(`${prefix}- **${formatKeyName(key)}**: ${formatSimpleValue(value)}`);
    }
  }

  return lines.join('\n');
}

/**
 * 将任意输出转换为 Markdown 格式
 * @param output 输出数据（可以是字符串、对象、数组等）
 * @returns Markdown 格式的字符串
 */
export function formatOutputToMarkdown(output: unknown): string {
  if (output === null || output === undefined) {
    return '*无输出*';
  }

  // 字符串：直接返回（可能已经是 Markdown）
  if (typeof output === 'string') {
    if (output.trim() === '') {
      return '*空输出*';
    }
    return output;
  }

  // 数字、布尔值
  if (typeof output === 'number' || typeof output === 'boolean') {
    return formatSimpleValue(output);
  }

  // 数组
  if (Array.isArray(output)) {
    if (output.length === 0) {
      return '*空列表*';
    }
    return formatArrayToMarkdown(output);
  }

  // 对象
  if (typeof output === 'object') {
    return formatObjectToMarkdown(output as object);
  }

  // 其他类型
  return String(output);
}

/**
 * 生成输出的一句话摘要
 * @param output 输出数据
 * @returns 一句话摘要
 */
export function generateOutputSummary(output: unknown): string {
  if (output === null || output === undefined) {
    return '无输出';
  }

  if (typeof output === 'string') {
    const trimmed = output.trim();
    if (trimmed === '') return '空输出';
    // 取第一行或前80个字符
    const firstLine = trimmed.split('\n')[0];
    if (firstLine.length > 80) {
      return firstLine.substring(0, 77) + '...';
    }
    return firstLine;
  }

  if (typeof output === 'number') {
    return `结果: ${formatSimpleValue(output)}`;
  }

  if (typeof output === 'boolean') {
    return output ? '成功' : '失败';
  }

  if (Array.isArray(output)) {
    return `返回 ${output.length} 项结果`;
  }

  if (typeof output === 'object') {
    const obj = output as Record<string, unknown>;

    // 智能提取关键信息
    for (const field of HIGHLIGHT_FIELDS) {
      if (field in obj) {
        const value = obj[field];
        return `${formatKeyName(field)}: ${formatSimpleValue(value)}`;
      }
    }

    for (const field of SUMMARY_FIELDS) {
      if (field in obj) {
        const value = String(obj[field]);
        return value.length > 80 ? value.substring(0, 77) + '...' : value;
      }
    }

    for (const field of ERROR_FIELDS) {
      if (field in obj) {
        return `错误: ${formatSimpleValue(obj[field])}`;
      }
    }

    // 返回字段数量
    const keys = Object.keys(obj);
    if (keys.length === 0) return '空对象';
    if (keys.length <= 3) {
      return keys.map(k => formatKeyName(k)).join(', ');
    }
    return `包含 ${keys.length} 个字段`;
  }

  return String(output).substring(0, 80);
}

export interface FormatNodeOutputResult {
  summary: string;
  narrative: string | null;
  highlights: string[] | null;
  markdown: string;
}

/**
 * 将节点输出格式化为三层展示结构（优先使用 narrative 字段）
 * @param output 节点输出（可为含 summary/narrative/data/highlights 的对象或任意类型）
 * @returns 用于三层展示的 { summary, narrative, highlights, markdown }
 */
export function formatNodeOutput(output: unknown): FormatNodeOutputResult {
  if (output === null || output === undefined) {
    return {
      summary: '无输出',
      narrative: null,
      highlights: null,
      markdown: '*无输出*',
    };
  }

  if (typeof output === 'object' && output !== null) {
    const obj = output as Record<string, unknown>;

    // 过滤技术字段
    const filteredObj = filterTechnicalFields(obj);

    // 提取 summary，确保是字符串
    let summary: string | null = null;
    if (typeof obj.summary === 'string') {
      summary = obj.summary;
      // 清洗 markdown 代码块标记
      if (summary.trim().startsWith('```')) {
        summary = null;
      }
    }
    if (!summary) {
      // 从 data 或过滤后的对象生成摘要
      const dataForSummary = obj.data ?? filteredObj;
      summary = generateOutputSummary(dataForSummary);
    }

    const narrative = typeof obj.narrative === 'string' ? obj.narrative : null;
    const highlights = Array.isArray(obj.highlights)
      ? (obj.highlights as unknown[]).map((x) => String(x))
      : null;

    // 优先使用 data 字段，否则使用过滤后的对象
    const data = obj.data !== undefined ? obj.data : filteredObj;
    const markdown = formatOutputToMarkdown(data);

    return {
      summary: summary || '执行完成',
      narrative: narrative || null,
      highlights,
      markdown,
    };
  }

  return {
    summary: generateOutputSummary(output),
    narrative: null,
    highlights: null,
    markdown: formatOutputToMarkdown(output),
  };
}

/**
 * 格式化持续时间
 * @param ms 毫秒数
 * @returns 格式化的时间字符串
 */
export function formatDuration(ms: number): string {
  if (ms < 1000) {
    return `${ms}ms`;
  }
  if (ms < 60000) {
    return `${(ms / 1000).toFixed(1)}s`;
  }
  const minutes = Math.floor(ms / 60000);
  const seconds = ((ms % 60000) / 1000).toFixed(0);
  return `${minutes}m ${seconds}s`;
}

/**
 * 格式化进度百分比
 * @param completed 已完成数量
 * @param total 总数量
 * @returns 百分比字符串
 */
export function formatProgress(completed: number, total: number): number {
  if (total === 0) return 0;
  return Math.round((completed / total) * 100);
}

/**
 * 开始节点输入参数的格式化结果
 */
export interface StartNodeInputResult {
  summary: string;  // 一句话摘要，如 "分析标的: 腾讯控股"
  params: Array<{
    label: string;  // 参数标签，如 "分析标的"
    value: string;  // 参数值，如 "腾讯控股 (00700.HK)"
  }>;
}

// 常见输入参数的中文映射
const INPUT_PARAM_LABELS: Record<string, string> = {
  // 股票/投资相关
  'stock': '股票',
  'stock_code': '股票代码',
  'stock_name': '股票名称',
  'symbol': '代码',
  'ticker': '股票代码',
  'target': '分析标的',
  'company': '公司',
  'company_name': '公司名称',

  // 时间相关
  'date': '日期',
  'start_date': '开始日期',
  'end_date': '结束日期',
  'date_range': '日期范围',
  'period': '周期',
  'year': '年份',
  'quarter': '季度',
  'month': '月份',

  // 通用参数
  'query': '查询',
  'keyword': '关键词',
  'keywords': '关键词',
  'topic': '主题',
  'subject': '主题',
  'input': '输入',
  'task': '任务',
  'instruction': '指令',
  'prompt': '提示',
  'question': '问题',

  // 配置相关
  'limit': '数量限制',
  'count': '数量',
  'max_results': '最大结果数',
  'language': '语言',
  'region': '地区',
  'market': '市场',
};

/**
 * 获取参数的友好标签
 */
function getParamLabel(key: string): string {
  // 先检查精确匹配
  const lowerKey = key.toLowerCase();
  if (INPUT_PARAM_LABELS[lowerKey]) {
    return INPUT_PARAM_LABELS[lowerKey];
  }

  // 检查是否包含中文，如果是则直接使用
  if (/[\u4e00-\u9fa5]/.test(key)) {
    return key;
  }

  // 转换 snake_case 为可读格式
  return formatKeyName(key);
}

/**
 * 格式化参数值为可读字符串
 */
function formatParamValue(value: unknown): string {
  if (value === null || value === undefined) {
    return '(未指定)';
  }

  if (typeof value === 'string') {
    return value || '(空)';
  }

  if (typeof value === 'number' || typeof value === 'boolean') {
    return formatSimpleValue(value);
  }

  if (Array.isArray(value)) {
    if (value.length === 0) return '(空列表)';
    // 简单值数组：用逗号连接
    if (value.every(item => typeof item !== 'object' || item === null)) {
      return value.map(formatSimpleValue).join(', ');
    }
    return `${value.length} 项`;
  }

  if (typeof value === 'object') {
    const keys = Object.keys(value as object);
    if (keys.length === 0) return '(空)';
    if (keys.length <= 3) {
      // 安全地格式化每个键值对，避免嵌套对象显示为 [object Object]
      return keys.map(k => {
        const v = (value as Record<string, unknown>)[k];
        return `${k}: ${formatSimpleValue(v)}`;
      }).join(', ');
    }
    return `${keys.length} 个字段`;
  }

  return String(value);
}

/**
 * 格式化开始节点的输入参数
 * @param output 开始节点的 fullOutput
 * @returns 格式化结果，如果没有用户输入则返回 null
 */
export function formatStartNodeInput(output: unknown): StartNodeInputResult | null {
  if (!output || typeof output !== 'object') {
    return null;
  }

  const obj = output as Record<string, unknown>;
  const context = obj.context as Record<string, unknown> | null;

  if (!context) {
    return null;
  }

  // 系统字段列表（不展示给用户）
  const systemFields = new Set(['workflow_id', 'global_context', 'config']);

  // 提取用户输入参数
  const userParams: Array<{ label: string; value: string; key: string }> = [];

  for (const [key, value] of Object.entries(context)) {
    if (systemFields.has(key)) {
      // 特殊处理 global_context：如果不为空则提取其中的参数
      if (key === 'global_context' && value && typeof value === 'object') {
        const gc = value as Record<string, unknown>;
        for (const [gcKey, gcValue] of Object.entries(gc)) {
          if (gcValue != null && JSON.stringify(gcValue) !== '{}' && JSON.stringify(gcValue) !== '[]') {
            userParams.push({
              key: gcKey,
              label: getParamLabel(gcKey),
              value: formatParamValue(gcValue),
            });
          }
        }
      }
      continue;
    }

    // 跳过空值
    if (value == null || JSON.stringify(value) === '{}' || JSON.stringify(value) === '[]') {
      continue;
    }

    userParams.push({
      key,
      label: getParamLabel(key),
      value: formatParamValue(value),
    });
  }

  // 如果没有用户输入参数，返回 null
  if (userParams.length === 0) {
    return null;
  }

  // 生成摘要（取第一个参数作为摘要）
  const primaryParam = userParams[0];
  const summary = userParams.length === 1
    ? `${primaryParam.label}: ${primaryParam.value}`
    : `${primaryParam.label}: ${primaryParam.value} 等 ${userParams.length} 项`;

  return {
    summary,
    params: userParams.map(({ label, value }) => ({ label, value })),
  };
}
