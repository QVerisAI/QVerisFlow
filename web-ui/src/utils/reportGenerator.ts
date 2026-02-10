/**
 * 工作流执行报告生成器
 *
 * 将 ExecutionSummary 数据转换为独立的 HTML 报告文档，
 * 在新窗口中打开，支持 PDF 导出。
 *
 * 设计理念：极简主义 + 极致审美
 * - 内容即设计，排版即层次，留白即高级
 * - 隐藏所有技术细节（node_id、workflow_id、JSON 结构等）
 * - 开始/结束节点不展示
 * - 已有叙述的步骤不重复展示原始数据
 */

import type { ExecutionSummary, ExecutionNodeResult, NodeActivity } from '../types';

// ─── 报告类型 ────────────────────────────────────────────────

/** 报告类型：result = 结果报告（最终成品），process = 过程报告（执行步骤） */
export type ReportType = 'result' | 'process';

// ─── 技术字段过滤 ──────────────────────────────────────────

const TECHNICAL_FIELDS = new Set([
  'agent_id', 'task_id', 'workspace_path', '_workspace_path',
  'duration_ms', 'success', 'verification_score', 'iterations',
  'output_files', 'workflow_id', 'global_context', 'config',
  'node_id', 'status', 'context', 'final_output',
]);

/** 已经被 narrative/highlights 展示过的顶层字段，详细数据中不再重复 */
const ALREADY_SHOWN_FIELDS = new Set([
  'summary', 'narrative', 'highlights', 'data_format', 'dataformat',
]);

function filterTechnicalFields(obj: Record<string, unknown>): Record<string, unknown> {
  return Object.fromEntries(
    Object.entries(obj).filter(([key]) => {
      const k = key.toLowerCase().replace(/_/g, '');
      return !TECHNICAL_FIELDS.has(key.toLowerCase())
        && !key.startsWith('_')
        && !TECHNICAL_FIELDS.has(k)
        && !ALREADY_SHOWN_FIELDS.has(key.toLowerCase());
    })
  );
}

// ─── 数据格式化工具 ────────────────────────────────────────

