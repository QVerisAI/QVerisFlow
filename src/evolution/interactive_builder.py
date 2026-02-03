"""
Interactive Workflow Builder - 交互式工作流构建器

支持边生成边调整的 Human-in-the-Loop 工作流构建模式。

核心组件:
- UserInteractionCallback: 用户交互回调接口
- IterationManager: 迭代管理器（检查点/回滚）
- InteractiveWorkflowBuilder: 交互式构建器主类
"""

import json
import uuid
import asyncio
from abc import ABC, abstractmethod
from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import (
    Any,
    Callable,
    Dict,
    List,
    Optional,
    Protocol,
    Union,
    runtime_checkable,
)

from src.utils.logger import get_logger
from ..definitions import AgentDefinition, WorkflowDefinition, WorkflowNode

logger = get_logger(__name__)


# ============================================================
# P0: 数据类定义
# ============================================================


class InteractionStage(str, Enum):
    """交互阶段"""
    PLAN = "plan"           # 方案规划阶段
    AGENT = "agent"         # Agent 生成阶段
    WORKFLOW = "workflow"   # 工作流组装阶段
    EXECUTION = "execution" # 执行监控阶段


class UserAction(str, Enum):
    """用户操作类型"""
    APPROVE = "approve"           # 批准
    MODIFY = "modify"             # 修改
    REGENERATE = "regenerate"     # 重新生成
    SKIP = "skip"                 # 跳过
    ROLLBACK = "rollback"         # 回滚
    CANCEL = "cancel"             # 取消整个会话
    ADD_NODE = "add_node"         # 添加节点
    REMOVE_NODE = "remove_node"   # 删除节点
    MODIFY_EDGE = "modify_edge"   # 修改边
    ADD_CONTEXT_REF = "add_context_ref"  # 添加上下文引用


class InteractionLevel(str, Enum):
    """交互级别"""
    MINIMAL = "minimal"           # 只在关键节点征求意见
    MODERATE = "moderate"         # 每个 Agent 生成后征求意见
    COMPREHENSIVE = "comprehensive"  # 每步都征求意见


@dataclass
class UserFeedback:
    """用户反馈"""
    action: UserAction
    feedback: Optional[str] = None      # 用户的文字反馈
    modifications: Optional[Dict[str, Any]] = None  # 用户的具体修改
    params: Optional[Dict[str, Any]] = None  # 额外参数
    timestamp: datetime = field(default_factory=datetime.now)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "action": self.action.value,
            "feedback": self.feedback,
            "modifications": self.modifications,
            "params": self.params,
            "timestamp": self.timestamp.isoformat(),
        }


@dataclass
class AgentSpec:
    """Agent 规格说明"""
    name: str
    task: str
    display_name: str = ""  # 用户友好的显示名称
    suggested_tools: List[str] = field(default_factory=list)
    constraints: Optional[Dict[str, Any]] = None
    dependencies: List[str] = field(default_factory=list)
    context_refs: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class WorkflowPlan:
    """工作流规划"""
    task_description: str
    agent_specs: List[AgentSpec]
    workflow_structure: str  # 描述性的工作流结构
    estimated_steps: int
    notes: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_description": self.task_description,
            "agent_specs": [spec.to_dict() for spec in self.agent_specs],
            "workflow_structure": self.workflow_structure,
            "estimated_steps": self.estimated_steps,
            "notes": self.notes,
        }


@dataclass
class IterationRecord:
    """迭代记录 - 支持回滚"""
    iteration_id: str
    timestamp: datetime
    stage: InteractionStage
    action: str  # "generate" | "modify" | "approve" | "rollback"
    before_state: Dict[str, Any]
    after_state: Dict[str, Any]
    user_feedback: Optional[UserFeedback] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "iteration_id": self.iteration_id,
            "timestamp": self.timestamp.isoformat(),
            "stage": self.stage.value,
            "action": self.action,
            "before_state": self.before_state,
            "after_state": self.after_state,
            "user_feedback": self.user_feedback.to_dict() if self.user_feedback else None,
            "metadata": self.metadata,
        }


@dataclass
class Checkpoint:
    """检查点"""
    checkpoint_id: str
    label: str
    timestamp: datetime
    stage: InteractionStage
    state: Dict[str, Any]
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "checkpoint_id": self.checkpoint_id,
            "label": self.label,
            "timestamp": self.timestamp.isoformat(),
            "stage": self.stage.value,
            "state": self.state,
        }


@dataclass
class BuilderState:
    """构建器状态 - 用于检查点和回滚"""
    draft_agents: List[Dict[str, Any]]
    draft_workflow: Optional[Dict[str, Any]]
    current_stage: InteractionStage
    plan: Optional[Dict[str, Any]]
    iteration_count: int
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "BuilderState":
        return cls(
            draft_agents=data.get("draft_agents", []),
            draft_workflow=data.get("draft_workflow"),
            current_stage=InteractionStage(data.get("current_stage", "plan")),
            plan=data.get("plan"),
            iteration_count=data.get("iteration_count", 0),
        )


# ============================================================
# P0: UserInteractionCallback 接口定义
# ============================================================


