"""
中间结果提取器

从工作流执行过程中提取关键信息，用于对话式展示。
"""

from dataclasses import dataclass, field
from typing import Dict, Any, Optional, List
from datetime import datetime
from enum import Enum
import json
import re

from src.utils.logger import get_logger

logger = get_logger()


class ExecutionEventType(Enum):
    """执行事件类型"""
    WORKFLOW_STARTED = "workflow_started"
    NODE_STARTED = "node_started"
    NODE_PROGRESS = "node_progress"
    NODE_INTERMEDIATE = "node_intermediate"
    NODE_COMPLETED = "node_completed"
    NODE_FAILED = "node_failed"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    CONTEXT_WRITTEN = "context_written"
    WORKFLOW_COMPLETED = "workflow_completed"
    WORKFLOW_FAILED = "workflow_failed"
    WORKFLOW_PAUSED = "workflow_paused"
    WORKFLOW_RESUMED = "workflow_resumed"


@dataclass
class ExecutionEvent:
    """执行事件"""
    event_type: ExecutionEventType
    timestamp: datetime = field(default_factory=datetime.now)
    workflow_id: Optional[str] = None
    node_id: Optional[str] = None
    node_name: Optional[str] = None
    data: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_type": self.event_type.value,
            "timestamp": self.timestamp.isoformat(),
            "workflow_id": self.workflow_id,
            "node_id": self.node_id,
            "node_name": self.node_name,
            "data": self.data,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ExecutionEvent":
        return cls(
            event_type=ExecutionEventType(data.get("event_type", "node_progress")),
            timestamp=datetime.fromisoformat(data["timestamp"]) if "timestamp" in data else datetime.now(),
            workflow_id=data.get("workflow_id"),
            node_id=data.get("node_id"),
            node_name=data.get("node_name"),
            data=data.get("data", {}),
        )


@dataclass
class FormattedMessage:
    """格式化后的消息"""
    text: str
    message_type: str = "info"  # info, success, error, warning, progress
    icon: Optional[str] = None
    data: Optional[Dict[str, Any]] = None