function escapeHtml(str: string): string {
  return str
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function formatDurationReadable(ms: number): string {
  if (ms < 10) return '< 0.1 秒';
  if (ms < 1000) {
    return `${(ms / 1000).toFixed(1)} 秒`;
  }
  if (ms < 60000) {
    const s = (ms / 1000).toFixed(1);
    return `${s} 秒`;
  }
  const min = Math.floor(ms / 60000);
  const sec = Math.round((ms % 60000) / 1000);
  return sec > 0 ? `${min} 分 ${sec} 秒` : `${min} 分钟`;
}

function formatDateReadable(isoStr: string): string {
  try {
    const d = new Date(isoStr);
    const year = d.getFullYear();
    const month = d.getMonth() + 1;
    const day = d.getDate();
    const h = String(d.getHours()).padStart(2, '0');
    const m = String(d.getMinutes()).padStart(2, '0');
    const s = String(d.getSeconds()).padStart(2, '0');
    return `${year}年${month}月${day}日 ${h}:${m}:${s}`;
  } catch {
    return isoStr;
  }
}

function formatTimeOnly(isoStr?: string): string {
  if (!isoStr) return '';
  try {
    const d = new Date(isoStr);
    const h = String(d.getHours()).padStart(2, '0');
    const m = String(d.getMinutes()).padStart(2, '0');
    const s = String(d.getSeconds()).padStart(2, '0');
    return `${h}:${m}:${s}`;
  } catch {
    return '';
  }
}

function formatDateShort(isoStr: string): string {
  try {
    const d = new Date(isoStr);
    const year = d.getFullYear();
    const month = d.getMonth() + 1;
    const day = d.getDate();
    return `${year}年${month}月${day}日`;
  } catch {
    return isoStr;
  }
}

function formatKeyLabel(key: string): string {
  if (/[\u4e00-\u9fa5]/.test(key)) return key;
  return key
    .replace(/_/g, ' ')
    .replace(/([a-z])([A-Z])/g, '$1 $2')
    .replace(/\b\w/g, c => c.toUpperCase());
}

function formatPrimitive(value: unknown): string {
  if (value === null || value === undefined) return '-';
  if (typeof value === 'boolean') return value ? '是' : '否';
  if (typeof value === 'number') {
    if (Number.isInteger(value)) return value.toLocaleString();
    return value.toFixed(4).replace(/\.?0+$/, '');
  }
  return String(value);
}

// ─── Markdown → HTML 转换器（用于 data_format="markdown" 的报告渲染） ──

/**
 * 轻量级 Markdown → HTML 转换器
 *
 * 支持：## / ### 标题、**加粗**、- / * 无序列表、1. 有序列表、
 *       | col | col | 表格、段落（空行分隔）。
 *
 * 不依赖任何外部库。
 */
function markdownToHtml(md: string): string {
  if (!md) return '';

  const lines = md.split('\n');
  const htmlParts: string[] = [];
  let i = 0;

  const inlineFmt = (text: string): string => {
    return escapeHtml(text)
      .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
      .replace(/`(.+?)`/g, '<code>$1</code>');
  };

  while (i < lines.length) {
    const line = lines[i];

    // --- 空行 → 段落间隔 ---
    if (line.trim() === '') { i++; continue; }

    // --- 标题 ---
    const headingMatch = line.match(/^(#{2,5})\s+(.+)$/);
    if (headingMatch) {
      const level = headingMatch[1].length;          // 2-5
      const tag = level <= 2 ? 'h4' : 'h5';
      htmlParts.push(`<${tag} class="section-block-title">${inlineFmt(headingMatch[2])}</${tag}>`);
      i++;
      continue;
    }

    // --- 表格 ---
    if (line.includes('|') && i + 1 < lines.length && /^\|?\s*[-:]+/.test(lines[i + 1])) {
      const parseRow = (row: string): string[] =>
        row.replace(/^\|/, '').replace(/\|$/, '').split('|').map(c => c.trim());

      const headers = parseRow(line);
      i += 2; // skip header + separator

      const bodyRows: string[][] = [];
      while (i < lines.length && lines[i].includes('|') && lines[i].trim() !== '') {
        bodyRows.push(parseRow(lines[i]));
        i++;
      }

      const thead = `<tr>${headers.map(h => `<th>${inlineFmt(h)}</th>`).join('')}</tr>`;
      const tbody = bodyRows.map(row =>
        `<tr>${row.map(c => `<td>${inlineFmt(c)}</td>`).join('')}</tr>`
      ).join('');
      htmlParts.push(`<table class="data-table"><thead>${thead}</thead><tbody>${tbody}</tbody></table>`);
      continue;
    }

    // --- 无序列表 ---
    if (/^\s*[-*]\s+/.test(line)) {
      const items: string[] = [];
      while (i < lines.length && /^\s*[-*]\s+/.test(lines[i])) {
        items.push(lines[i].replace(/^\s*[-*]\s+/, ''));
        i++;
      }
      htmlParts.push(`<ul class="bullet-list">${items.map(it => `<li>${inlineFmt(it)}</li>`).join('')}</ul>`);
      continue;
    }

    // --- 有序列表 ---
    if (/^\s*\d+\.\s+/.test(line)) {
      const items: string[] = [];
      while (i < lines.length && /^\s*\d+\.\s+/.test(lines[i])) {
        items.push(lines[i].replace(/^\s*\d+\.\s+/, ''));
        i++;
      }
      htmlParts.push(`<ol class="bullet-list">${items.map(it => `<li>${inlineFmt(it)}</li>`).join('')}</ol>`);
      continue;
    }

    // --- 普通段落（收集连续非空行） ---
    const paraLines: string[] = [];
    while (i < lines.length && lines[i].trim() !== '' && !/^#{2,5}\s/.test(lines[i]) && !/^\s*[-*]\s+/.test(lines[i]) && !/^\s*\d+\.\s+/.test(lines[i]) && !(lines[i].includes('|') && i + 1 < lines.length && /^\|?\s*[-:]+/.test(lines[i + 1] || ''))) {
      paraLines.push(lines[i]);
      i++;
    }
    if (paraLines.length > 0) {
      htmlParts.push(`<p>${inlineFmt(paraLines.join(' '))}</p>`);
    }
  }

  return htmlParts.join('\n');
}

/**
 * 检测 fullOutput 中 data 字段的格式
 * 优先级：显式 data_format > 类型推断
 */
function detectDataFormat(output: unknown): 'json' | 'markdown' {
  if (output && typeof output === 'object') {
    const obj = output as Record<string, unknown>;
    // 顶层检查
    if (obj.data_format === 'markdown' || obj.dataFormat === 'markdown') return 'markdown';
    if (obj.data_format === 'json' || obj.dataFormat === 'json') return 'json';
    // 处理嵌套 result 结构（历史数据可能包含原始 agent 输出 {result: {summary, data, data_format, ...}}）
    const inner = (typeof obj.result === 'object' && obj.result !== null)
      ? obj.result as Record<string, unknown>
      : null;
    if (inner) {
      if (inner.data_format === 'markdown' || inner.dataFormat === 'markdown') return 'markdown';
      if (inner.data_format === 'json' || inner.dataFormat === 'json') return 'json';
      if (typeof inner.data === 'string') return 'markdown';
    }
    // 自动检测：如果 data 是字符串，视为 markdown
    if (typeof obj.data === 'string') return 'markdown';
  }
  return 'json';
}

// ─── 递归结构化数据渲染器 ──────────────────────────────────

function isPrimitive(value: unknown): boolean {
  return value === null || value === undefined || typeof value !== 'object';
}

function isFlatObject(obj: Record<string, unknown>): boolean {
  return Object.values(obj).every(isPrimitive);
}

function isHomogeneousObjectArray(arr: unknown[]): boolean {
  if (arr.length < 1 || arr.length > 50) return false;
  if (!arr.every(item => typeof item === 'object' && item !== null && !Array.isArray(item))) return false;
  const keys0 = Object.keys(arr[0] as object).sort().join(',');
  return arr.every(item => {
    const keys = Object.keys(item as object).sort().join(',');
    return keys === keys0;
  });
}

function renderStructuredData(value: unknown, depth: number = 0): string {
  if (value === null || value === undefined) return '';
  if (typeof value === 'string') {
    const escaped = escapeHtml(value);
    if (value.includes('\n')) {
      return `<div class="text-block">${escaped.replace(/\n/g, '<br>')}</div>`;
    }
    return `<span class="text-inline">${escaped}</span>`;
  }
  if (typeof value === 'number' || typeof value === 'boolean') {
    return `<span class="text-inline">${formatPrimitive(value)}</span>`;
  }

  if (Array.isArray(value)) {
    if (value.length === 0) return '';
    if (value.every(isPrimitive)) {
      return `<ul class="bullet-list">${value.map(v => `<li>${escapeHtml(formatPrimitive(v))}</li>`).join('')}</ul>`;
    }
    if (isHomogeneousObjectArray(value)) {
      return renderTable(value as Record<string, unknown>[]);
    }
    return `<div class="numbered-list">${value.map((item, i) =>
      `<div class="numbered-item"><span class="numbered-idx">${i + 1}.</span><div class="numbered-content">${renderStructuredData(item, depth + 1)}</div></div>`
    ).join('')}</div>`;
  }

  if (typeof value === 'object') {
    const obj = value as Record<string, unknown>;
    const entries = Object.entries(obj).filter(([, v]) => v !== null && v !== undefined);
    if (entries.length === 0) return '';

    if (isFlatObject(obj)) {
      return renderKvTable(entries);
    }

    return entries.map(([key, val]) => {
      const label = formatKeyLabel(key);
      if (isPrimitive(val)) {
        return `<div class="kv-inline"><span class="kv-inline-label">${escapeHtml(label)}</span><span class="kv-inline-value">${escapeHtml(formatPrimitive(val))}</span></div>`;
      }
      const tagName = depth < 1 ? 'h4' : 'h5';
      const content = renderStructuredData(val, depth + 1);
      if (!content) return '';
      return `<div class="section-block"><${tagName} class="section-block-title">${escapeHtml(label)}</${tagName}>${content}</div>`;
    }).join('');
  }

  return escapeHtml(String(value));
}

function renderKvTable(entries: [string, unknown][]): string {
  const rows = entries.map(([key, val]) =>
    `<tr><td class="kv-label">${escapeHtml(formatKeyLabel(key))}</td><td class="kv-value">${escapeHtml(formatPrimitive(val))}</td></tr>`
  ).join('');
  return `<table class="kv-table"><tbody>${rows}</tbody></table>`;
}

function renderTable(rows: Record<string, unknown>[]): string {
  if (rows.length === 0) return '';
  const keys = Object.keys(rows[0]);
  const thead = `<tr>${keys.map(k => `<th>${escapeHtml(formatKeyLabel(k))}</th>`).join('')}</tr>`;
  const tbody = rows.map(row =>
    `<tr>${keys.map(k => `<td>${escapeHtml(formatPrimitive(row[k]))}</td>`).join('')}</tr>`
  ).join('');
  return `<table class="data-table"><thead>${thead}</thead><tbody>${tbody}</tbody></table>`;
}

function renderOutputData(output: unknown, formatHint?: 'json' | 'markdown'): string {
  if (output === null || output === undefined) return '';
  if (typeof output !== 'object') return renderStructuredData(output);

  let obj = output as Record<string, unknown>;
  // 处理嵌套 result 结构：原始 agent 输出 {agent_id, result: {summary, data, ...}, ...}
  if (typeof obj.result === 'object' && obj.result !== null) {
    const inner = obj.result as Record<string, unknown>;
    if ('data' in inner || 'summary' in inner) {
      obj = inner;
    }
  }
  const dataFormat = formatHint || detectDataFormat(obj);
  const filtered = filterTechnicalFields(obj);

  const data = filtered.data !== undefined ? filtered.data : filtered;
  if (data === null || data === undefined) return '';

  // Markdown 路径：data 是字符串，直接转 HTML
  if (dataFormat === 'markdown' && typeof data === 'string') {
    return markdownToHtml(data);
  }

  // JSON 路径：保持原有结构化渲染
  if (typeof data === 'object' && Object.keys(data as object).length === 0) return '';
  return renderStructuredData(data);
}

// ─── 节点过滤（开始/结束节点不展示） ────────────────────────

/** 判断是否为开始节点 */
function isStartNode(node: ExecutionNodeResult): boolean {
  const id = (node.nodeId ?? '').toLowerCase();
  const name = (node.nodeName ?? '').toLowerCase();
  return id === 'start' || name === '开始节点' || name === 'start';
}

/** 判断是否为结束节点 */
function isEndNode(node: ExecutionNodeResult): boolean {
  const id = (node.nodeId ?? '').toLowerCase();
  const name = (node.nodeName ?? '').toLowerCase();
  return id === 'end' || name === '结束节点' || name === 'end'
    || id.startsWith('end_') || name.includes('结束');
}

/** 判断是否为基础设施节点（开始/结束），这些节点不在报告中展示 */
function isInfraNode(node: ExecutionNodeResult): boolean {
  return isStartNode(node) || isEndNode(node);
}

/** 判断节点是否应在报告中展示 */
function shouldShowInReport(node: ExecutionNodeResult): boolean {
  return !isInfraNode(node);
}

/** 获取报告中可见的业务节点 */
function getVisibleNodes(summary: ExecutionSummary): ExecutionNodeResult[] {
  return summary.nodeResults.filter(shouldShowInReport);
}

// ─── 智能报告标题 ──────────────────────────────────────────

/**
 * 构建干净的报告标题
 * 只使用 workflowName（人类可读名称），不拼接任何 context 值
 */
function buildReportTitle(summary: ExecutionSummary): string {
  const name = summary.workflowName || '';
  if (!name) return '工作流执行报告';
  // 去掉名称中可能出现的技术后缀（如 _workflow、_v2 等）
  return name;
}

// ─── 获取节点的展示文本 ────────────────────────────────────

function getNodeNarrative(node: ExecutionNodeResult): string {
  if (node.outputNarrative) return escapeHtml(node.outputNarrative);
  if (node.outputSummary) return escapeHtml(node.outputSummary);
  if (node.outputPreview) return escapeHtml(node.outputPreview);

  if (node.fullOutput && typeof node.fullOutput === 'object') {
    const obj = node.fullOutput as Record<string, unknown>;
    if (typeof obj.narrative === 'string') return escapeHtml(obj.narrative);
    if (typeof obj.summary === 'string') return escapeHtml(obj.summary);
  }

  return '';
}

function getNodeHighlights(node: ExecutionNodeResult): string[] {
  if (node.outputHighlights && node.outputHighlights.length > 0) return node.outputHighlights;
  if (node.fullOutput && typeof node.fullOutput === 'object') {
    const obj = node.fullOutput as Record<string, unknown>;
    if (Array.isArray(obj.highlights)) return obj.highlights.map(String);
  }
  return [];
}

/** 检查节点是否有叙述性内容（narrative 或 highlights） */
function hasNarrativeContent(node: ExecutionNodeResult): boolean {
  return getNodeNarrative(node) !== '' || getNodeHighlights(node).length > 0;
}

// ─── CSS 样式 ──────────────────────────────────────────────

function getReportStyles(): string {
  return `
    * { margin: 0; padding: 0; box-sizing: border-box; }

    body {
      font-family: -apple-system, "PingFang SC", "Noto Sans SC", "Helvetica Neue", Arial, sans-serif;
      font-size: 16px;
      line-height: 1.8;
      color: #1e293b;
      background: #fff;
      -webkit-font-smoothing: antialiased;
      -moz-osx-font-smoothing: grayscale;
    }

    .report-container {
      max-width: 720px;
      margin: 0 auto;
      padding: 80px 40px 60px;
    }

    /* ── 工具栏 ── */
    .toolbar {
      position: fixed;
      top: 0;
      left: 0;
      right: 0;
      z-index: 100;
      display: flex;
      justify-content: space-between;
      align-items: center;
      padding: 12px 32px;
      background: rgba(255, 255, 255, 0.92);
      backdrop-filter: blur(12px);
      -webkit-backdrop-filter: blur(12px);
      border-bottom: 1px solid #f1f5f9;
    }
    .toolbar-btn {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      padding: 8px 20px;
      border: none;
      border-radius: 8px;
      font-size: 14px;
      font-weight: 500;
      cursor: pointer;
      transition: all 0.15s;
    }
    .toolbar-btn-back {
      background: none;
      color: #64748b;
    }
    .toolbar-btn-back:hover { color: #1e293b; }
    .toolbar-btn-print {
      background: #f1f5f9;
      color: #475569;
    }
    .toolbar-btn-print:hover { background: #e2e8f0; }
    .toolbar-btn-export {
      background: #1e293b;
      color: #fff;
    }
    .toolbar-btn-export:hover { background: #334155; }

    /* ── 标题区 ── */
    .report-title {
      font-size: 28px;
      font-weight: 500;
      color: #1e293b;
      letter-spacing: -0.5px;
      margin-bottom: 6px;
      line-height: 1.4;
    }
    .report-subtitle {
      font-size: 14px;
      color: #94a3b8;
      margin-bottom: 4px;
    }
    .report-meta {
      font-size: 13px;
      color: #94a3b8;
      margin-bottom: 48px;
    }

    /* ── 分隔线 ── */
    .divider {
      border: none;
      border-top: 1px solid #e2e8f0;
      margin: 48px 0;
    }

    /* ── 执行状态 ── */
    .status-bar {
      display: flex;
      align-items: center;
      gap: 16px;
      padding: 16px 20px;
      background: #f8fafc;
      border-radius: 10px;
      font-size: 14px;
      color: #475569;
      margin-bottom: 48px;
      flex-wrap: wrap;
    }
    .status-dot {
      width: 8px;
      height: 8px;
      border-radius: 50%;
      flex-shrink: 0;
    }
    .status-dot-success { background: #10b981; }
    .status-dot-failed { background: #dc2626; }
    .status-dot-cancelled { background: #f59e0b; }
    .status-text { font-weight: 500; }
    .status-detail { color: #94a3b8; }

    /* ── 摘要区 ── */
    .summary-text {
      font-size: 16px;
      line-height: 1.8;
      color: #334155;
      margin-bottom: 20px;
    }
    .findings {
      margin: 0 0 0 4px;
      padding: 0;
      list-style: none;
    }
    .findings li {
      font-size: 14px;
      line-height: 1.7;
      color: #64748b;
      padding-left: 16px;
      position: relative;
      margin-bottom: 4px;
    }
    .findings li::before {
      content: "\\00B7";
      position: absolute;
      left: 0;
      font-weight: bold;
      color: #94a3b8;
    }

    /* ── 章节标题 ── */
    .section-label {
      font-size: 12px;
      font-weight: 600;
      letter-spacing: 2px;
      text-transform: uppercase;
      color: #94a3b8;
      margin-bottom: 32px;
    }

    /* ── 步骤卡片 ── */
    .step-card {
      margin-bottom: 56px;
      page-break-inside: avoid;
    }
    .step-number {
      font-size: 48px;
      font-weight: 300;
      color: #e2e8f0;
      letter-spacing: -2px;
      line-height: 1;
      margin-bottom: 8px;
    }
    .step-header {
      display: flex;
      justify-content: space-between;
      align-items: baseline;
      margin-bottom: 2px;
    }
    .step-name {
      font-size: 18px;
      font-weight: 500;
      color: #1e293b;
    }
    .step-status {
      font-size: 13px;
      color: #94a3b8;
      white-space: nowrap;
    }
    .step-status-success { color: #64748b; }
    .step-status-failed { color: #dc2626; }
    .step-name-failed { color: #dc2626; }

    .step-divider {
      border: none;
      border-top: 1px dashed #e2e8f0;
      margin: 12px 0 16px;
    }

    .step-narrative {
      font-size: 15px;
      line-height: 1.8;
      color: #334155;
      margin-bottom: 16px;
    }

    .step-highlights {
      margin: 0 0 16px 4px;
      padding: 0;
      list-style: none;
    }
    .step-highlights li {
      font-size: 13px;
      line-height: 1.7;
      color: #64748b;
      padding-left: 16px;
      position: relative;
      margin-bottom: 2px;
    }
    .step-highlights li::before {
      content: "\\00B7";
      position: absolute;
      left: 0;
      font-weight: bold;
      color: #94a3b8;
    }

    /* ── 错误信息 ── */
    .error-block {
      font-size: 14px;
      color: #dc2626;
      padding-left: 16px;
      border-left: 2px solid #dc2626;
      margin: 12px 0;
    }

    /* ── 执行过程时间线 ── */
    .timeline-label {
      font-size: 12px;
      font-weight: 600;
      letter-spacing: 1px;
      color: #cbd5e1;
      margin-bottom: 10px;
    }
    .timeline {
      margin-bottom: 16px;
    }
    .timeline-item {
      display: flex;
      gap: 12px;
      font-size: 13px;
      line-height: 1.6;
      padding: 3px 0;
    }
    .timeline-time {
      font-family: "SF Mono", "Fira Code", "Consolas", monospace;
      font-size: 12px;
      color: #cbd5e1;
      min-width: 56px;
      flex-shrink: 0;
    }
    .timeline-icon {
      flex-shrink: 0;
      width: 16px;
      text-align: center;
      color: #94a3b8;
      font-size: 12px;
    }
    .timeline-text {
      color: #64748b;
    }
    .timeline-tool { color: #94a3b8; }
    .timeline-detail {
      color: #94a3b8;
      font-size: 12px;
      margin-left: 84px;
      margin-top: -2px;
      padding-bottom: 2px;
    }

    /* ── 结构化数据渲染 ── */

    .section-block {
      margin: 16px 0;
    }
    .section-block-title {
      font-size: 14px;
      font-weight: 600;
      color: #475569;
      margin-bottom: 8px;
      padding-bottom: 4px;
      border-bottom: 1px solid #f1f5f9;
    }
    h5.section-block-title {
      font-size: 13px;
      font-weight: 500;
      color: #64748b;
      border-bottom: none;
      margin-bottom: 4px;
    }

    .kv-inline {
      display: flex;
      gap: 8px;
      padding: 3px 0;
      font-size: 14px;
      line-height: 1.6;
    }
    .kv-inline-label {
      color: #94a3b8;
      flex-shrink: 0;
      min-width: 60px;
    }
    .kv-inline-label::after { content: "\\FF1A"; }
    .kv-inline-value {
      color: #334155;
      word-break: break-word;
    }

    .kv-table {
      width: 100%;
      border-collapse: collapse;
      font-size: 14px;
      margin: 8px 0;
    }
    .kv-table td {
      padding: 6px 12px 6px 0;
      vertical-align: top;
      border-bottom: 1px solid #f1f5f9;
      line-height: 1.6;
    }
    .kv-table tr:last-child td {
      border-bottom: none;
    }
    .kv-label {
      color: #94a3b8;
      white-space: nowrap;
      width: 1%;
      padding-right: 16px;
    }
    .kv-value {
      color: #334155;
      word-break: break-word;
    }

    .data-table {
      width: 100%;
      border-collapse: collapse;
      font-size: 13px;
      margin: 8px 0;
    }
    .data-table th {
      text-align: left;
      padding: 8px 12px 8px 0;
      font-weight: 500;
      color: #94a3b8;
      border-bottom: 2px solid #e2e8f0;
      white-space: nowrap;
    }
    .data-table td {
      padding: 6px 12px 6px 0;
      color: #334155;
      border-bottom: 1px solid #f1f5f9;
      vertical-align: top;
      line-height: 1.5;
    }
    .data-table tr:last-child td {
      border-bottom: none;
    }

    .bullet-list {
      margin: 4px 0 4px 4px;
      padding: 0;
      list-style: none;
    }
    .bullet-list li {
      font-size: 14px;
      line-height: 1.6;
      color: #334155;
      padding-left: 16px;
      position: relative;
      margin-bottom: 2px;
    }
    .bullet-list li::before {
      content: "\\00B7";
      position: absolute;
      left: 0;
      font-weight: bold;
      color: #94a3b8;
    }

    .numbered-list {
      margin: 4px 0;
    }
    .numbered-item {
      display: flex;
      gap: 8px;
      padding: 4px 0;
    }
    .numbered-idx {
      color: #94a3b8;
      font-size: 13px;
      flex-shrink: 0;
      min-width: 20px;
    }
    .numbered-content {
      flex: 1;
      min-width: 0;
    }

    .text-block {
      font-size: 14px;
      line-height: 1.7;
      color: #334155;
      margin: 4px 0;
    }
    .text-inline {
      font-size: 14px;
      color: #334155;
    }

    /* ── Markdown 渲染内容 ── */
    .step-data p {
      font-size: 14px;
      line-height: 1.8;
      color: #334155;
      margin: 8px 0;
    }
    .step-data ol {
      margin: 4px 0 4px 4px;
      padding: 0;
      list-style: none;
      counter-reset: ol-counter;
    }
    .step-data ol li {
      font-size: 14px;
      line-height: 1.6;
      color: #334155;
      padding-left: 24px;
      position: relative;
      margin-bottom: 2px;
      counter-increment: ol-counter;
    }
    .step-data ol li::before {
      content: counter(ol-counter) ".";
      position: absolute;
      left: 0;
      color: #94a3b8;
      font-size: 13px;
    }
    .step-data code {
      font-family: "SF Mono", "Fira Code", "Consolas", monospace;
      font-size: 13px;
      background: #f1f5f9;
      padding: 1px 5px;
      border-radius: 3px;
      color: #475569;
    }

    /* ── 步骤详细数据容器 ── */
    .step-data {
      margin-top: 16px;
      padding: 16px 20px;
      background: #f8fafc;
      border-radius: 10px;
    }
    .step-data-label {
      font-size: 12px;
      font-weight: 600;
      letter-spacing: 1px;
      color: #cbd5e1;
      margin-bottom: 12px;
    }

    /* 折叠 */
    .detail-toggle {
      display: inline-block;
      font-size: 13px;
      color: #94a3b8;
      cursor: pointer;
      border: none;
      background: none;
      padding: 0;
      font-family: inherit;
      transition: color 0.15s;
    }
    .detail-toggle:hover { color: #64748b; }
    .detail-content {
      display: none;
    }
    .detail-content.open { display: block; }

    /* ── 结论区 ── */
    .conclusion-text {
      font-size: 16px;
      line-height: 1.8;
      color: #334155;
      margin-bottom: 20px;
    }

    /* ── 页脚 ── */
    .report-footer {
      text-align: center;
      font-size: 12px;
      color: #cbd5e1;
      padding-top: 20px;
    }

    /* ── 打印样式 ── */
    @page {
      margin: 0;   /* 去掉页面边距，浏览器默认页眉页脚（URL、日期、页码）就没有空间渲染 */
    }
    @media print {
      .no-print { display: none !important; }
      .report-container { padding: 20mm; max-width: 100%; }  /* 用 padding 代替 @page margin 控制内容边距 */
      body { padding: 0; margin: 0; }
      .step-card { break-inside: avoid; }
      .detail-content { display: block !important; }
      .detail-toggle { display: none; }
      .status-bar { background: #f8fafc !important; -webkit-print-color-adjust: exact; print-color-adjust: exact; }
      .status-dot { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
      .step-data { background: #f8fafc !important; -webkit-print-color-adjust: exact; print-color-adjust: exact; }

      /* 防止表格行、列表项在分页处被截断 */
      tr { break-inside: avoid; page-break-inside: avoid; }
      li { break-inside: avoid; page-break-inside: avoid; }
      .kv-table tr { break-inside: avoid; page-break-inside: avoid; }
      .data-table tr { break-inside: avoid; page-break-inside: avoid; }
      .bullet-list li { break-inside: avoid; page-break-inside: avoid; }
      .findings li { break-inside: avoid; page-break-inside: avoid; }
      .step-highlights li { break-inside: avoid; page-break-inside: avoid; }
      .numbered-item { break-inside: avoid; page-break-inside: avoid; }
      .section-block { break-inside: avoid; page-break-inside: avoid; }
      .kv-inline { break-inside: avoid; page-break-inside: avoid; }

      /* 控制孤行和寡行（确保段落至少有 3 行在页面开头或结尾） */
      p { orphans: 3; widows: 3; }
      .step-narrative { orphans: 3; widows: 3; }
      .summary-text { orphans: 3; widows: 3; }
      .conclusion-text { orphans: 3; widows: 3; }

      /* 表格尽量不分页（小表格），大表格允许行级分页但行本身不断开 */
      .kv-table { break-inside: avoid-page; }
      table { break-inside: auto; }
      thead { display: table-header-group; }  /* 表头在每页重复显示 */
      tfoot { display: table-footer-group; }
    }
  `;
}

// ─── HTML 渲染函数 ─────────────────────────────────────────

function renderToolbar(): string {
  return `
    <div class="toolbar no-print">
      <button class="toolbar-btn toolbar-btn-back" onclick="window.close()">\u2190 返回</button>
      <div style="display:flex;gap:8px;">
        <button class="toolbar-btn toolbar-btn-print" onclick="printReport()">打印</button>
        <button class="toolbar-btn toolbar-btn-export" onclick="exportPdf()">导出 PDF</button>
      </div>
    </div>
  `;
}

function renderHeader(summary: ExecutionSummary, reportType: ReportType): string {
  const title = buildReportTitle(summary);
  const visibleNodes = getVisibleNodes(summary);
  const totalDisplay = visibleNodes.length;
  const completedDisplay = visibleNodes.filter(n => n.status === 'completed' || n.status === 'success' as string).length;

  const duration = formatDurationReadable(summary.totalDurationMs);
  const dateStr = formatDateReadable(summary.startedAt);

  const subtitle = reportType === 'result' ? '执行结果报告' : '执行过程报告';

  return `
    <div class="report-title">${escapeHtml(title)}</div>
    <div class="report-subtitle">${subtitle}</div>
    <div class="report-meta">${dateStr} \u00B7 耗时 ${duration} \u00B7 ${completedDisplay}/${totalDisplay} 个步骤完成</div>
  `;
}

function renderStatusBar(summary: ExecutionSummary): string {
  const statusConfig: Record<string, { dot: string; text: string }> = {
    completed: { dot: 'status-dot-success', text: '执行成功' },
    failed: { dot: 'status-dot-failed', text: '执行失败' },
    cancelled: { dot: 'status-dot-cancelled', text: '已取消' },
  };
  const config = statusConfig[summary.status] || statusConfig.failed;
  const duration = formatDurationReadable(summary.totalDurationMs);
  const visibleNodes = getVisibleNodes(summary);
  const totalDisplay = visibleNodes.length;
  const completedDisplay = visibleNodes.filter(n => n.status === 'completed' || n.status === 'success' as string).length;

  return `
    <div class="status-bar">
      <span class="status-dot ${config.dot}"></span>
      <span class="status-text">${config.text}</span>
      <span class="status-detail">${duration}</span>
      <span class="status-detail">${completedDisplay}/${totalDisplay} 步骤完成</span>
      <span class="status-detail">${formatDateReadable(summary.startedAt)}</span>
    </div>
  `;
}

function renderSummary(summary: ExecutionSummary): string {
  const narrative = summary.finalNarrative;
  const highlights = summary.finalHighlights;

  if (!narrative && (!highlights || highlights.length === 0)) return '';

  let html = '';
  if (narrative) {
    html += `<div class="summary-text">${escapeHtml(narrative)}</div>`;
  }
  if (highlights && highlights.length > 0) {
    html += `<ul class="findings">`;
    for (const h of highlights) {
      html += `<li>${escapeHtml(h)}</li>`;
    }
    html += `</ul>`;
  }
  return html;
}

function renderActivities(activities: NodeActivity[]): string {
  if (!activities || activities.length === 0) return '';

  const items = activities.map(act => {
    const time = formatTimeOnly(act.timestamp);
    let icon = '';
    let text = '';

    switch (act.type) {
      case 'tool_start':
        icon = '&#9881;';
        text = `<span class="timeline-tool">${escapeHtml(act.toolName || '工具')}</span>`;
        break;
      case 'tool_result':
        icon = '&#10003;';
        text = escapeHtml(act.message);
        break;
      case 'tool_failed':
        icon = '&#10007;';
        text = escapeHtml(act.message);
        break;
      case 'thinking':
        icon = '&#9672;';
        text = escapeHtml(act.message);
        break;
      case 'decision':
        icon = '&#9670;';
        text = escapeHtml(act.message);
        break;
      case 'iteration':
        icon = '&#8634;';
        text = escapeHtml(act.message);
        break;
      default:
        icon = '&#8226;';
        text = escapeHtml(act.message);
    }

    let html = `<div class="timeline-item">
      <span class="timeline-time">${time}</span>
      <span class="timeline-icon">${icon}</span>
      <span class="timeline-text">${text}</span>
    </div>`;

    if (act.detail) {
      html += `<div class="timeline-detail">${escapeHtml(act.detail)}</div>`;
    }

    return html;
  });

  return `
    <div class="timeline-label">执行过程</div>
    <div class="timeline">${items.join('')}</div>
  `;
}

/**
 * 渲染步骤的详细数据
 *
 * 策略：
 * - data_format="markdown"：Markdown 内容直接展示（已是人类可读的格式）
 * - data_format="json" + 已有 narrative/highlights：折叠展示（用户可手动展开查看）
 * - data_format="json" + 无叙述内容：直接展示结构化数据
 */
function renderStepDetail(node: ExecutionNodeResult, stepIdx: number): string {
  const output = node.fullOutput;
  if (!output || (typeof output === 'object' && Object.keys(output as object).length === 0)) return '';

  // 优先使用节点级 dataFormat（持久化后恢复的数据），再从 fullOutput 推断
  const dataFormat = node.dataFormat || detectDataFormat(output);
  const content = renderOutputData(output, dataFormat);
  if (!content) return '';

  // Markdown 格式：直接展示，因为内容本身就是面向人类可读的
  if (dataFormat === 'markdown') {
    return `
      <div class="step-data">
        <div class="step-data-label">详细分析</div>
        ${content}
      </div>
    `;
  }

  // JSON 格式：根据是否有叙述内容决定展开/折叠
  const detailId = `detail-${stepIdx}`;

  if (hasNarrativeContent(node)) {
    // 已有叙述 → 默认折叠，用户可手动展开查看原始数据
    return `
      <div class="step-data">
        <div class="step-data-label">详细分析</div>
        <button class="detail-toggle" onclick="toggleDetail('${detailId}')">展开查看 \u203A</button>
        <div class="detail-content" id="${detailId}">${content}</div>
      </div>
    `;
  }

  // 无叙述 → 直接展示结构化数据
  return `
    <div class="step-data">
      <div class="step-data-label">详细分析</div>
      ${content}
    </div>
  `;
}

function renderSteps(summary: ExecutionSummary): string {
  const visibleNodes = getVisibleNodes(summary);
  if (visibleNodes.length === 0) return '';

  let html = `<div class="section-label">执行步骤</div>`;

  visibleNodes.forEach((node, idx) => {
    const stepNum = String(idx + 1).padStart(2, '0');
    const isFailed = node.status === 'failed';

    // 状态标签：统一中文，兼容后端可能返回的 success
    const statusLabels: Record<string, string> = {
      completed: '完成',
      success: '完成',
      failed: '失败',
      running: '进行中',
      pending: '等待中',
    };
    const statusLabel = statusLabels[node.status] || node.status;
    const duration = node.durationMs != null ? formatDurationReadable(node.durationMs) : '';
    const statusClass = isFailed ? 'step-status-failed' : 'step-status-success';
    const statusRight = [statusLabel, duration].filter(Boolean).join(' \u00B7 ');

    const narrative = getNodeNarrative(node);
    const highlights = getNodeHighlights(node);

    html += `
      <div class="step-card">
        <div class="step-number">${stepNum}</div>
        <div class="step-header">
          <span class="step-name ${isFailed ? 'step-name-failed' : ''}">${escapeHtml(node.nodeName)}</span>
          <span class="step-status ${statusClass}">${statusRight}</span>
        </div>
        <hr class="step-divider">
    `;

    if (narrative) {
      html += `<div class="step-narrative">${narrative}</div>`;
    }

    if (highlights.length > 0) {
      html += `<ul class="step-highlights">`;
      for (const h of highlights) {
        html += `<li>${escapeHtml(h)}</li>`;
      }
      html += `</ul>`;
    }

    if (isFailed && node.error) {
      html += `<div class="error-block">${escapeHtml(node.error)}</div>`;
    }

    // 执行过程（activities 时间线）
    if (node.activities && node.activities.length > 0) {
      html += renderActivities(node.activities);
    }

    // 详细数据（仅当没有叙述性内容时才折叠展示）
    html += renderStepDetail(node, idx);

    html += `</div>`;
  });

  return html;
}

/**
 * 从节点 fullOutput 中提取实际的 data 内容（markdown 或结构化数据）
 *
 * 处理嵌套结构：
 * - {result: {summary, narrative, data, data_format}} → 取 result.data
 * - {dep_xxx: {result: {summary, narrative, data}}} → 取第一个 dep 的 result.data
 * - {data, data_format} → 取 data
 * - 其他 → 过滤技术字段后返回
 */
function extractNodeDataContent(node: ExecutionNodeResult): { content: string; format: 'markdown' | 'json'; rawData: unknown } {
  const output = node.fullOutput;
  if (!output || typeof output !== 'object') return { content: '', format: 'json', rawData: null };

  let obj = output as Record<string, unknown>;

  // 层级 1：直接有 result 字段
  if (typeof obj.result === 'object' && obj.result !== null) {
    const inner = obj.result as Record<string, unknown>;
    if ('data' in inner || 'summary' in inner) {
      obj = inner;
    }
  } else {
    // 层级 2：嵌套在 dep_xxx 等子键中（如 {context, dep_report_generator: {result: {...}}}）
    for (const val of Object.values(obj)) {
      if (val && typeof val === 'object' && !Array.isArray(val)) {
        const sub = val as Record<string, unknown>;
        if (typeof sub.result === 'object' && sub.result !== null) {
          const inner = sub.result as Record<string, unknown>;
          if ('data' in inner || 'summary' in inner) {
            obj = inner;
            break;
          }
        }
        // 也可能直接是 {summary, data, data_format}
        if ('data' in sub && ('summary' in sub || 'data_format' in sub)) {
          obj = sub;
          break;
        }
      }
    }
  }

  const format = node.dataFormat || detectDataFormat(obj);

  // 提取 data 字段
  const data = obj.data;
  if (format === 'markdown' && typeof data === 'string') {
    return { content: data, format: 'markdown', rawData: data };
  }

  // JSON data
  if (data !== undefined && data !== null) {
    return { content: '', format: 'json', rawData: data };
  }

  // 回退：过滤技术字段后的整个对象
  const filtered = filterTechnicalFields(obj);
  if (Object.keys(filtered).length > 0) {
    return { content: '', format: 'json', rawData: filtered };
  }

  return { content: '', format: 'json', rawData: null };
}

/**
 * 渲染结果报告的完整主体内容
 *
 * 用于 result 类型报告，从最后一个业务节点提取最终成品。
 * 结构：执行摘要 → 要点 → 详细报告 → 结论
 *
 * 策略：
 * 1. 找到最后一个业务节点（非开始/结束）
 * 2. 提取其 narrative（执行摘要）、highlights（要点）、data（详细报告 markdown）
 * 3. 如果节点数据为空，回退到 summary 级别的 finalNarrative / finalOutput
 */
function renderFinalOutputContent(summary: ExecutionSummary): string {
  const visibleNodes = getVisibleNodes(summary);

  // 找最后一个有内容的业务节点
  let lastNode: ExecutionNodeResult | null = null;
  for (let i = visibleNodes.length - 1; i >= 0; i--) {
    const node = visibleNodes[i];
    if (node.fullOutput || node.outputNarrative || node.outputMarkdown) {
      lastNode = node;
      break;
    }
  }

  // ── 1. 执行摘要（Narrative） ──
  let narrative = '';
  let highlights: string[] = [];

  if (lastNode) {
    // 优先从最后节点获取
    narrative = getNodeNarrative(lastNode);
    highlights = getNodeHighlights(lastNode);
  }

  // 回退到 summary 级别
  if (!narrative && summary.finalNarrative) {
    narrative = escapeHtml(summary.finalNarrative);
  }
  if (highlights.length === 0 && summary.finalHighlights && summary.finalHighlights.length > 0) {
    highlights = summary.finalHighlights;
  }

  let html = '';

  // 渲染执行摘要
  if (narrative) {
    html += `<div class="section-label">执行摘要</div>`;
    html += `<div class="summary-text">${narrative}</div>`;
  }

  // 渲染要点
  if (highlights.length > 0) {
    if (!narrative) {
      html += `<div class="section-label">要点</div>`;
    }
    html += `<ul class="findings">`;
    for (const h of highlights) {
      html += `<li>${escapeHtml(h)}</li>`;
    }
    html += `</ul>`;
  }

  // ── 2. 详细报告（Data 内容） ──
  let detailHtml = '';

  if (lastNode) {
    const extracted = extractNodeDataContent(lastNode);

    if (extracted.format === 'markdown' && extracted.content) {
      // Markdown 格式：直接渲染为 HTML
      detailHtml = markdownToHtml(extracted.content);
    } else if (extracted.rawData) {
      // JSON 格式：结构化渲染
      detailHtml = renderStructuredData(extracted.rawData);
    }
  }

  // 回退到 summary.finalOutputMarkdown 或 summary.finalOutput
  if (!detailHtml) {
    if (summary.finalOutputMarkdown) {
      detailHtml = markdownToHtml(summary.finalOutputMarkdown);
    } else if (summary.finalOutput) {
      const dataFormat = detectDataFormat(summary.finalOutput);
      detailHtml = renderOutputData(summary.finalOutput, dataFormat);
    }
  }

  if (detailHtml) {
    if (narrative || highlights.length > 0) {
      html += `<hr class="divider">`;
    }
    html += `<div class="section-label">详细报告</div>`;
    html += `<div class="step-data">${detailHtml}</div>`;
  }

  // 注意：移除了此处的结论区渲染，因为与执行摘要内容完全重复。
  // 如果需要在报告末尾添加结论，应使用独立的结论数据源，而非复用 narrative。

  // 如果什么内容都没有
  if (!html) {
    html = `<div class="summary-text" style="color:#94a3b8;">暂无详细数据</div>`;
  }

  return html;
}

function renderFooter(summary: ExecutionSummary): string {
  const dateStr = formatDateShort(summary.completedAt || summary.startedAt);
  return `
    <hr class="divider">
    <div class="report-footer">QVerisFlow \u00B7 ${dateStr}</div>
  `;
}

function getExportScript(reportTitle: string): string {
  const safeName = reportTitle.replace(/['"\\]/g, '');
  return `
    <script>
      /* ── 动态加载 CDN 脚本（比 <script src> 更可靠） ── */
      var _pdfDepsReady = false;
      (function loadPdfDeps() {
        var scripts = [
          'https://cdnjs.cloudflare.com/ajax/libs/html2canvas/1.4.1/html2canvas.min.js',
          'https://cdnjs.cloudflare.com/ajax/libs/jspdf/2.5.1/jspdf.umd.min.js'
        ];
        var loaded = 0;
        function onDone() {
          loaded++;
          if (loaded === scripts.length) {
            _pdfDepsReady = true;
            /* 启用导出按钮（如果初始时被禁用） */
            var btn = document.querySelector('.toolbar-btn-export');
            if (btn && btn.dataset.waiting) {
              btn.textContent = '导出 PDF';
              btn.disabled = false;
              delete btn.dataset.waiting;
            }
          }
        }
        scripts.forEach(function(src) {
          var s = document.createElement('script');
          s.src = src;
          s.onload = onDone;
          s.onerror = function() {
            console.warn('Failed to load: ' + src + ', retrying...');
            /* 失败后重试一次 */
            var s2 = document.createElement('script');
            s2.src = src;
            s2.onload = onDone;
            s2.onerror = function() { console.error('Failed to load PDF dependency: ' + src); };
            document.head.appendChild(s2);
          };
          document.head.appendChild(s);
        });
      })();

      function toggleDetail(id) {
        var el = document.getElementById(id);
        if (el) el.classList.toggle('open');
      }

      /**
       * 分片渲染导出 PDF（智能分页版本）
       *
       * 核心思路：将报告按 A4 页高度逐页截图（html2canvas），每页 Canvas
       * 仅约 1000px 高，绝不会超出浏览器 Canvas 尺寸限制（~65 535px）。
       * 然后用 jsPDF 将每张截图依次放入 PDF 页面。
       *
       * 智能分页：在分页点附近寻找合适的断点（表格行之间、段落之间），
       * 避免在文字行中间截断。
       */
      async function exportPdf() {
        /* ── 1. 依赖检测 ── */
        if (!_pdfDepsReady || typeof html2canvas !== 'function') {
          /* 脚本可能还在加载，等待最多 10 秒 */
          var btn = document.querySelector('.toolbar-btn-export');
          if (btn) { btn.textContent = '加载中...'; btn.disabled = true; btn.dataset.waiting = '1'; }
          var waited = 0;
          while (!_pdfDepsReady && waited < 10000) {
            await new Promise(function(r) { setTimeout(r, 500); });
            waited += 500;
          }
          if (!_pdfDepsReady || typeof html2canvas !== 'function') {
            if (btn) { btn.textContent = '导出 PDF'; btn.disabled = false; delete btn.dataset.waiting; }
            alert('PDF 导出组件加载失败，请检查网络连接后刷新页面重试，或使用浏览器打印功能 (Ctrl/Cmd+P) 导出');
            return;
          }
          if (btn) { btn.textContent = '导出 PDF'; btn.disabled = false; delete btn.dataset.waiting; }
        }
        var JsPDF = (typeof jspdf !== 'undefined' && jspdf.jsPDF) ? jspdf.jsPDF : null;
        if (!JsPDF) {
          alert('PDF 导出组件加载失败，请刷新页面重试，或使用浏览器打印功能 (Ctrl/Cmd+P) 导出');
          return;
        }

        var btn = document.querySelector('.toolbar-btn-export');
        if (btn) { btn.textContent = '准备中...'; btn.disabled = true; }

        /* ── 2. 展开所有折叠区域，隐藏工具栏 ── */
        var details = Array.from(document.querySelectorAll('.detail-content'));
        var toggleBtns = Array.from(document.querySelectorAll('.detail-toggle'));
        details.forEach(function(el) { el.classList.add('open'); });
        toggleBtns.forEach(function(el) { el.style.display = 'none'; });

        var toolbar = document.querySelector('.toolbar');
        if (toolbar) toolbar.style.display = 'none';

        var element = document.getElementById('report-content');
        if (!element) {
          alert('无法找到报告内容');
          if (toolbar) toolbar.style.display = '';
          if (btn) { btn.textContent = '导出 PDF'; btn.disabled = false; }
          return;
        }

        /* 减少顶部留白（工具栏已隐藏，不再需要 80px padding） */
        var origPadTop = element.style.paddingTop;
        element.style.paddingTop = '40px';

        /* 等待布局重排稳定 */
        await new Promise(function(r) {
          requestAnimationFrame(function() { setTimeout(r, 300); });
        });

        try {
          var totalH = element.scrollHeight;
          var totalW = element.offsetWidth || element.scrollWidth || 720;

          /* ── 3. 计算分页参数 ── */
          var PW = 210, PH = 297, MG = 15;       /* A4 尺寸 & 边距 (mm) */
          var CW = PW - 2 * MG;                   /* 内容宽度 180mm */
          var CH = PH - 2 * MG;                   /* 内容高度 267mm */
          var pxPerMm  = totalW / CW;              /* 像素 → 毫米 */
          var pageHPx  = Math.floor(CH * pxPerMm); /* 每页高度（像素） */

          /* ── 4. 智能分页：收集所有可分页断点 ── */
          /**
           * 寻找合适的分页点：在目标位置附近（上下 100px）寻找元素边界
           * 优先级：表格行底部 > 段落底部 > 列表项底部 > 分割线 > 任意块元素底部
           */
          function findBreakPoint(targetY, searchRange) {
            searchRange = searchRange || 100;
            var minY = Math.max(0, targetY - searchRange);
            var maxY = Math.min(totalH, targetY + searchRange);

            /* 收集候选断点 */
            var candidates = [];
            var containerRect = element.getBoundingClientRect();
            var containerTop = containerRect.top + window.scrollY;

            /* 选择器优先级从高到低 */
            var selectors = [
              { sel: 'tr', priority: 10 },
              { sel: 'p', priority: 9 },
              { sel: 'li', priority: 8 },
              { sel: 'hr', priority: 7 },
              { sel: '.step-card', priority: 6 },
              { sel: '.section-block', priority: 5 },
              { sel: '.kv-inline', priority: 4 },
              { sel: '.numbered-item', priority: 4 },
              { sel: 'div', priority: 1 }
            ];

            selectors.forEach(function(item) {
              var els = element.querySelectorAll(item.sel);
              els.forEach(function(el) {
                var rect = el.getBoundingClientRect();
                var elBottom = rect.bottom + window.scrollY - containerTop;
                if (elBottom >= minY && elBottom <= maxY) {
                  candidates.push({ y: elBottom, priority: item.priority });
                }
              });
            });

            if (candidates.length === 0) return targetY;

            /* 按优先级降序，然后按距离目标的距离升序排序 */
            candidates.sort(function(a, b) {
              if (b.priority !== a.priority) return b.priority - a.priority;
              return Math.abs(a.y - targetY) - Math.abs(b.y - targetY);
            });

            return Math.floor(candidates[0].y);
          }

          /* ── 5. 计算智能分页点 ── */
          var pageBreaks = [0];
          var currentY = 0;
          while (currentY < totalH) {
            var idealNextY = currentY + pageHPx;
            if (idealNextY >= totalH) {
              break;
            }
            var actualBreak = findBreakPoint(idealNextY, 80);
            /* 确保分页点在合理范围内，避免页面过短或过长 */
            var minPageH = pageHPx * 0.7;
            var maxPageH = pageHPx * 1.15;
            if (actualBreak - currentY < minPageH) {
              actualBreak = currentY + pageHPx;
            } else if (actualBreak - currentY > maxPageH) {
              actualBreak = currentY + pageHPx;
            }
            pageBreaks.push(Math.min(actualBreak, totalH));
            currentY = actualBreak;
          }
          pageBreaks.push(totalH);

          var numPages = pageBreaks.length - 1;
          if (numPages < 1) numPages = 1;

          var scale = 2;
          var pdf = new JsPDF('p', 'mm', 'a4');

          /* ── 6. 逐页截图并写入 PDF ── */
          for (var i = 0; i < numPages; i++) {
            if (btn) btn.textContent = '导出 (' + (i + 1) + '/' + numPages + ')...';

            var yOff   = pageBreaks[i];
            var sliceH = pageBreaks[i + 1] - yOff;
            if (sliceH <= 0) continue;

            var canvas = await html2canvas(element, {
              scale:           scale,
              useCORS:         true,
              backgroundColor: '#ffffff',
              y:               yOff,
              x:               0,
              width:           totalW,
              height:          sliceH,
              windowWidth:     totalW
            });

            if (canvas.width === 0 || canvas.height === 0) continue;

            var imgData = canvas.toDataURL('image/jpeg', 0.92);
            var imgHMm  = (canvas.height / canvas.width) * CW;

            if (i > 0) pdf.addPage();
            pdf.addImage(imgData, 'JPEG', MG, MG, CW, imgHMm);

            /* 及时释放 Canvas 内存 */
            canvas.width  = 0;
            canvas.height = 0;
            canvas = null;
          }

          pdf.save('${safeName}.pdf');

        } catch (err) {
          console.error('PDF export failed:', err);
          alert('PDF 导出失败: ' + (err.message || err) + '\\n\\n请尝试使用浏览器打印功能 (Ctrl/Cmd+P) 导出');
        } finally {
          /* ── 7. 恢复页面原始状态 ── */
          element.style.paddingTop = origPadTop;
          if (toolbar) toolbar.style.display = '';
          details.forEach(function(el) { el.classList.remove('open'); });
          toggleBtns.forEach(function(el) { el.style.display = ''; });
          if (btn) { btn.textContent = '导出 PDF'; btn.disabled = false; }
        }
      }

      function printReport() {
        window.print();
      }
    <\/script>
  `;
}

// ─── 主函数 ────────────────────────────────────────────────

/**
 * 生成完整的 HTML 报告文档
 *
 * @param summary    执行摘要数据
 * @param reportType 报告类型：'result' = 结果报告（最终成品），'process' = 过程报告（执行步骤）
 */
export function generateReportHtml(summary: ExecutionSummary, reportType: ReportType = 'process'): string {
  const reportTitle = buildReportTitle(summary);
  const typeSuffix = reportType === 'result' ? '结果报告' : '过程报告';
  const pdfFileName = reportTitle + '-' + typeSuffix;

  // 根据报告类型生成不同的主体内容
  // 注意：移除了过程报告中的 renderConclusion 调用，因为它与 renderSummary 使用相同的数据源，
  // 会导致执行摘要和结论内容完全重复。
  const bodyContent = reportType === 'result'
    ? `
    ${renderFinalOutputContent(summary)}
    `
    : `
    ${renderSummary(summary)}
    <hr class="divider">
    ${renderSteps(summary)}
    `;

  return `<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>${escapeHtml(reportTitle)} - ${typeSuffix}</title>
  <style>${getReportStyles()}</style>
</head>
<body>
  ${renderToolbar()}
  <div class="report-container" id="report-content">
    ${renderHeader(summary, reportType)}
    ${renderStatusBar(summary)}
    ${bodyContent}
    ${renderFooter(summary)}
  </div>
  ${getExportScript(pdfFileName)}
</body>
</html>`;
}

/**
 * 在新窗口中打开执行报告
 *
 * @param summary    执行摘要数据
 * @param reportType 报告类型：'result' = 结果报告（最终成品），'process' = 过程报告（执行步骤）
 *
 * 使用 Blob URL 代替 document.write()：
 * - 避免 about:blank 页面（打印时会在页脚显示 about:blank）
 * - 避免 Chrome 阻止 document.write() 注入的外部脚本
 * - 新页面获得真实 origin，CDN 脚本可以正常加载
 *
 * Blob URL 生命周期：
 * - 不主动 revoke，报告页在主应用存活期间可随时刷新
 * - 主应用页面关闭/刷新后，Blob URL 自动失效（浏览器自动回收）
 * - 每次打开报告仅创建一个小 Blob，内存开销可忽略
 */
export function openReport(summary: ExecutionSummary, reportType: ReportType = 'process'): void {
  const html = generateReportHtml(summary, reportType);
  const blob = new Blob([html], { type: 'text/html' });
  const url = URL.createObjectURL(blob);
  window.open(url, '_blank');
}