@runtime_checkable
class UserInteractionCallback(Protocol):
    """
    用户交互回调协议
    
    实现此协议以支持不同的交互方式（CLI、Web UI、API 等）
    """
    
    async def request_approval(
        self,
        stage: InteractionStage,
        content: Any,
        options: List[UserAction],
        context: Optional[Dict[str, Any]] = None,
    ) -> UserFeedback:
        """
        请求用户审批/反馈
        
        Args:
            stage: 当前阶段
            content: 需要审批的内容
            options: 可选的操作
            context: 上下文信息
            
        Returns:
            用户反馈
        """
        ...
    
    async def notify_progress(
        self,
        stage: InteractionStage,
        progress: float,
        message: str,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        通知进度
        
        Args:
            stage: 当前阶段
            progress: 进度 (0.0 - 1.0)
            message: 进度消息
            details: 详细信息
        """
        ...
    
    async def request_input(
        self,
        prompt: str,
        input_type: str,  # "text" | "choice" | "json" | "confirm"
        options: Optional[List[str]] = None,
        default: Optional[Any] = None,
    ) -> Any:
        """
        请求用户输入
        
        Args:
            prompt: 提示信息
            input_type: 输入类型
            options: 选项列表（用于 choice 类型）
            default: 默认值
            
        Returns:
            用户输入
        """
        ...
    
    async def display_message(
        self,
        message: str,
        level: str = "info",  # "info" | "warning" | "error" | "success"
    ) -> None:
        """
        显示消息
        
        Args:
            message: 消息内容
            level: 消息级别
        """
        ...
    
    async def display_diff(
        self,
        before: Dict[str, Any],
        after: Dict[str, Any],
        title: str = "Changes",
    ) -> None:
        """
        显示差异对比
        
        Args:
            before: 修改前状态
            after: 修改后状态
            title: 标题
        """
        ...


# ============================================================
# P0: IterationManager 检查点/回滚机制
# ============================================================


class IterationManager:
    """
    迭代管理器 - 支持版本检查点和回滚
    
    功能:
    - 创建检查点
    - 回滚到检查点
    - 记录所有迭代操作
    - 获取版本差异
    """
    
    def __init__(
        self,
        storage_path: Optional[Path] = None,
        max_checkpoints: int = 20,
    ):
        """
        初始化迭代管理器
        
        Args:
            storage_path: 持久化存储路径（可选）
            max_checkpoints: 最大检查点数量
        """
        self.storage_path = storage_path
        self.max_checkpoints = max_checkpoints
        
        self.checkpoints: Dict[str, Checkpoint] = {}
        self.checkpoint_order: List[str] = []  # 按时间顺序
        self.iterations: List[IterationRecord] = []
        
        if storage_path:
            storage_path.mkdir(parents=True, exist_ok=True)
    
    def checkpoint(
        self,
        label: str,
        stage: InteractionStage,
        state: BuilderState,
    ) -> str:
        """
        创建检查点
        
        Args:
            label: 检查点标签（描述性名称）
            stage: 当前阶段
            state: 当前状态
            
        Returns:
            检查点 ID
        """
        checkpoint_id = f"ckpt_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
        
        checkpoint = Checkpoint(
            checkpoint_id=checkpoint_id,
            label=label,
            timestamp=datetime.now(),
            stage=stage,
            state=state.to_dict(),
        )
        
        self.checkpoints[checkpoint_id] = checkpoint
        self.checkpoint_order.append(checkpoint_id)
        
        # 限制检查点数量
        while len(self.checkpoint_order) > self.max_checkpoints:
            oldest_id = self.checkpoint_order.pop(0)
            del self.checkpoints[oldest_id]
        
        # 持久化
        if self.storage_path:
            self._save_checkpoint(checkpoint)
        
        logger.info(f"创建检查点: {checkpoint_id} ({label})")
        return checkpoint_id
    
    def rollback(self, checkpoint_id: str) -> BuilderState:
        """
        回滚到检查点
        
        Args:
            checkpoint_id: 检查点 ID
            
        Returns:
            回滚后的状态
        """
        if checkpoint_id not in self.checkpoints:
            raise ValueError(f"检查点不存在: {checkpoint_id}")
        
        checkpoint = self.checkpoints[checkpoint_id]
        state = BuilderState.from_dict(checkpoint.state)
        
        # 记录回滚操作
        self.record_iteration(
            stage=checkpoint.stage,
            action="rollback",
            before_state={},  # 当前状态在调用方记录
            after_state=checkpoint.state,
            metadata={"rollback_to": checkpoint_id, "label": checkpoint.label},
        )
        
        logger.info(f"回滚到检查点: {checkpoint_id} ({checkpoint.label})")
        return state
    
    def record_iteration(
        self,
        stage: InteractionStage,
        action: str,
        before_state: Dict[str, Any],
        after_state: Dict[str, Any],
        user_feedback: Optional[UserFeedback] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> IterationRecord:
        """
        记录迭代操作
        
        Args:
            stage: 当前阶段
            action: 操作类型
            before_state: 操作前状态
            after_state: 操作后状态
            user_feedback: 用户反馈
            metadata: 额外元数据
            
        Returns:
            迭代记录
        """
        record = IterationRecord(
            iteration_id=f"iter_{len(self.iterations):04d}_{uuid.uuid4().hex[:6]}",
            timestamp=datetime.now(),
            stage=stage,
            action=action,
            before_state=before_state,
            after_state=after_state,
            user_feedback=user_feedback,
            metadata=metadata or {},
        )
        
        self.iterations.append(record)
        
        # 持久化
        if self.storage_path:
            self._save_iteration(record)
        
        return record
    
    def get_checkpoints(self) -> List[Checkpoint]:
        """获取所有检查点（按时间顺序）"""
        return [self.checkpoints[cid] for cid in self.checkpoint_order]
    
    def get_latest_checkpoint(self) -> Optional[Checkpoint]:
        """获取最新检查点"""
        if not self.checkpoint_order:
            return None
        return self.checkpoints[self.checkpoint_order[-1]]
    
    def get_diff(
        self,
        from_id: str,
        to_id: str,
    ) -> Dict[str, Any]:
        """
        获取两个检查点之间的差异
        
        Args:
            from_id: 起始检查点 ID
            to_id: 目标检查点 ID
            
        Returns:
            差异描述
        """
        if from_id not in self.checkpoints:
            raise ValueError(f"检查点不存在: {from_id}")
        if to_id not in self.checkpoints:
            raise ValueError(f"检查点不存在: {to_id}")
        
        from_state = self.checkpoints[from_id].state
        to_state = self.checkpoints[to_id].state
        
        diff = {
            "from_checkpoint": from_id,
            "to_checkpoint": to_id,
            "changes": {},
        }
        
        # 比较 agents
        from_agents = {a.get("agent_id"): a for a in from_state.get("draft_agents", [])}
        to_agents = {a.get("agent_id"): a for a in to_state.get("draft_agents", [])}
        
        added_agents = set(to_agents.keys()) - set(from_agents.keys())
        removed_agents = set(from_agents.keys()) - set(to_agents.keys())
        
        diff["changes"]["agents"] = {
            "added": list(added_agents),
            "removed": list(removed_agents),
        }
        
        # 比较 workflow
        if from_state.get("draft_workflow") != to_state.get("draft_workflow"):
            diff["changes"]["workflow"] = "modified"
        
        # 比较阶段
        if from_state.get("current_stage") != to_state.get("current_stage"):
            diff["changes"]["stage"] = {
                "from": from_state.get("current_stage"),
                "to": to_state.get("current_stage"),
            }
        
        return diff
    
    def get_iteration_history(
        self,
        stage: Optional[InteractionStage] = None,
        limit: Optional[int] = None,
    ) -> List[IterationRecord]:
        """
        获取迭代历史
        
        Args:
            stage: 筛选特定阶段
            limit: 限制返回数量
            
        Returns:
            迭代记录列表
        """
        records = self.iterations
        
        if stage:
            records = [r for r in records if r.stage == stage]
        
        if limit:
            records = records[-limit:]
        
        return records
    
    def export_history(self) -> Dict[str, Any]:
        """导出完整历史记录"""
        return {
            "checkpoints": [c.to_dict() for c in self.get_checkpoints()],
            "iterations": [i.to_dict() for i in self.iterations],
            "exported_at": datetime.now().isoformat(),
        }
    
    def _save_checkpoint(self, checkpoint: Checkpoint) -> None:
        """持久化检查点"""
        if not self.storage_path:
            return
        
        filepath = self.storage_path / f"{checkpoint.checkpoint_id}.json"
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(checkpoint.to_dict(), f, ensure_ascii=False, indent=2)
    
    def _save_iteration(self, record: IterationRecord) -> None:
        """持久化迭代记录"""
        if not self.storage_path:
            return
        
        filepath = self.storage_path / "iterations.jsonl"
        with open(filepath, "a", encoding="utf-8") as f:
            f.write(json.dumps(record.to_dict(), ensure_ascii=False) + "\n")
    
    def load_from_storage(self) -> None:
        """从存储加载历史"""
        if not self.storage_path or not self.storage_path.exists():
            return
        
        # 加载检查点
        for filepath in sorted(self.storage_path.glob("ckpt_*.json")):
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
                checkpoint = Checkpoint(
                    checkpoint_id=data["checkpoint_id"],
                    label=data["label"],
                    timestamp=datetime.fromisoformat(data["timestamp"]),
                    stage=InteractionStage(data["stage"]),
                    state=data["state"],
                )
                self.checkpoints[checkpoint.checkpoint_id] = checkpoint
                self.checkpoint_order.append(checkpoint.checkpoint_id)
        
        # 加载迭代记录
        iterations_file = self.storage_path / "iterations.jsonl"
        if iterations_file.exists():
            with open(iterations_file, "r", encoding="utf-8") as f:
                for line in f:
                    data = json.loads(line)
                    feedback = None
                    if data.get("user_feedback"):
                        fb_data = data["user_feedback"]
                        feedback = UserFeedback(
                            action=UserAction(fb_data["action"]),
                            feedback=fb_data.get("feedback"),
                            modifications=fb_data.get("modifications"),
                            params=fb_data.get("params"),
                            timestamp=datetime.fromisoformat(fb_data["timestamp"]),
                        )
                    
                    record = IterationRecord(
                        iteration_id=data["iteration_id"],
                        timestamp=datetime.fromisoformat(data["timestamp"]),
                        stage=InteractionStage(data["stage"]),
                        action=data["action"],
                        before_state=data["before_state"],
                        after_state=data["after_state"],
                        user_feedback=feedback,
                        metadata=data.get("metadata", {}),
                    )
                    self.iterations.append(record)
        
        logger.info(
            f"从存储加载: {len(self.checkpoints)} 个检查点, "
            f"{len(self.iterations)} 条迭代记录"
        )


# ============================================================
# P1: CLI 交互回调实现
# ============================================================


class CLIInteractionCallback:
    """
    命令行交互回调实现
    
    提供基于终端的交互体验，支持彩色输出和进度条。
    """
    
    # ANSI 颜色代码
    COLORS = {
        "reset": "\033[0m",
        "bold": "\033[1m",
        "red": "\033[91m",
        "green": "\033[92m",
        "yellow": "\033[93m",
        "blue": "\033[94m",
        "magenta": "\033[95m",
        "cyan": "\033[96m",
    }
    
    def __init__(self, use_colors: bool = True):
        self.use_colors = use_colors
    
    def _color(self, text: str, color: str) -> str:
        """应用颜色"""
        if not self.use_colors:
            return text
        return f"{self.COLORS.get(color, '')}{text}{self.COLORS['reset']}"
    
    def _print_header(self, title: str) -> None:
        """打印标题"""
        print("\n" + "=" * 60)
        print(self._color(f"  {title}", "bold"))
        print("=" * 60)
    
    def _print_section(self, title: str) -> None:
        """打印小节标题"""
        print(f"\n{self._color('▶ ' + title, 'cyan')}")
        print("-" * 40)
    
    async def request_approval(
        self,
        stage: InteractionStage,
        content: Any,
        options: List[UserAction],
        context: Optional[Dict[str, Any]] = None,
    ) -> UserFeedback:
        """请求用户审批"""
        stage_names = {
            InteractionStage.PLAN: "📋 方案规划",
            InteractionStage.AGENT: "🤖 Agent 生成",
            InteractionStage.WORKFLOW: "🔄 工作流组装",
            InteractionStage.EXECUTION: "▶️ 执行监控",
        }
        
        self._print_header(f"审批请求 - {stage_names.get(stage, stage.value)}")
        
        # 显示内容
        if isinstance(content, dict):
            self._display_content(content)
        else:
            print(content)
        
        # 显示上下文
        if context:
            self._print_section("上下文信息")
            for key, value in context.items():
                if isinstance(value, list):
                    print(f"  {key}: [{len(value)} items]")
                else:
                    print(f"  {key}: {value}")
        
        # 显示选项
        self._print_section("可选操作")
        option_map = {}
        for i, opt in enumerate(options, 1):
            option_names = {
                UserAction.APPROVE: "✅ 批准",
                UserAction.MODIFY: "✏️ 修改",
                UserAction.REGENERATE: "🔄 重新生成",
                UserAction.SKIP: "⏭️ 跳过",
                UserAction.ROLLBACK: "⏪ 回滚",
                UserAction.CANCEL: "❌ 取消",
                UserAction.ADD_NODE: "➕ 添加节点",
                UserAction.REMOVE_NODE: "➖ 删除节点",
                UserAction.MODIFY_EDGE: "🔗 修改连接",
                UserAction.ADD_CONTEXT_REF: "📎 添加数据引用",
            }
            print(f"  [{i}] {option_names.get(opt, opt.value)}")
            option_map[str(i)] = opt
        
        # 获取用户选择
        while True:
            choice = input(f"\n{self._color('请选择操作 [1-' + str(len(options)) + ']: ', 'yellow')}")
            if choice in option_map:
                action = option_map[choice]
                break
            print(self._color("无效选择，请重试", "red"))
        
        # 根据操作类型获取额外信息
        feedback = None
        modifications = None
        params = None
        
        if action == UserAction.MODIFY:
            feedback = input("请输入修改意见: ")
            mod_input = input("请输入 JSON 格式的修改内容 (直接回车跳过): ")
            if mod_input.strip():
                try:
                    modifications = json.loads(mod_input)
                except json.JSONDecodeError:
                    print(self._color("JSON 解析失败，将作为文字反馈处理", "yellow"))
                    feedback = f"{feedback}\n{mod_input}"
        
        elif action == UserAction.REGENERATE:
            feedback = input("请输入重新生成的要求/约束: ")
        
        elif action == UserAction.ADD_CONTEXT_REF:
            node_id = input("请输入要添加引用的节点 ID: ")
            ref_nodes = input("请输入要引用的节点 ID (逗号分隔): ")
            params = {
                "node_id": node_id,
                "ref_nodes": [n.strip() for n in ref_nodes.split(",")],
            }
        
        elif action == UserAction.ROLLBACK:
            checkpoint_id = input("请输入要回滚到的检查点 ID: ")
            params = {"checkpoint_id": checkpoint_id}
        
        return UserFeedback(
            action=action,
            feedback=feedback,
            modifications=modifications,
            params=params,
        )
    
    async def notify_progress(
        self,
        stage: InteractionStage,
        progress: float,
        message: str,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        """通知进度"""
        bar_width = 30
        filled = int(bar_width * progress)
        bar = "█" * filled + "░" * (bar_width - filled)
        
        stage_emoji = {
            InteractionStage.PLAN: "📋",
            InteractionStage.AGENT: "🤖",
            InteractionStage.WORKFLOW: "🔄",
            InteractionStage.EXECUTION: "▶️",
        }
        
        emoji = stage_emoji.get(stage, "⚙️")
        print(f"\r{emoji} [{bar}] {progress*100:.0f}% - {message}", end="", flush=True)
        
        if progress >= 1.0:
            print()  # 换行
    
    async def request_input(
        self,
        prompt: str,
        input_type: str,
        options: Optional[List[str]] = None,
        default: Optional[Any] = None,
    ) -> Any:
        """请求用户输入"""
        if input_type == "confirm":
            default_str = "[Y/n]" if default else "[y/N]"
            response = input(f"{prompt} {default_str}: ").strip().lower()
            if not response:
                return default
            return response in ("y", "yes", "是", "确认")
        
        elif input_type == "choice":
            if options:
                print(f"\n{prompt}")
                for i, opt in enumerate(options, 1):
                    print(f"  [{i}] {opt}")
                
                while True:
                    choice = input("请选择: ")
                    try:
                        idx = int(choice) - 1
                        if 0 <= idx < len(options):
                            return options[idx]
                    except ValueError:
                        pass
                    print(self._color("无效选择", "red"))
        
        elif input_type == "json":
            print(f"{prompt}")
            if default:
                print(f"默认值: {json.dumps(default, ensure_ascii=False)}")
            
            response = input("请输入 JSON: ")
            if not response and default:
                return default
            
            try:
                return json.loads(response)
            except json.JSONDecodeError:
                print(self._color("JSON 解析失败，使用默认值", "yellow"))
                return default
        
        else:  # text
            default_hint = f" [{default}]" if default else ""
            response = input(f"{prompt}{default_hint}: ")
            return response if response else default
    
    async def display_message(
        self,
        message: str,
        level: str = "info",
    ) -> None:
        """显示消息"""
        level_config = {
            "info": ("ℹ️", "blue"),
            "warning": ("⚠️", "yellow"),
            "error": ("❌", "red"),
            "success": ("✅", "green"),
        }
        
        emoji, color = level_config.get(level, ("•", "reset"))
        print(f"{emoji} {self._color(message, color)}")
    
    async def display_diff(
        self,
        before: Dict[str, Any],
        after: Dict[str, Any],
        title: str = "Changes",
    ) -> None:
        """显示差异对比"""
        self._print_section(f"差异对比: {title}")
        
        all_keys = set(before.keys()) | set(after.keys())
        
        for key in sorted(all_keys):
            before_val = before.get(key)
            after_val = after.get(key)
            
            if before_val == after_val:
                continue
            
            if before_val is None:
                print(f"  {self._color(f'+ {key}: {after_val}', 'green')}")
            elif after_val is None:
                print(f"  {self._color(f'- {key}: {before_val}', 'red')}")
            else:
                print(f"  {self._color(f'~ {key}:', 'yellow')}")
                print(f"    - {before_val}")
                print(f"    + {after_val}")
    
    def _display_content(self, content: Dict[str, Any]) -> None:
        """显示内容字典"""
        for key, value in content.items():
            if key in ("agent_definition", "workflow"):
                self._print_section(f"{key}")
                if isinstance(value, dict):
                    # 简化显示
                    display_fields = ["agent_id", "name", "description", "workflow_id"]
                    for field in display_fields:
                        if field in value:
                            print(f"  {field}: {value[field]}")
                    
                    # 显示其他重要字段
                    if "nodes" in value:
                        print(f"  nodes: [{len(value['nodes'])} items]")
                    if "tool_references" in value:
                        tools = [t.get("tool_id") for t in value.get("tool_references", [])]
                        print(f"  tools: {tools}")
                    if "llm_config" in value:
                        print(f"  model: {value['llm_config'].get('model_name')}")
            else:
                print(f"  {key}: {value}")


# ============================================================
# P1: InteractiveWorkflowBuilder 核心流程
# ============================================================


class MaxIterationsExceeded(Exception):
    """超过最大迭代次数异常"""
    pass


class InteractiveWorkflowBuilder:
    """
    交互式工作流构建器 - 支持边生成边调整
    
    核心功能:
    1. 需求理解与方案规划（支持用户审核调整）
    2. 逐步生成 Agents（支持用户审核调整）
    3. 组装 Workflow（支持用户调整依赖和数据引用）
    4. 检查点和回滚
    """
    
    def __init__(
        self,
        meta_agent: Any,  # MetaAgent 类型，避免循环导入
        callback: UserInteractionCallback,
        storage_path: Optional[Path] = None,
        max_iterations_per_step: int = 3,
    ):
        """
        初始化交互式构建器
        
        Args:
            meta_agent: MetaAgent 实例
            callback: 用户交互回调
            storage_path: 存储路径
            max_iterations_per_step: 每步最大迭代次数
        """
        self.meta_agent = meta_agent
        self.callback = callback
        self.max_iterations = max_iterations_per_step
        
        # 状态管理
        self.draft_agents: List[AgentDefinition] = []
        self.draft_workflow: Optional[WorkflowDefinition] = None
        self.current_plan: Optional[WorkflowPlan] = None
        self.task_description: str = ""
        self.current_stage: InteractionStage = InteractionStage.PLAN
        
        # 迭代管理
        self.iteration_manager = IterationManager(
            storage_path= Path(storage_path) / "iterations" if storage_path else None
        )
        
        # 会话状态
        self.session_id = f"session_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        self.is_cancelled = False
    
    def _get_current_state(self) -> BuilderState:
        """获取当前状态"""
        return BuilderState(
            draft_agents=[
                a.model_dump() if hasattr(a, "model_dump") else vars(a)
                for a in self.draft_agents
            ],
            draft_workflow=(
                self.draft_workflow.model_dump()
                if self.draft_workflow and hasattr(self.draft_workflow, "model_dump")
                else None
            ),
            current_stage=self.current_stage,
            plan=self.current_plan.to_dict() if self.current_plan else None,
            iteration_count=len(self.iteration_manager.iterations),
        )
    
    async def start_interactive_session(
        self,
        task_description: str,
        interaction_level: InteractionLevel = InteractionLevel.MODERATE,
        existing_agents: Optional[List[str]] = None,
    ) -> WorkflowDefinition:
        """
        启动交互式工作流构建会话
        
        Args:
            task_description: 任务描述
            interaction_level: 交互级别
            existing_agents: 可复用的已有 Agent ID 列表
            
        Returns:
            构建完成的 WorkflowDefinition
        """
        self.task_description = task_description
        self.is_cancelled = False
        
        await self.callback.display_message(
            f"🚀 启动交互式工作流构建会话: {self.session_id}",
            level="success"
        )
        
        try:
            # Phase 1: 需求理解与方案规划
            self.current_stage = InteractionStage.PLAN
            plan = await self._phase_understand_and_plan(task_description, existing_agents)
            
            if self.is_cancelled:
                raise asyncio.CancelledError("用户取消了会话")
            
            # Phase 2: 逐步生成 Agents
            self.current_stage = InteractionStage.AGENT
            await self._phase_generate_agents(plan, interaction_level)
            
            if self.is_cancelled:
                raise asyncio.CancelledError("用户取消了会话")
            
            # Phase 3: 组装 Workflow
            self.current_stage = InteractionStage.WORKFLOW
            workflow = await self._phase_assemble_workflow(interaction_level)
            
            await self.callback.display_message(
                "🎉 工作流构建完成！",
                level="success"
            )
            
            return workflow
            
        except asyncio.CancelledError:
            await self.callback.display_message(
                "会话已取消",
                level="warning"
            )
            raise
        
        except Exception as e:
            await self.callback.display_message(
                f"构建过程发生错误: {e}",
                level="error"
            )
            raise
    
    async def _phase_understand_and_plan(
        self,
        task_description: str,
        existing_agents: Optional[List[str]] = None,
    ) -> WorkflowPlan:
        """Phase 1: 需求理解与方案规划"""
        await self.callback.notify_progress(
            InteractionStage.PLAN, 0.1, "分析任务需求..."
        )
        
        # 生成初始规划
        plan = await self._generate_plan(task_description, existing_agents)
        
        await self.callback.notify_progress(
            InteractionStage.PLAN, 0.5, "规划生成完成，等待审核..."
        )
        
        # 创建检查点
        self.iteration_manager.checkpoint(
            "initial_plan",
            InteractionStage.PLAN,
            self._get_current_state()
        )
        
        # 请求用户审核
        for i in range(self.max_iterations):
            feedback = await self.callback.request_approval(
                stage=InteractionStage.PLAN,
                content={
                    "plan": plan.to_dict(),
                    "iteration": i + 1,
                },
                options=[
                    UserAction.APPROVE,
                    UserAction.MODIFY,
                    UserAction.REGENERATE,
                    UserAction.CANCEL,
                ],
                context={"existing_agents": existing_agents},
            )
            
            # 记录迭代
            before_state = self._get_current_state().to_dict()
            
            if feedback.action == UserAction.APPROVE:
                self.current_plan = plan
                self.iteration_manager.record_iteration(
                    InteractionStage.PLAN, "approve",
                    before_state, self._get_current_state().to_dict(),
                    feedback
                )
                await self.callback.notify_progress(
                    InteractionStage.PLAN, 1.0, "规划已批准"
                )
                return plan
            
            elif feedback.action == UserAction.MODIFY:
                plan = await self._apply_plan_modifications(plan, feedback)
                self.iteration_manager.record_iteration(
                    InteractionStage.PLAN, "modify",
                    before_state, self._get_current_state().to_dict(),
                    feedback
                )
            
            elif feedback.action == UserAction.REGENERATE:
                plan = await self._generate_plan(
                    task_description,
                    existing_agents,
                    constraints=feedback.feedback,
                )
                self.iteration_manager.record_iteration(
                    InteractionStage.PLAN, "regenerate",
                    before_state, self._get_current_state().to_dict(),
                    feedback
                )
            
            elif feedback.action == UserAction.CANCEL:
                self.is_cancelled = True
                return plan
        
        # 超过最大迭代，使用最后的规划
        self.current_plan = plan
        return plan
    
    async def _generate_plan(
        self,
        task_description: str,
        existing_agents: Optional[List[str]] = None,
        constraints: Optional[str] = None,
        # 新增参数：支持智能迭代
        previous_plans: Optional[List[Dict[str, Any]]] = None,
        user_feedback: Optional[str] = None,
        iteration_context: Optional[str] = None,
    ) -> WorkflowPlan:
        """
        生成工作流规划
        
        支持两种模式：
        1. 初次生成：仅根据 task_description 生成
        2. 智能迭代：结合历史规划和用户反馈，LLM 深度理解后生成新规划
        
        Args:
            task_description: 原始任务描述
            existing_agents: 已有的 Agent 列表（可复用）
            constraints: 额外约束条件
            previous_plans: 历史规划列表（从检查点提取）
            user_feedback: 用户最新反馈/修改要求
            iteration_context: 迭代上下文描述
        """
        # 获取真实可用的工具列表
        available_tools_info = self.meta_agent._get_available_tools_info()
        
        # 构建历史规划上下文
        history_context = self._format_previous_plans(previous_plans) if previous_plans else "无"
        
        # 构建当前规划上下文
        current_plan_context = self._format_current_plan() if self.current_plan else "无"
        
        # 构建用户反馈/迭代说明
        feedback_section = ""
        if user_feedback:
            feedback_section = f"""
## 用户最新反馈/修改要求（重要！）
{user_feedback}

## 迭代说明
{iteration_context or "用户希望基于反馈修改规划"}

## 重要：理解用户意图
- 如果用户要求"整合"、"合并"之前的规划，请分析历史规划中的 Agent，选择合适的加入新规划
- 如果用户提到"上一版"、"之前"的某些 Agent，请从历史规划中找到并整合
- 如果用户要求修改某个 Agent，请在新规划中体现修改
- 如果用户要求添加/删除 Agent，请相应调整
- **新生成的规划必须是完整的、可执行的**，包含所有必要的 Agent 和正确的依赖关系
"""
        
        prompt = f"""你是一个工作流规划专家。请根据以下信息，生成一个完整的工作流规划。

## 原始任务描述
{task_description}

## 历史规划参考
{history_context}

## 当前规划
{current_plan_context}
{feedback_section}
## 已有 Agent（可复用）
{existing_agents or "无"}

## 额外约束
{constraints or "无"}

## Framework 可用工具列表
{available_tools_info}

## 工具选择重要说明
**suggested_tools 必须只使用上述列出的工具 ID，不要虚构工具名称！**

工具选择指南：
1. **外部数据获取**（金融数据、新闻、网页内容、API 调用等）：
   - 必须使用 `qveris_search_tools` 和 `qveris_execute_tool`
   - 不要虚构如 "Web Scraper"、"Financial API"、"News Aggregator" 等工具
   
2. **文件操作**：使用 `file_read`、`file_write`、`file_edit` 等

3. **命令执行**：使用 `bash_execute_safe`

4. **纯 LLM 分析/生成**：如果 Agent 只需要 LLM 思考能力，suggested_tools 可以为空数组

## 输出要求
请输出完整的 JSON 格式规划（包含所有需要的 Agent）：

```json
{{
    "agent_specs": [
        {{
            "name": "Agent 技术名称（英文 CamelCase，如 DataCollectorAgent）",
            "display_name": "用户友好的中文名称（如：数据收集器、趋势分析师）",
            "task": "Agent 职责描述",
            "suggested_tools": ["qveris_search_tools", "qveris_execute_tool"],
            "dependencies": ["依赖的 Agent 名称"],
            "context_refs": ["需要引用数据的 Agent 名称"]
        }}
    ],
    "workflow_structure": "工作流结构的文字描述",
    "estimated_steps": 3,
    "notes": "注意事项"
}}
```

规划原则：
1. 每个 Agent 职责单一明确
2. **display_name 必须是简洁易懂的中文名称**，让用户能直观理解 Agent 的作用
3. 数据收集类 Agent 应该被后续分析/报告 Agent 通过 context_refs 引用
4. 合理设置依赖关系，支持并行执行
5. 考虑错误处理和数据验证
6. **suggested_tools 必须使用真实存在的工具 ID**
"""
        
        response = await self.meta_agent._call_llm(prompt)
        
        # 解析响应
        import re
        json_match = re.search(r"```json\s*([\s\S]*?)\s*```", response)
        if json_match:
            json_str = json_match.group(1)
        else:
            json_str = response
        
        try:
            data = json.loads(json_str)
            
            agent_specs = [
                AgentSpec(
                    name=spec.get("name", f"agent_{i}"),
                    task=spec.get("task", ""),
                    display_name=spec.get("display_name", spec.get("name", f"智能助手{i}")),
                    suggested_tools=spec.get("suggested_tools", []),
                    dependencies=spec.get("dependencies", []),
                    context_refs=spec.get("context_refs", []),
                )
                for i, spec in enumerate(data.get("agent_specs", []))
            ]
            
            return WorkflowPlan(
                task_description=task_description,
                agent_specs=agent_specs,
                workflow_structure=data.get("workflow_structure", ""),
                estimated_steps=data.get("estimated_steps", len(agent_specs) + 2),
                notes=data.get("notes"),
            )
            
        except json.JSONDecodeError as e:
            logger.warning(f"规划解析失败: {e}")
            # 返回默认规划
            return WorkflowPlan(
                task_description=task_description,
                agent_specs=[
                    AgentSpec(
                        name="data_collector",
                        task="数据收集",
                        display_name="数据收集器",
                        suggested_tools=["qveris_search_tools", "qveris_execute_tool"],
                    ),
                    AgentSpec(
                        name="analyzer",
                        task="数据分析",
                        display_name="数据分析师",
                        dependencies=["data_collector"],
                    ),
                    AgentSpec(
                        name="report_generator",
                        task="报告生成",
                        display_name="报告生成器",
                        dependencies=["analyzer"],
                        context_refs=["data_collector"],
                    ),
                ],
                workflow_structure="data_collector → analyzer → report_generator",
                estimated_steps=5,
            )
    
    def _format_previous_plans(self, previous_plans: Optional[List[Dict[str, Any]]]) -> str:
        """格式化历史规划信息，供 LLM 参考"""
        if not previous_plans:
            return "无"
        
        formatted_plans = []
        for i, plan in enumerate(previous_plans):
            plan_text = f"### 历史规划 {i + 1}"
            if plan.get('checkpoint_label'):
                plan_text += f" ({plan['checkpoint_label']})"
            if plan.get('timestamp'):
                plan_text += f" - {plan['timestamp'][:19]}"
            plan_text += "\n"
            
            if plan.get('task_description'):
                plan_text += f"任务描述: {plan['task_description'][:200]}...\n" if len(plan.get('task_description', '')) > 200 else f"任务描述: {plan['task_description']}\n"
            
            agents = plan.get('agents', [])
            if agents:
                plan_text += f"包含 {len(agents)} 个 Agent:\n"
                for agent in agents:
                    name = agent.get('name', 'Unknown')
                    display_name = agent.get('display_name', name)
                    task = agent.get('task', '')[:100]
                    deps = agent.get('dependencies', [])
                    plan_text += f"  - {display_name} ({name}): {task}"
                    if deps:
                        plan_text += f" [依赖: {', '.join(deps)}]"
                    plan_text += "\n"
            
            formatted_plans.append(plan_text)
        
        return "\n".join(formatted_plans)
    
    def _format_current_plan(self) -> str:
        """格式化当前规划信息"""
        if not self.current_plan:
            return "无"
        
        plan = self.current_plan
        result = f"任务描述: {plan.task_description}\n"
        result += f"工作流结构: {plan.workflow_structure or '未定义'}\n"
        result += f"包含 {len(plan.agent_specs)} 个 Agent:\n"
        
        for spec in plan.agent_specs:
            result += f"  - {spec.display_name or spec.name} ({spec.name}): {spec.task}"
            if spec.dependencies:
                result += f" [依赖: {', '.join(spec.dependencies)}]"
            if spec.suggested_tools:
                result += f" [工具: {', '.join(spec.suggested_tools)}]"
            result += "\n"
        
        return result
    
    async def _apply_plan_modifications(
        self,
        plan: WorkflowPlan,
        feedback: UserFeedback,
    ) -> WorkflowPlan:
        """应用用户对规划的修改"""
        if feedback.modifications:
            # 直接应用 JSON 修改
            if "agent_specs" in feedback.modifications:
                plan.agent_specs = [
                    AgentSpec(**spec) if isinstance(spec, dict) else spec
                    for spec in feedback.modifications["agent_specs"]
                ]
            if "workflow_structure" in feedback.modifications:
                plan.workflow_structure = feedback.modifications["workflow_structure"]
            if "notes" in feedback.modifications:
                plan.notes = feedback.modifications["notes"]
        
        elif feedback.feedback:
            # 使用 LLM 理解并应用文字修改
            prompt = f"""根据用户反馈修改规划。

## 当前规划
{json.dumps(plan.to_dict(), ensure_ascii=False, indent=2)}

## 用户反馈
{feedback.feedback}

## 输出要求
输出修改后的完整规划 JSON。
"""
            response = await self.meta_agent._call_llm(prompt)
            
            import re
            json_match = re.search(r"```json\s*([\s\S]*?)\s*```", response)
            if json_match:
                try:
                    data = json.loads(json_match.group(1))
                    plan.agent_specs = [
                        AgentSpec(**spec) for spec in data.get("agent_specs", [])
                    ]
                    plan.workflow_structure = data.get("workflow_structure", plan.workflow_structure)
                    plan.notes = data.get("notes", plan.notes)
                except json.JSONDecodeError:
                    pass
        
        return plan
    
    async def _phase_generate_agents(
        self,
        plan: WorkflowPlan,
        interaction_level: InteractionLevel,
    ) -> None:
        """Phase 2: 逐步生成 Agents"""
        total_agents = len(plan.agent_specs)
        
        for i, spec in enumerate(plan.agent_specs):
            progress = (i + 0.5) / total_agents
            await self.callback.notify_progress(
                InteractionStage.AGENT,
                progress,
                f"生成 Agent: {spec.name} ({i+1}/{total_agents})"
            )
            
            agent = await self._generate_agent_with_review(
                spec, 
                interaction_level,
                i + 1,
                total_agents,
            )
            
            if agent:
                self.draft_agents.append(agent)
            
            if self.is_cancelled:
                return
            
            # 创建检查点
            self.iteration_manager.checkpoint(
                f"agent_{spec.name}_completed",
                InteractionStage.AGENT,
                self._get_current_state()
            )
        
        await self.callback.notify_progress(
            InteractionStage.AGENT, 1.0,
            f"所有 Agent 生成完成 ({len(self.draft_agents)}/{total_agents})"
        )
    
    async def _generate_agent_with_review(
        self,
        spec: AgentSpec,
        interaction_level: InteractionLevel,
        current_num: int,
        total_num: int,
    ) -> Optional[AgentDefinition]:
        """生成单个 Agent 并支持审核调整"""
        
        for i in range(self.max_iterations):
            # 生成 Agent
            agent = await self.meta_agent.create_agent(
                task_description=spec.task,
                tools=spec.suggested_tools if spec.suggested_tools else None,
                constraints={
                    "name_hint": spec.name,
                    "dependencies": spec.dependencies,
                    "context_refs": spec.context_refs,
                },
            )
            
            # 根据交互级别决定是否请求审核
            if interaction_level == InteractionLevel.MINIMAL and i == 0:
                # 最小交互级别：第一次直接通过
                return agent
            
            # 请求审核
            feedback = await self.callback.request_approval(
                stage=InteractionStage.AGENT,
                content={
                    "agent_definition": (
                        agent.model_dump() if hasattr(agent, "model_dump") 
                        else vars(agent)
                    ),
                    "spec": spec.to_dict(),
                    "iteration": i + 1,
                    "progress": f"{current_num}/{total_num}",
                },
                options=[
                    UserAction.APPROVE,
                    UserAction.MODIFY,
                    UserAction.REGENERATE,
                    UserAction.SKIP,
                    UserAction.ROLLBACK,
                    UserAction.CANCEL,
                ],
                context={
                    "previous_agents": [a.agent_id for a in self.draft_agents],
                    "remaining": total_num - current_num,
                }
            )
            
            before_state = self._get_current_state().to_dict()
            
            if feedback.action == UserAction.APPROVE:
                self.iteration_manager.record_iteration(
                    InteractionStage.AGENT, "approve",
                    before_state, self._get_current_state().to_dict(),
                    feedback, {"agent_id": agent.agent_id}
                )
                return agent
            
            elif feedback.action == UserAction.MODIFY:
                agent = await self._apply_agent_modifications(agent, feedback)
                self.iteration_manager.record_iteration(
                    InteractionStage.AGENT, "modify",
                    before_state, self._get_current_state().to_dict(),
                    feedback, {"agent_id": agent.agent_id}
                )
                return agent
            
            elif feedback.action == UserAction.REGENERATE:
                # 更新 spec 并重新生成
                if feedback.feedback:
                    spec.task = f"{spec.task}\n额外要求: {feedback.feedback}"
                self.iteration_manager.record_iteration(
                    InteractionStage.AGENT, "regenerate",
                    before_state, self._get_current_state().to_dict(),
                    feedback
                )
                continue
            
            elif feedback.action == UserAction.SKIP:
                self.iteration_manager.record_iteration(
                    InteractionStage.AGENT, "skip",
                    before_state, self._get_current_state().to_dict(),
                    feedback
                )
                return None
            
            elif feedback.action == UserAction.ROLLBACK:
                if feedback.params and "checkpoint_id" in feedback.params:
                    state = self.iteration_manager.rollback(feedback.params["checkpoint_id"])
                    self._restore_state(state)
                    await self.callback.display_message(
                        f"已回滚到检查点: {feedback.params['checkpoint_id']}",
                        level="info"
                    )
                return None
            
            elif feedback.action == UserAction.CANCEL:
                self.is_cancelled = True
                return None
        
        # 超过最大迭代，返回最后生成的 agent
        await self.callback.display_message(
            f"Agent {spec.name} 超过最大迭代次数，使用最后版本",
            level="warning"
        )
        return agent
    
    async def _apply_agent_modifications(
        self,
        agent: AgentDefinition,
        feedback: UserFeedback,
    ) -> AgentDefinition:
        """应用用户对 Agent 的修改"""
        agent_dict = agent.model_dump() if hasattr(agent, "model_dump") else vars(agent)
        
        if feedback.modifications:
            # 直接应用 JSON 修改
            for key, value in feedback.modifications.items():
                if key in agent_dict:
                    agent_dict[key] = value
        
        elif feedback.feedback:
            # 使用 LLM 理解并应用文字修改
            optimized = await self.meta_agent.optimize_prompt(
                agent_id=agent.agent_id,
                feedback_history=[{
                    "task": "用户修改请求",
                    "success": False,
                    "feedback": feedback.feedback,
                }]
            )
            return optimized
        
        return AgentDefinition(**agent_dict)
    
    async def _phase_assemble_workflow(
        self,
        interaction_level: InteractionLevel,
    ) -> WorkflowDefinition:
        """Phase 3: 组装工作流"""
        await self.callback.notify_progress(
            InteractionStage.WORKFLOW, 0.2, "组装工作流..."
        )
        
        # 确保所有草稿 Agent 都注册到 AgentRegistry
        for agent in self.draft_agents:
            if not self.meta_agent.agent_registry.get_definition(agent.agent_id):
                self.meta_agent.agent_registry.register_definition(agent)
                logger.debug(f"注册草稿 Agent: {agent.agent_id}")
        
        # 生成初始工作流
        workflow = await self.meta_agent.generate_workflow(
            task_description=self.task_description,
            available_agents=[a.agent_id for a in self.draft_agents],
        )
        
        self.draft_workflow = workflow
        
        # 创建检查点
        self.iteration_manager.checkpoint(
            "initial_workflow",
            InteractionStage.WORKFLOW,
            self._get_current_state()
        )
        
        await self.callback.notify_progress(
            InteractionStage.WORKFLOW, 0.5, "工作流生成完成，等待审核..."
        )
        
        # 交互式调整
        for i in range(self.max_iterations):
            feedback = await self.callback.request_approval(
                stage=InteractionStage.WORKFLOW,
                content={
                    "workflow": (
                        workflow.model_dump() if hasattr(workflow, "model_dump")
                        else vars(workflow)
                    ),
                    "visualization": self._visualize_workflow(workflow),
                    "iteration": i + 1,
                },
                options=[
                    UserAction.APPROVE,
                    UserAction.MODIFY,
                    UserAction.ADD_CONTEXT_REF,
                    UserAction.REGENERATE,
                    UserAction.ROLLBACK,
                    UserAction.CANCEL,
                ],
                context={
                    "agents": [a.agent_id for a in self.draft_agents],
                    "checkpoints": [
                        c.checkpoint_id 
                        for c in self.iteration_manager.get_checkpoints()[-5:]
                    ],
                }
            )
            
            before_state = self._get_current_state().to_dict()
            
            if feedback.action == UserAction.APPROVE:
                self.iteration_manager.record_iteration(
                    InteractionStage.WORKFLOW, "approve",
                    before_state, self._get_current_state().to_dict(),
                    feedback
                )
                await self.callback.notify_progress(
                    InteractionStage.WORKFLOW, 1.0, "工作流已批准"
                )
                return workflow
            
            elif feedback.action == UserAction.ADD_CONTEXT_REF:
                if feedback.params:
                    workflow = self._add_context_refs(
                        workflow,
                        feedback.params.get("node_id"),
                        feedback.params.get("ref_nodes", []),
                    )
                    self.draft_workflow = workflow
                self.iteration_manager.record_iteration(
                    InteractionStage.WORKFLOW, "add_context_ref",
                    before_state, self._get_current_state().to_dict(),
                    feedback
                )
            
            elif feedback.action == UserAction.MODIFY:
                workflow = await self._apply_workflow_modifications(workflow, feedback)
                self.draft_workflow = workflow
                self.iteration_manager.record_iteration(
                    InteractionStage.WORKFLOW, "modify",
                    before_state, self._get_current_state().to_dict(),
                    feedback
                )
            
            elif feedback.action == UserAction.REGENERATE:
                workflow = await self.meta_agent.generate_workflow(
                    task_description=self.task_description,
                    available_agents=[a.agent_id for a in self.draft_agents],
                    constraints={"user_feedback": feedback.feedback} if feedback.feedback else None,
                )
                self.draft_workflow = workflow
                self.iteration_manager.record_iteration(
                    InteractionStage.WORKFLOW, "regenerate",
                    before_state, self._get_current_state().to_dict(),
                    feedback
                )
            
            elif feedback.action == UserAction.ROLLBACK:
                if feedback.params and "checkpoint_id" in feedback.params:
                    state = self.iteration_manager.rollback(feedback.params["checkpoint_id"])
                    self._restore_state(state)
                    workflow = self.draft_workflow
            
            elif feedback.action == UserAction.CANCEL:
                self.is_cancelled = True
                return workflow
        
        return workflow
    
    def _visualize_workflow(self, workflow: WorkflowDefinition) -> str:
        """可视化工作流结构"""
        lines = ["", "工作流结构:", ""]
        
        # 构建节点依赖图
        for node in workflow.nodes:
            deps = node.dependencies if node.dependencies else []
            refs = node.context_refs if node.context_refs else []
            
            node_str = f"  [{node.node_id}] {node.name}"
            if node.agent_id:
                node_str += f" (Agent: {node.agent_id})"
            
            lines.append(node_str)
            
            if deps:
                lines.append(f"    ↑ 依赖: {', '.join(deps)}")
            if refs:
                lines.append(f"    📎 数据引用: {', '.join(refs)}")
        
        # 绘制简单的流程图
        lines.append("")
        lines.append("执行流程:")
        
        edges_str = []
        for edge in workflow.edges:
            edges_str.append(f"  {edge.from_node} → {edge.to_node}")
        
        lines.extend(edges_str)
        
        return "\n".join(lines)
    
    def _add_context_refs(
        self,
        workflow: WorkflowDefinition,
        node_id: str,
        ref_nodes: List[str],
    ) -> WorkflowDefinition:
        """添加上下文引用"""
        for node in workflow.nodes:
            if node.node_id == node_id:
                existing_refs = set(node.context_refs or [])
                existing_refs.update(ref_nodes)
                node.context_refs = list(existing_refs)
                logger.info(f"为节点 {node_id} 添加 context_refs: {ref_nodes}")
                break
        
        return workflow
    
    async def _apply_workflow_modifications(
        self,
        workflow: WorkflowDefinition,
        feedback: UserFeedback,
    ) -> WorkflowDefinition:
        """应用用户对工作流的修改"""
        if feedback.modifications:
            # 直接应用 JSON 修改
            workflow_dict = (
                workflow.model_dump() if hasattr(workflow, "model_dump")
                else vars(workflow)
            )
            
            for key, value in feedback.modifications.items():
                if key == "nodes" and isinstance(value, list):
                    # 更新节点
                    for node_mod in value:
                        node_id = node_mod.get("node_id")
                        for node in workflow.nodes:
                            if node.node_id == node_id:
                                for k, v in node_mod.items():
                                    if hasattr(node, k):
                                        setattr(node, k, v)
                                break
                elif key in workflow_dict:
                    workflow_dict[key] = value
        
        elif feedback.feedback:
            # 使用优化方法
            workflow = await self.meta_agent.optimize_workflow(
                workflow=workflow,
                execution_history=[{
                    "success": False,
                    "feedback": feedback.feedback,
                }],
                optimization_goal="user_feedback",
            )
        
        return workflow
    
    def _restore_state(self, state: BuilderState) -> None:
        """恢复状态"""
        from ..definitions import AgentDefinition, WorkflowDefinition
        
        self.draft_agents = [
            AgentDefinition(**a) for a in state.draft_agents
        ]
        
        if state.draft_workflow:
            self.draft_workflow = WorkflowDefinition(**state.draft_workflow)
        else:
            self.draft_workflow = None
        
        self.current_stage = state.current_stage
        
        if state.plan:
            self.current_plan = WorkflowPlan(
                task_description=state.plan["task_description"],
                agent_specs=[AgentSpec(**s) for s in state.plan["agent_specs"]],
                workflow_structure=state.plan["workflow_structure"],
                estimated_steps=state.plan["estimated_steps"],
                notes=state.plan.get("notes"),
            )
    
    def get_session_summary(self) -> Dict[str, Any]:
        """获取会话摘要"""
        return {
            "session_id": self.session_id,
            "task_description": self.task_description,
            "current_stage": self.current_stage.value,
            "agents_created": len(self.draft_agents),
            "workflow_created": self.draft_workflow is not None,
            "total_iterations": len(self.iteration_manager.iterations),
            "checkpoints": len(self.iteration_manager.checkpoints),
            "history": self.iteration_manager.export_history(),
        }