class IntermediateResultExtractor:
    """
    中间结果提取器
    
    从 Agent 执行输出中提取关键信息，用于对话展示。
    """
    
    # 关键字段映射（用于提取关键发现）
    KEY_FIELDS = {
        # 金融分析
        "trend": "趋势",
        "price": "价格",
        "support": "支撑位",
        "resistance": "阻力位",
        "volume": "成交量",
        "change": "涨跌幅",
        "market_cap": "市值",
        "pe_ratio": "市盈率",
        
        # 数据分析
        "count": "数量",
        "total": "总计",
        "average": "平均",
        "max": "最大值",
        "min": "最小值",
        "result": "结果",
        "summary": "摘要",
        
        # 状态
        "status": "状态",
        "progress": "进度",
        "error": "错误",
        "warning": "警告",
    }
    
    # 值翻译映射
    VALUE_TRANSLATIONS = {
        "bullish": "看涨",
        "bearish": "看跌",
        "neutral": "中性",
        "up": "上涨",
        "down": "下跌",
        "stable": "稳定",
        "success": "成功",
        "failed": "失败",
        "pending": "等待中",
        "running": "执行中",
        "completed": "已完成",
    }
    
    def __init__(self, llm_client: Optional[Any] = None, max_summary_length: int = 200):
        """
        初始化提取器
        
        Args:
            llm_client: LLM 客户端（可选，用于生成智能摘要）
            max_summary_length: 摘要最大长度
        """
        self.llm_client = llm_client
        self.max_summary_length = max_summary_length
    
    async def extract_key_findings(self, node_output: Dict[str, Any]) -> List[str]:
        """
        提取关键发现点
        
        Args:
            node_output: 节点输出
            
        Returns:
            关键发现列表
        """
        findings = []
        
        if not node_output:
            return findings
        
        # 扁平化嵌套结构
        flat_data = self._flatten_dict(node_output)
        
        # 提取关键字段
        for key, value in flat_data.items():
            key_lower = key.lower()
            
            for field, label in self.KEY_FIELDS.items():
                if field in key_lower and value is not None:
                    formatted_value = self._format_value(value)
                    if formatted_value:
                        findings.append(f"{label}: {formatted_value}")
                        break
        
        # 限制数量
        return findings[:5]
    
    async def summarize_output(
        self,
        node_output: Dict[str, Any],
        max_length: Optional[int] = None
    ) -> str:
        """
        生成输出摘要
        
        Args:
            node_output: 节点输出
            max_length: 最大长度
            
        Returns:
            摘要文本
        """
        max_len = max_length or self.max_summary_length
        
        if not node_output:
            return "无输出"
        
        # 尝试使用 LLM 生成智能摘要
        if self.llm_client:
            try:
                return await self._llm_summarize(node_output, max_len)
            except Exception as e:
                logger.warning(f"LLM 摘要失败: {e}")
        
        # 降级到规则提取
        return self._rule_based_summary(node_output, max_len)
    
    async def format_for_chat(self, event: ExecutionEvent) -> FormattedMessage:
        """
        格式化执行事件为对话消息
        
        Args:
            event: 执行事件
            
        Returns:
            格式化后的消息
        """
        event_type = event.event_type
        data = event.data
        node_name = event.node_name or event.node_id or "unknown"
        
        if event_type == ExecutionEventType.WORKFLOW_STARTED:
            return FormattedMessage(
                text="🚀 工作流开始执行...",
                message_type="info",
                icon="rocket",
            )
        
        elif event_type == ExecutionEventType.NODE_STARTED:
            return FormattedMessage(
                text=f"📊 [{node_name}] 开始执行...",
                message_type="info",
                icon="chart",
            )
        
        elif event_type == ExecutionEventType.NODE_PROGRESS:
            step = data.get("step", "处理中")
            detail = data.get("detail", "")
            text = f"   → {step}"
            if detail:
                text += f": {detail}"
            return FormattedMessage(
                text=text,
                message_type="progress",
                icon="arrow",
            )
        
        elif event_type == ExecutionEventType.TOOL_CALL:
            tool_id = data.get("tool_id", "unknown")
            params = data.get("params", {})
            params_str = self._format_params(params)
            return FormattedMessage(
                text=f"   → 调用工具: {tool_id}{params_str}",
                message_type="info",
                icon="tool",
            )
        
        elif event_type == ExecutionEventType.TOOL_RESULT:
            result = data.get("result")
            summary = self._quick_summary(result) if result else "无返回"
            return FormattedMessage(
                text=f"   ← 返回: {summary}",
                message_type="info",
                icon="check",
            )
        
        elif event_type == ExecutionEventType.NODE_INTERMEDIATE:
            output = data.get("output", {})
            findings = await self.extract_key_findings(output)
            if findings:
                text = f"   📝 中间结果:\n" + "\n".join(f"      - {f}" for f in findings)
            else:
                text = "   📝 已产生中间结果"
            return FormattedMessage(
                text=text,
                message_type="info",
                icon="note",
                data={"findings": findings},
            )
        
        elif event_type == ExecutionEventType.CONTEXT_WRITTEN:
            file_name = data.get("file_name", "context")
            return FormattedMessage(
                text=f"   💾 数据已保存: {file_name}",
                message_type="info",
                icon="save",
            )
        
        elif event_type == ExecutionEventType.NODE_COMPLETED:
            duration_ms = data.get("duration_ms", 0)
            duration_str = f"{duration_ms/1000:.1f}s" if duration_ms else ""
            output_preview = data.get("output_preview")
            
            text = f"✅ [{node_name}] 完成!"
            if duration_str:
                text += f" ({duration_str})"
            
            return FormattedMessage(
                text=text,
                message_type="success",
                icon="check_circle",
                data={"output_preview": output_preview},
            )
        
        elif event_type == ExecutionEventType.NODE_FAILED:
            error = data.get("error", "未知错误")
            return FormattedMessage(
                text=f"❌ [{node_name}] 失败: {error}",
                message_type="error",
                icon="error",
            )
        
        elif event_type == ExecutionEventType.WORKFLOW_COMPLETED:
            total_duration = data.get("total_duration_ms", 0)
            nodes_completed = data.get("nodes_completed", 0)
            total_nodes = data.get("total_nodes", 0)
            
            text = f"🎉 工作流执行完成!\n"
            text += f"   总耗时: {total_duration/1000:.1f}s\n"
            text += f"   成功节点: {nodes_completed}/{total_nodes}"
            
            return FormattedMessage(
                text=text,
                message_type="success",
                icon="celebration",
                data={
                    "total_duration_ms": total_duration,
                    "nodes_completed": nodes_completed,
                    "total_nodes": total_nodes,
                },
            )
        
        elif event_type == ExecutionEventType.WORKFLOW_FAILED:
            error = data.get("error", "未知错误")
            failed_node = data.get("failed_node")
            
            text = f"❌ 工作流执行失败: {error}"
            if failed_node:
                text = f"❌ 工作流执行失败（节点 {failed_node}）: {error}"
            
            return FormattedMessage(
                text=text,
                message_type="error",
                icon="error",
            )
        
        elif event_type == ExecutionEventType.WORKFLOW_PAUSED:
            return FormattedMessage(
                text="⏸️ 工作流已暂停",
                message_type="warning",
                icon="pause",
            )
        
        elif event_type == ExecutionEventType.WORKFLOW_RESUMED:
            return FormattedMessage(
                text="▶️ 工作流已恢复执行",
                message_type="info",
                icon="play",
            )
        
        else:
            message = data.get("message", f"事件: {event_type.value}")
            return FormattedMessage(
                text=message,
                message_type="info",
            )
    
    def _flatten_dict(
        self,
        d: Dict[str, Any],
        parent_key: str = "",
        sep: str = "."
    ) -> Dict[str, Any]:
        """扁平化嵌套字典"""
        items = []
        for k, v in d.items():
            new_key = f"{parent_key}{sep}{k}" if parent_key else k
            if isinstance(v, dict):
                items.extend(self._flatten_dict(v, new_key, sep).items())
            else:
                items.append((new_key, v))
        return dict(items)
    
    def _format_value(self, value: Any) -> str:
        """格式化值"""
        if value is None:
            return ""
        
        if isinstance(value, bool):
            return "是" if value else "否"
        
        if isinstance(value, (int, float)):
            if isinstance(value, float):
                # 格式化数字
                if abs(value) >= 1000000:
                    return f"{value/1000000:.2f}M"
                elif abs(value) >= 1000:
                    return f"{value/1000:.2f}K"
                else:
                    return f"{value:.2f}"
            return str(value)
        
        if isinstance(value, str):
            # 翻译常见值
            lower_value = value.lower()
            if lower_value in self.VALUE_TRANSLATIONS:
                return self.VALUE_TRANSLATIONS[lower_value]
            return value[:50] + "..." if len(value) > 50 else value
        
        if isinstance(value, list):
            if len(value) == 0:
                return "空"
            if len(value) <= 3:
                return ", ".join(str(v)[:20] for v in value)
            return f"{len(value)} 项"
        
        if isinstance(value, dict):
            return f"{len(value)} 个字段"
        
        return str(value)[:50]
    
    def _format_params(self, params: Dict[str, Any]) -> str:
        """格式化参数"""
        if not params:
            return ""
        
        param_strs = []
        for k, v in list(params.items())[:3]:
            v_str = str(v)[:20]
            if len(str(v)) > 20:
                v_str += "..."
            param_strs.append(f"{k}={v_str}")
        
        result = f"({', '.join(param_strs)})"
        if len(params) > 3:
            result = result[:-1] + f", ...共{len(params)}参数)"
        
        return result
    
    def _quick_summary(self, data: Any) -> str:
        """快速生成摘要"""
        if data is None:
            return "无"
        
        if isinstance(data, str):
            return data[:50] + "..." if len(data) > 50 else data
        
        if isinstance(data, (int, float, bool)):
            return str(data)
        
        if isinstance(data, list):
            return f"列表 ({len(data)} 项)"
        
        if isinstance(data, dict):
            keys = list(data.keys())[:3]
            return f"对象: {', '.join(keys)}" + ("..." if len(data) > 3 else "")
        
        return str(type(data).__name__)
    
    def _rule_based_summary(self, output: Dict[str, Any], max_len: int) -> str:
        """基于规则的摘要生成"""
        # 优先使用已有的 summary 字段
        if "summary" in output:
            summary = str(output["summary"])
            return summary[:max_len] + "..." if len(summary) > max_len else summary
        
        if "result" in output:
            result = output["result"]
            if isinstance(result, str):
                return result[:max_len] + "..." if len(result) > max_len else result
        
        # 提取关键字段
        key_values = []
        flat = self._flatten_dict(output)
        
        for key, value in flat.items():
            key_lower = key.lower()
            for field in self.KEY_FIELDS:
                if field in key_lower:
                    formatted = self._format_value(value)
                    if formatted:
                        key_values.append(f"{self.KEY_FIELDS[field]}: {formatted}")
                    break
        
        if key_values:
            return "; ".join(key_values[:5])
        
        # 最后：JSON 概览
        try:
            json_str = json.dumps(output, ensure_ascii=False, indent=None)
            return json_str[:max_len] + "..." if len(json_str) > max_len else json_str
        except:
            return f"输出包含 {len(output)} 个字段"
    
    async def _llm_summarize(self, output: Dict[str, Any], max_len: int) -> str:
        """使用 LLM 生成智能摘要"""
        # 限制输入大小
        output_str = json.dumps(output, ensure_ascii=False, indent=2)[:2000]
        
        prompt = f"""请用一句话（不超过{max_len}字）总结以下执行结果的关键信息：

{output_str}

只输出摘要，不要其他内容。
"""
        
        # 使用 UnifiedLLMClient 的 call 方法
        messages = [{"role": "user", "content": prompt}]
        response = await self.llm_client.call(messages)
        
        # 提取响应内容
        if hasattr(response, 'content'):
            content = response.content
        elif isinstance(response, dict) and 'content' in response:
            content = response['content']
        elif isinstance(response, str):
            content = response
        else:
            content = str(response)
        
        # 清理输出
        content = content.strip().strip('"\'')
        return content[:max_len]
    
    def create_progress_event(
        self,
        workflow_id: str,
        node_id: str,
        step: str,
        detail: Optional[str] = None
    ) -> ExecutionEvent:
        """创建进度事件（便捷方法）"""
        return ExecutionEvent(
            event_type=ExecutionEventType.NODE_PROGRESS,
            workflow_id=workflow_id,
            node_id=node_id,
            data={
                "step": step,
                "detail": detail,
            }
        )
    
    def create_tool_call_event(
        self,
        workflow_id: str,
        node_id: str,
        tool_id: str,
        params: Dict[str, Any]
    ) -> ExecutionEvent:
        """创建工具调用事件（便捷方法）"""
        return ExecutionEvent(
            event_type=ExecutionEventType.TOOL_CALL,
            workflow_id=workflow_id,
            node_id=node_id,
            data={
                "tool_id": tool_id,
                "params": params,
            }
        )
    
    def create_completion_event(
        self,
        workflow_id: str,
        node_id: str,
        node_name: str,
        duration_ms: int,
        output_preview: Optional[Dict] = None
    ) -> ExecutionEvent:
        """创建完成事件（便捷方法）"""
        return ExecutionEvent(
            event_type=ExecutionEventType.NODE_COMPLETED,
            workflow_id=workflow_id,
            node_id=node_id,
            node_name=node_name,
            data={
                "duration_ms": duration_ms,
                "output_preview": output_preview,
            }
        )
