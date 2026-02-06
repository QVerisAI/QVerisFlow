/**
 * 输出格式化工具
 * 将各种类型的节点输出转换为可读的 Markdown 格式
 */

// 特殊字段名称映射（用于智能识别）
const HIGHLIGHT_FIELDS = ['recommendation', 'suggestion', '建议', '推荐'];
const SUMMARY_FIELDS = ['summary', 'conclusion', 'result', '摘要', '结论', '结果'];
const ERROR_FIELDS = ['error', 'exception', '错误', '异常'];
const ANALYSIS_FIELDS = ['analysis', 'evaluation', '分析', '评估'];

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
