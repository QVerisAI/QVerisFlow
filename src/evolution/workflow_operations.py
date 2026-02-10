"""
工作流操作工具

将工作流操作封装为可被 LLM 调用的工具函数
"""

from dataclasses import dataclass, field
from typing import Dict, Any, Optional, List, TYPE_CHECKING, Callable, Awaitable
from datetime import datetime
from pathlib import Path
import json
import traceback
import asyncio
from src.utils.logger import get_logger

if TYPE_CHECKING:
    from .interactive_builder import InteractiveWorkflowBuilder, AgentSpec, WorkflowPlan
    from .meta_agent import MetaAgent
    from src.orchestration.workflow_engine import WorkflowEngine

logger = get_logger()


@dataclass
class OperationResult:
    """操作结果"""

    success: bool
    message: str
    data: Optional[Dict[str, Any]] = None
    workflow_changed: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "message": self.message,
            "data": self.data,
            "workflow_changed": self.workflow_changed,
        }


class WorkflowOperationTools:
    """
    工作流操作工具集

    将所有工作流操作封装为可被 LLM 调用的方法。
    每个方法对应一个 LLM 可调用的工具。
    """

    def __init__(
        self,
        meta_agent: "MetaAgent",
        storage_path: Optional[str] = None,
        tool_registry: Optional[Any] = None,
    ):
        """
        初始化工具集

        Args:
            meta_agent: MetaAgent 实例
            storage_path: 存储路径
            tool_registry: 工具注册表（用于验证工具）
        """
        from .interactive_builder import (
            InteractiveWorkflowBuilder,
            AgentSpec,
            WorkflowPlan,
            InteractionStage,
        )

        self.meta_agent = meta_agent
        self.storage_path = storage_path
        self.tool_registry = tool_registry

        # 延迟初始化的 builder
        self._builder: Optional["InteractiveWorkflowBuilder"] = None

        # 工作流引擎（用于执行）
        self._workflow_engine: Optional["WorkflowEngine"] = None

        # 失败的 Agent 列表（用于支持重新生成）
        self._failed_agents: List[Dict[str, Any]] = []

        # 执行状态（实际状态由 WorkflowEngine 的 ExecutionFSM 管理）
        self._execution_task = None
        self._current_workflow_id: Optional[str] = None  # 当前执行的工作流 ID

        # 任务描述
        self._task_description: str = ""

        # 缓存的有效工具列表
        self._valid_tools_cache: Optional[set] = None

        # 进度回调
        self._progress_callback: Optional[
            Callable[[Dict[str, Any]], Awaitable[None]]
        ] = None

    def set_progress_callback(
        self, callback: Optional[Callable[[Dict[str, Any]], Awaitable[None]]]
    ) -> None:
        """设置进度回调函数"""
        self._progress_callback = callback

    @property
    def builder(self) -> Optional["InteractiveWorkflowBuilder"]:
        return self._builder

    @property
    def fsm(self):
        """便捷访问构建器的状态机"""
        if self._builder:
            return self._builder.fsm
        return None

    def _ensure_builder(self) -> bool:
        """确保 builder 已初始化"""
        return self._builder is not None

    def _init_builder(self, task_description: str) -> None:
        """
        初始化构建器
        
        当为已加载的工作流创建新规划时，会保留数据库 ID 和 FSM 状态，
        以确保后续保存时能正确更新（而不是创建新的）工作流和 Agent。
        """
        from .interactive_builder import InteractiveWorkflowBuilder, BuilderStateMachine, ArtifactStatus

        self._task_description = task_description

        # 保存现有 builder 的状态（如果有的话）
        old_workflow_db_id = None
        old_agent_db_ids = {}
        is_loaded_workflow = False
        if self._builder:
            old_workflow_db_id = getattr(self._builder, "loaded_workflow_db_id", None)
            old_agent_db_ids = getattr(self._builder, "loaded_agent_db_ids", {})
            is_loaded_workflow = old_workflow_db_id is not None

        self._builder = InteractiveWorkflowBuilder(
            meta_agent=self.meta_agent,
            callback=None,  # 不使用回调，由 DialogueAgent 处理
            storage_path=self.storage_path,
            max_iterations_per_step=3,
        )

        # 恢复数据库 ID（确保更新操作能正确识别已存在的工作流和 Agent）
        if old_workflow_db_id:
            self._builder.loaded_workflow_db_id = old_workflow_db_id
        if old_agent_db_ids:
            self._builder.loaded_agent_db_ids = old_agent_db_ids

        # 如果是已加载的工作流，初始化 FSM 到"已有制品但需要更新"状态
        # 这确保 FSM 状态与数据库 ID 状态一致
        if is_loaded_workflow:
            self._builder.fsm = BuilderStateMachine(
                # 新规划将被创建，所以 plan 初始化为 ABSENT（on_plan_created 会设为 CURRENT）
                plan_status=ArtifactStatus.ABSENT,
                # 已有 agents，但基于旧规划，所以是 STALE
                # 这会让 resolve_approve() 返回 REGENERATE_ALL_AGENTS
                agents_status=ArtifactStatus.STALE,
                # 已有 workflow，但需要重新组装
                workflow_status=ArtifactStatus.STALE,
                # 版本号保持一致性
                plan_version=0,
                agents_version=1,  # 表示已有 agents
                workflow_version=1,  # 表示已有 workflow
                agents_based_on_plan_version=0,  # 旧规划版本
                workflow_based_on_agents_version=0,  # 需要重新组装
            )
            logger.info(
                f"为已加载的工作流初始化 builder: workflow_db_id={old_workflow_db_id}, "
                f"agent_db_ids={list(old_agent_db_ids.keys())}"
            )
        self._builder.task_description = task_description

    def _get_executions_path(self) -> Path:
        """
        获取执行记录存储路径（确保所有方法使用一致的路径）

        Returns:
            执行记录存储目录的 Path 对象
        """
        if self.storage_path:
            return Path(self.storage_path) / "executions"
        elif self._builder and hasattr(self._builder, "storage_path"):
            return Path(self._builder.storage_path) / "executions"
        else:
            return Path("./workspaces/workflow_executions")

    # ========== 创建操作 ==========

    async def create_workflow_plan(
        self,
        task_description: str,
    ) -> OperationResult:
        """
        创建新的工作流规划

        Args:
            task_description: 任务描述

        Returns:
            操作结果，包含生成的规划
        """
        try:
            # 初始化 builder
            self._init_builder(task_description)

            # 生成规划
            plan = await self._builder._generate_plan(task_description)

            if plan:
                self._builder.current_plan = plan

                # 通知状态机：规划已创建
                self._builder.fsm.on_plan_created()

                # 创建检查点
                self._builder.iteration_manager.checkpoint(
                    label="initial_plan",
                    stage=self._builder.current_stage,
                    state=self._builder._get_current_state(),
                )

                return OperationResult(
                    success=True,
                    message=f"已创建工作流规划，包含 {len(plan.agent_specs)} 个 Agent",
                    data={"plan": plan.to_dict()},
                    workflow_changed=True,
                )
            else:
                return OperationResult(
                    success=False,
                    message="无法生成工作流规划",
                )

        except Exception as e:
            logger.error(
                f"创建工作流规划失败: {e}, traceback: {traceback.format_exc()}"
            )
            return OperationResult(success=False, message=str(e))

    # ========== Plan 操作 ==========

    async def add_agent_to_plan(
        self,
        name: str,
        task: str,
        display_name: Optional[str] = None,
        dependencies: Optional[List[str]] = None,
        tools: Optional[List[str]] = None,
        position: str = "auto",
    ) -> OperationResult:
        """
        向规划中添加新的 Agent

        Args:
            name: Agent 技术名称
            task: Agent 任务描述
            display_name: 用户友好的显示名称（如不提供，使用 name）
            dependencies: 依赖的 Agent 名称列表
            tools: 使用的工具列表
            position: 位置 - "auto", "start", "end", "after:AgentName", "before:AgentName"

        Returns:
            操作结果
        """
        from .interactive_builder import AgentSpec

        if not self._ensure_builder():
            return OperationResult(success=False, message="请先创建工作流规划")

        if not self._builder.current_plan:
            return OperationResult(success=False, message="当前没有工作流规划")

        try:
            # 获取现有 agent 名称
            existing_names = [
                spec.name for spec in self._builder.current_plan.agent_specs
            ]

            # 检查名称是否重复
            if name in existing_names:
                return OperationResult(success=False, message=f"Agent '{name}' 已存在")

            # 处理依赖
            deps = dependencies or []
            # 验证依赖是否存在
            for dep in deps:
                if dep not in existing_names:
                    return OperationResult(
                        success=False, message=f"依赖的 Agent '{dep}' 不存在"
                    )

            # 根据 position 确定实际依赖
            if position == "auto" and not deps:
                # 自动推断：依赖最后一个没有被依赖的 agent
                if existing_names:
                    # 找出哪些 agent 没有被其他 agent 依赖
                    dependents = set()
                    for spec in self._builder.current_plan.agent_specs:
                        dependents.update(spec.dependencies)

                    # 找到"叶子"节点
                    leaves = [n for n in existing_names if n not in dependents]
                    if leaves:
                        deps = leaves[-1:]  # 依赖最后一个叶子

            elif position.startswith("after:"):
                after_agent = position[6:]
                if after_agent in existing_names:
                    deps = [after_agent]

            elif position.startswith("before:"):
                before_agent = position[7:]
                # 让 before_agent 依赖新 agent
                # 这需要在添加后修改
                pass

            # 验证并过滤工具列表 - 只保留内置工具
            validated_tools = (
                self._validate_tools(tools)
                if tools
                else ["qveris_search_tools", "qveris_execute_tool"]
            )

            # 创建新的 AgentSpec
            new_spec = AgentSpec(
                name=name,
                task=task,
                display_name=display_name or name,
                suggested_tools=validated_tools,
                dependencies=deps,
                context_refs=[],
            )

            # 添加到规划
            self._builder.current_plan.agent_specs.append(new_spec)

            # 处理 before 位置
            if position.startswith("before:"):
                before_agent = position[7:]
                for spec in self._builder.current_plan.agent_specs:
                    if spec.name == before_agent:
                        if name not in spec.dependencies:
                            spec.dependencies.append(name)
                        break

            # 更新工作流结构描述
            self._builder.current_plan.workflow_structure = (
                self._generate_workflow_structure()
            )

            # 通知状态机：规划被修改（新增 spec）
            self._builder.fsm.on_plan_modified(added_specs=[name])

            # 创建检查点
            self._builder.iteration_manager.checkpoint(
                label=f"add_agent_{name}",
                stage=self._builder.current_stage,
                state=self._builder._get_current_state(),
            )

            # 使用显示名称进行用户友好的反馈
            friendly_name = display_name or name
            pending_msg = self._builder.fsm.describe_pending()
            msg = f"已添加「{friendly_name}」到工作流规划"
            if pending_msg:
                msg += f"\n{pending_msg}"
            return OperationResult(
                success=True,
                message=msg,
                data={"plan": self._builder.current_plan.to_dict()},
                workflow_changed=True,
            )

        except Exception as e:
            logger.error(f"添加 Agent 失败: {e}, traceback: {traceback.format_exc()}")
            return OperationResult(success=False, message=str(e))

    async def remove_agent_from_plan(self, agent_name: str) -> OperationResult:
        """
        从规划中移除 Agent

        Args:
            agent_name: 要移除的 Agent 名称

        Returns:
            操作结果
        """
        if not self._ensure_builder() or not self._builder.current_plan:
            return OperationResult(success=False, message="当前没有工作流规划")

        try:
            # 查找要移除的 agent
            spec_to_remove = None
            for spec in self._builder.current_plan.agent_specs:
                if spec.name.lower() == agent_name.lower():
                    spec_to_remove = spec
                    break

            if not spec_to_remove:
                return OperationResult(
                    success=False, message=f"未找到 Agent: {agent_name}"
                )

            # 移除
            self._builder.current_plan.agent_specs.remove(spec_to_remove)

            # 清理其他 agent 中对此 agent 的依赖
            for spec in self._builder.current_plan.agent_specs:
                if spec_to_remove.name in spec.dependencies:
                    spec.dependencies.remove(spec_to_remove.name)
                if spec_to_remove.name in spec.context_refs:
                    spec.context_refs.remove(spec_to_remove.name)

            # 更新结构描述
            self._builder.current_plan.workflow_structure = (
                self._generate_workflow_structure()
            )

            # 通知状态机：规划被修改（移除 spec）
            self._builder.fsm.on_plan_modified(removed_specs=[spec_to_remove.name])

            # 创建检查点
            self._builder.iteration_manager.checkpoint(
                label=f"remove_agent_{agent_name}",
                stage=self._builder.current_stage,
                state=self._builder._get_current_state(),
            )

            # 使用显示名称进行用户友好的反馈
            friendly_name = spec_to_remove.display_name or spec_to_remove.name
            return OperationResult(
                success=True,
                message=f"已移除「{friendly_name}」",
                data={"plan": self._builder.current_plan.to_dict()},
                workflow_changed=True,
            )

        except Exception as e:
            logger.error(f"移除 Agent 失败: {e}, traceback: {traceback.format_exc()}")
            return OperationResult(success=False, message=str(e))

    async def modify_agent_spec(
        self,
        agent_name: str,
        new_name: Optional[str] = None,
        new_display_name: Optional[str] = None,
        new_task: Optional[str] = None,
        add_dependencies: Optional[List[str]] = None,
        remove_dependencies: Optional[List[str]] = None,
        add_tools: Optional[List[str]] = None,
        remove_tools: Optional[List[str]] = None,
    ) -> OperationResult:
        """
        修改 Agent 规格

        Args:
            agent_name: 要修改的 Agent 名称
            new_name: 新名称（可选）
            new_display_name: 新显示名称（可选）
            new_task: 新任务描述（可选）
            add_dependencies: 要添加的依赖（可选）
            remove_dependencies: 要移除的依赖（可选）
            add_tools: 要添加的工具（可选）
            remove_tools: 要移除的工具（可选）

        Returns:
            操作结果
        """
        if not self._ensure_builder() or not self._builder.current_plan:
            return OperationResult(success=False, message="当前没有工作流规划")

        try:
            # 查找 agent
            target_spec = None
            for spec in self._builder.current_plan.agent_specs:
                if spec.name.lower() == agent_name.lower():
                    target_spec = spec
                    break

            if not target_spec:
                return OperationResult(
                    success=False, message=f"未找到 Agent: {agent_name}"
                )

            changes = []
            old_name = target_spec.name

            # 修改名称
            if new_name and new_name != target_spec.name:
                # 更新其他 agent 中的引用
                for spec in self._builder.current_plan.agent_specs:
                    if old_name in spec.dependencies:
                        spec.dependencies = [
                            new_name if d == old_name else d for d in spec.dependencies
                        ]
                    if old_name in spec.context_refs:
                        spec.context_refs = [
                            new_name if r == old_name else r for r in spec.context_refs
                        ]
                target_spec.name = new_name
                changes.append(f"技术名称改为 {new_name}")

            # 修改显示名称
            if new_display_name and new_display_name != target_spec.display_name:
                target_spec.display_name = new_display_name
                changes.append(f"显示名称改为「{new_display_name}」")

            # 修改任务
            if new_task:
                target_spec.task = new_task
                changes.append("更新了任务描述")

            # 修改依赖
            if add_dependencies:
                for dep in add_dependencies:
                    if dep not in target_spec.dependencies:
                        target_spec.dependencies.append(dep)
                changes.append(f"添加依赖: {add_dependencies}")

            if remove_dependencies:
                target_spec.dependencies = [
                    d for d in target_spec.dependencies if d not in remove_dependencies
                ]
                changes.append(f"移除依赖: {remove_dependencies}")

            # 修改工具
            if add_tools:
                for tool in add_tools:
                    if tool not in target_spec.suggested_tools:
                        target_spec.suggested_tools.append(tool)
                changes.append(f"添加工具: {add_tools}")

            if remove_tools:
                target_spec.suggested_tools = [
                    t for t in target_spec.suggested_tools if t not in remove_tools
                ]
                changes.append(f"移除工具: {remove_tools}")

            if not changes:
                return OperationResult(success=True, message="没有需要修改的内容")

            # 更新结构描述
            self._builder.current_plan.workflow_structure = (
                self._generate_workflow_structure()
            )

            # 通知状态机：规划被修改
            self._builder.fsm.on_plan_modified()

            # 创建检查点
            self._builder.iteration_manager.checkpoint(
                label=f"modify_agent_{agent_name}",
                stage=self._builder.current_stage,
                state=self._builder._get_current_state(),
            )

            # 使用显示名称进行用户友好的反馈
            friendly_name = target_spec.display_name or target_spec.name
            return OperationResult(
                success=True,
                message=f"已修改「{friendly_name}」",
                data={"plan": self._builder.current_plan.to_dict()},
                workflow_changed=True,
            )

        except Exception as e:
            logger.error(f"修改 Agent 失败: {e}, traceback: {traceback.format_exc()}")
            return OperationResult(success=False, message=str(e))

    async def modify_dependencies(
        self,
        agent_name: str,
        depends_on: List[str],
    ) -> OperationResult:
        """
        修改 Agent 的依赖关系（完全替换）

        Args:
            agent_name: Agent 名称
            depends_on: 新的依赖列表（完全替换现有依赖）

        Returns:
            操作结果
        """
        if not self._ensure_builder() or not self._builder.current_plan:
            return OperationResult(success=False, message="当前没有工作流规划")

        try:
            # 查找 agent
            target_spec = None
            existing_names = []
            for spec in self._builder.current_plan.agent_specs:
                existing_names.append(spec.name)
                if spec.name.lower() == agent_name.lower():
                    target_spec = spec

            if not target_spec:
                return OperationResult(
                    success=False, message=f"未找到 Agent: {agent_name}"
                )

            # 验证依赖
            for dep in depends_on:
                if dep not in existing_names:
                    return OperationResult(
                        success=False, message=f"依赖的 Agent '{dep}' 不存在"
                    )
                if dep == target_spec.name:
                    return OperationResult(success=False, message="Agent 不能依赖自己")

            # 更新依赖
            old_deps = target_spec.dependencies.copy()
            target_spec.dependencies = depends_on

            # 更新结构描述
            self._builder.current_plan.workflow_structure = (
                self._generate_workflow_structure()
            )

            # 通知状态机：规划被修改
            self._builder.fsm.on_plan_modified()

            # 创建检查点
            self._builder.iteration_manager.checkpoint(
                label=f"modify_deps_{agent_name}",
                stage=self._builder.current_stage,
                state=self._builder._get_current_state(),
            )

            # 使用显示名称进行用户友好的反馈
            friendly_name = target_spec.display_name or target_spec.name
            return OperationResult(
                success=True,
                message=f"已更新「{friendly_name}」的依赖关系",
                data={"plan": self._builder.current_plan.to_dict()},
                workflow_changed=True,
            )

        except Exception as e:
            logger.error(f"修改依赖失败: {e}, traceback: {traceback.format_exc()}")
            return OperationResult(success=False, message=str(e))

    async def set_parallel_agents(
        self,
        agent_names: List[str],
    ) -> OperationResult:
        """
        设置多个 Agent 并行执行（移除它们之间的依赖）

        Args:
            agent_names: 要并行执行的 Agent 名称列表

        Returns:
            操作结果
        """
        if not self._ensure_builder() or not self._builder.current_plan:
            return OperationResult(success=False, message="当前没有工作流规划")

        try:
            # 验证所有 agent 存在
            existing_names = [
                spec.name for spec in self._builder.current_plan.agent_specs
            ]
            for name in agent_names:
                if name not in existing_names:
                    return OperationResult(
                        success=False, message=f"Agent '{name}' 不存在"
                    )

            # 移除这些 agent 之间的相互依赖
            for spec in self._builder.current_plan.agent_specs:
                if spec.name in agent_names:
                    # 移除对其他并行 agent 的依赖
                    spec.dependencies = [
                        d for d in spec.dependencies if d not in agent_names
                    ]

            # 更新结构描述
            self._builder.current_plan.workflow_structure = (
                self._generate_workflow_structure()
            )

            # 通知状态机：规划被修改
            self._builder.fsm.on_plan_modified()

            # 创建检查点
            self._builder.iteration_manager.checkpoint(
                label=f"set_parallel_{len(agent_names)}",
                stage=self._builder.current_stage,
                state=self._builder._get_current_state(),
            )

            return OperationResult(
                success=True,
                message=f"已设置并行执行: {', '.join(agent_names)}",
                workflow_changed=True,
            )

        except Exception as e:
            logger.error(f"设置并行执行失败: {e}, traceback: {traceback.format_exc()}")
            return OperationResult(success=False, message=str(e))

    async def reorder_workflow(
        self,
        new_order: List[str],
    ) -> OperationResult:
        """
        重新排序工作流中的 Agent

        Args:
            new_order: 新的执行顺序（Agent 名称列表）

        Returns:
            操作结果
        """
        if not self._ensure_builder() or not self._builder.current_plan:
            return OperationResult(success=False, message="当前没有工作流规划")

        try:
            existing_specs = {
                spec.name: spec for spec in self._builder.current_plan.agent_specs
            }

            # 验证所有名称
            for name in new_order:
                if name not in existing_specs:
                    return OperationResult(
                        success=False, message=f"Agent '{name}' 不存在"
                    )

            # 重新排列并更新依赖
            new_specs = []
            for i, name in enumerate(new_order):
                spec = existing_specs[name]
                # 更新依赖：依赖于前面的 agent
                if i > 0:
                    spec.dependencies = [new_order[i - 1]]
                else:
                    spec.dependencies = []
                new_specs.append(spec)

            self._builder.current_plan.agent_specs = new_specs

            # 更新结构描述
            self._builder.current_plan.workflow_structure = (
                self._generate_workflow_structure()
            )

            # 通知状态机：规划被修改
            self._builder.fsm.on_plan_modified()

            # 创建检查点
            self._builder.iteration_manager.checkpoint(
                label="reorder_workflow",
                stage=self._builder.current_stage,
                state=self._builder._get_current_state(),
            )

            return OperationResult(
                success=True,
                message=f"已重新排序工作流: {' → '.join(new_order)}",
                workflow_changed=True,
            )

        except Exception as e:
            logger.error(f"重新排序失败: {e}, traceback: {traceback.format_exc()}")
            return OperationResult(success=False, message=str(e))

    # ========== 生成操作 ==========

    async def regenerate_plan(
        self,
        feedback: Optional[str] = None,
        constraints: Optional[Dict[str, Any]] = None,
    ) -> OperationResult:
        """
        根据反馈重新生成规划

        Args:
            feedback: 用户反馈
            constraints: 约束条件

        Returns:
            操作结果
        """
        if not self._ensure_builder():
            return OperationResult(success=False, message="请先创建工作流")

        try:
            task_desc = self._task_description
            if feedback:
                task_desc = f"{task_desc}\n\n用户反馈: {feedback}"

            plan = await self._builder._generate_plan(task_desc)

            if plan:
                self._builder.current_plan = plan

                # 通知状态机：规划完全替换
                self._builder.fsm.on_plan_created()

                self._builder.iteration_manager.checkpoint(
                    label="regenerate_plan",
                    stage=self._builder.current_stage,
                    state=self._builder._get_current_state(),
                )

                return OperationResult(
                    success=True,
                    message=f"已重新生成规划，包含 {len(plan.agent_specs)} 个 Agent",
                    data={"plan": plan.to_dict()},
                    workflow_changed=True,
                )
            else:
                return OperationResult(success=False, message="重新生成失败")

        except Exception as e:
            logger.error(f"重新生成规划失败: {e}, traceback: {traceback.format_exc()}")
            return OperationResult(success=False, message=str(e))

    async def generate_agents_from_plan(
        self, progress_callback: Optional[Callable] = None
    ) -> OperationResult:
        """
        从规划生成实际的 Agent 定义

        Args:
            progress_callback: 进度回调函数，接收进度事件字典（可选，如未提供则使用内置回调）

        Returns:
            操作结果，包含生成结果摘要
        """
        if not self._ensure_builder() or not self._builder.current_plan:
            return OperationResult(success=False, message="当前没有工作流规划")

        # 使用提供的回调或内置回调
        callback = progress_callback or self._progress_callback

        try:
            from .interactive_builder import InteractionStage

            self._builder.current_stage = InteractionStage.AGENT
            generated = []
            failed = []
            total = len(self._builder.current_plan.agent_specs)

            for i, spec in enumerate(self._builder.current_plan.agent_specs):
                # 获取用户友好的显示名称
                display_name = spec.display_name or spec.name

                # 发送生成进度事件
                if callback:
                    try:
                        await callback(
                            {
                                "type": "agent_generation_progress",
                                "current": i + 1,
                                "total": total,
                                "agent_name": spec.name,
                                "display_name": display_name,
                                "status": "generating",
                                "message": f"正在生成 {display_name}...",
                            }
                        )
                        # 让出事件循环，确保 WebSocket 消息能够立即发送
                        await asyncio.sleep(0)
                    except Exception as cb_error:
                        logger.warning(f"进度回调执行失败: {cb_error}")

                full_description = f"Agent名称: {spec.name}\n显示名称: {display_name}\n任务: {spec.task}"
                if spec.dependencies:
                    full_description += f"\n依赖: {', '.join(spec.dependencies)}"

                try:
                    agent = await self.meta_agent.create_agent(
                        task_description=full_description,
                        tools=spec.suggested_tools or None,
                    )

                    if agent:
                        # 确保 display_name 被正确设置
                        if not agent.display_name:
                            agent.display_name = display_name
                        self._builder.draft_agents.append(agent)
                        generated.append(
                            {
                                "name": agent.name,
                                "display_name": agent.display_name,
                                "description": agent.description,
                                "domain_type": (
                                    agent.domain_type.value
                                    if agent.domain_type
                                    else "general"
                                ),
                                "tools_count": (
                                    len(agent.tool_references)
                                    if agent.tool_references
                                    else 0
                                ),
                                "tools": [
                                    t.alias or t.tool_id
                                    for t in (agent.tool_references or [])
                                ],
                                "status": "success",
                            }
                        )

                        # 发送完成事件
                        if callback:
                            try:
                                await callback(
                                    {
                                        "type": "agent_generation_progress",
                                        "current": i + 1,
                                        "total": total,
                                        "agent_name": agent.name,
                                        "display_name": agent.display_name,
                                        "status": "completed",
                                        "message": f"{agent.display_name} 生成完成",
                                    }
                                )
                                # 让出事件循环，确保 WebSocket 消息能够立即发送
                                await asyncio.sleep(0)
                            except Exception as cb_error:
                                logger.warning(f"进度回调执行失败: {cb_error}")
                    else:
                        failed.append(
                            {
                                "name": spec.name,
                                "display_name": display_name,
                                "reason": "生成返回空结果",
                            }
                        )
                except Exception as agent_error:
                    logger.error(f"生成 Agent {spec.name} 失败: {agent_error}")
                    failed.append(
                        {
                            "name": spec.name,
                            "display_name": display_name,
                            "reason": str(agent_error),
                        }
                    )

            # 通知状态机：Agents 全量生成完成
            self._builder.fsm.on_agents_generated()

            self._builder.iteration_manager.checkpoint(
                label="generate_agents",
                stage=self._builder.current_stage,
                state=self._builder._get_current_state(),
            )

            # 保存失败的 Agent 列表（用于支持重新生成）
            self._failed_agents = failed

            # 构建详细摘要
            summary = {
                "total_agents": len(generated),
                "failed_count": len(failed),
                "agents": generated,
                "failed_agents": failed if failed else None,
                "next_step": "您可以确认这些 Agent，或点击画布中的节点查看详情并进行修改",
            }

            success_names = [a["display_name"] for a in generated]
            message = f"已生成 {len(generated)} 个 Agent"
            if failed:
                message += f"（{len(failed)} 个失败）"

            return OperationResult(
                success=len(generated) > 0,
                message=message,
                data={"summary": summary},
                workflow_changed=True,
            )

        except Exception as e:
            logger.error(f"生成 Agent 失败: {e}, traceback: {traceback.format_exc()}")
            return OperationResult(success=False, message=str(e))

    async def regenerate_agent(
        self,
        agent_name: str,
        feedback: Optional[str] = None,
        progress_callback: Optional[Callable] = None,
    ) -> OperationResult:
        """
        重新生成指定的 Agent

        用于生成失败或用户不满意时重新生成单个 Agent。

        Args:
            agent_name: Agent 名称（支持 name 或 display_name，也支持 'failed' 表示所有失败的）
            feedback: 用户反馈，用于改进生成（可选）
            progress_callback: 进度回调函数（可选）

        Returns:
            操作结果
        """
        if not self._ensure_builder() or not self._builder.current_plan:
            return OperationResult(success=False, message="当前没有工作流规划")

        callback = progress_callback or self._progress_callback

        try:
            # 特殊处理：重新生成所有失败的 Agent
            if agent_name.lower() in [
                "failed",
                "失败的",
                "失败的agent",
                "失败的 agent",
                "all_failed",
            ]:
                return await self._regenerate_failed_agents(feedback, callback)

            # 查找对应的 AgentSpec
            target_spec = None
            for spec in self._builder.current_plan.agent_specs:
                if spec.name.lower() == agent_name.lower() or (
                    spec.display_name
                    and spec.display_name.lower() == agent_name.lower()
                ):
                    target_spec = spec
                    break

            if not target_spec:
                # 尝试模糊匹配
                for spec in self._builder.current_plan.agent_specs:
                    if agent_name.lower() in spec.name.lower() or (
                        spec.display_name
                        and agent_name.lower() in spec.display_name.lower()
                    ):
                        target_spec = spec
                        break

            if not target_spec:
                return OperationResult(
                    success=False,
                    message=f"未找到 Agent: {agent_name}。可用的 Agent: {[s.display_name or s.name for s in self._builder.current_plan.agent_specs]}",
                )

            display_name = target_spec.display_name or target_spec.name

            # 发送进度事件
            if callback:
                try:
                    await callback(
                        {
                            "type": "agent_generation_progress",
                            "current": 1,
                            "total": 1,
                            "agent_name": target_spec.name,
                            "display_name": display_name,
                            "status": "regenerating",
                            "message": f"正在重新生成 {display_name}...",
                        }
                    )
                except Exception as cb_error:
                    logger.warning(f"进度回调执行失败: {cb_error}")

            # 移除旧的 Agent（如果存在）
            self._builder.draft_agents = [
                a
                for a in self._builder.draft_agents
                if a.name.lower() != target_spec.name.lower()
                and (
                    not a.display_name or a.display_name.lower() != display_name.lower()
                )
            ]

            # 从失败列表中移除（如果存在）
            self._failed_agents = [
                f
                for f in self._failed_agents
                if f.get("name", "").lower() != target_spec.name.lower()
                and f.get("display_name", "").lower() != display_name.lower()
            ]

            # 构建增强的任务描述
            full_description = f"Agent名称: {target_spec.name}\n显示名称: {display_name}\n任务: {target_spec.task}"
            if target_spec.dependencies:
                full_description += f"\n依赖: {', '.join(target_spec.dependencies)}"
            if feedback:
                full_description += f"\n\n用户反馈: {feedback}"

            # 重新生成
            agent = await self.meta_agent.create_agent(
                task_description=full_description,
                tools=target_spec.suggested_tools or None,
            )

            if agent:
                if not agent.display_name:
                    agent.display_name = display_name
                self._builder.draft_agents.append(agent)

                # 发送完成事件
                if callback:
                    try:
                        await callback(
                            {
                                "type": "agent_generation_progress",
                                "current": 1,
                                "total": 1,
                                "agent_name": agent.name,
                                "display_name": agent.display_name,
                                "status": "completed",
                                "message": f"{agent.display_name} 重新生成完成",
                            }
                        )
                    except Exception as cb_error:
                        logger.warning(f"进度回调执行失败: {cb_error}")

                # 通知状态机：Agent 被重新生成
                self._builder.fsm.on_agent_regenerated(target_spec.name)

                # 创建检查点
                self._builder.iteration_manager.checkpoint(
                    label="regenerate_agent",
                    stage=self._builder.current_stage,
                    state=self._builder._get_current_state(),
                )

                return OperationResult(
                    success=True,
                    message=f"已重新生成 Agent: {agent.display_name}",
                    data={
                        "agent": {
                            "name": agent.name,
                            "display_name": agent.display_name,
                            "description": agent.description,
                        }
                    },
                    workflow_changed=True,
                )
            else:
                # 记录失败
                self._failed_agents.append(
                    {
                        "name": target_spec.name,
                        "display_name": display_name,
                        "reason": "重新生成返回空结果",
                    }
                )
                return OperationResult(
                    success=False,
                    message=f"重新生成 Agent {display_name} 失败：返回空结果",
                )

        except Exception as e:
            logger.error(
                f"重新生成 Agent 失败: {e}, traceback: {traceback.format_exc()}"
            )
            return OperationResult(success=False, message=f"重新生成失败: {str(e)}")

    async def _regenerate_failed_agents(
        self,
        feedback: Optional[str] = None,
        progress_callback: Optional[Callable] = None,
    ) -> OperationResult:
        """
        重新生成所有失败的 Agent

        Args:
            feedback: 用户反馈
            progress_callback: 进度回调

        Returns:
            操作结果
        """
        if not self._failed_agents:
            return OperationResult(success=True, message="没有需要重新生成的失败 Agent")

        regenerated = []
        still_failed = []
        total = len(self._failed_agents)

        for i, failed_info in enumerate(self._failed_agents.copy()):
            agent_name = failed_info.get("name", "")
            display_name = failed_info.get("display_name", agent_name)

            # 发送进度
            if progress_callback:
                try:
                    await progress_callback(
                        {
                            "type": "agent_generation_progress",
                            "current": i + 1,
                            "total": total,
                            "agent_name": agent_name,
                            "display_name": display_name,
                            "status": "regenerating",
                            "message": f"正在重新生成 {display_name}... ({i+1}/{total})",
                        }
                    )
                except Exception as cb_error:
                    logger.warning(f"进度回调执行失败: {cb_error}")

            result = await self.regenerate_agent(agent_name, feedback, None)

            if result.success:
                regenerated.append(display_name)
            else:
                still_failed.append(
                    {
                        "name": agent_name,
                        "display_name": display_name,
                        "reason": result.message,
                    }
                )

        # 更新失败列表
        self._failed_agents = still_failed

        if regenerated:
            message = (
                f"已重新生成 {len(regenerated)} 个 Agent: {', '.join(regenerated)}"
            )
            if still_failed:
                message += f"（{len(still_failed)} 个仍然失败）"
            return OperationResult(
                success=True,
                message=message,
                data={"regenerated": regenerated, "still_failed": still_failed},
                workflow_changed=True,
            )
        else:
            return OperationResult(
                success=False,
                message=f"重新生成失败，{len(still_failed)} 个 Agent 仍然无法生成",
            )

    async def merge_plans(
        self,
        source: str = "previous",
        merge_strategy: str = "union",
        agents_to_include: Optional[List[str]] = None,
    ) -> OperationResult:
        """
        合并或整合两个规划

        用于用户说"整合两个规划"、"融合"、"合并"等场景。

        Args:
            source: 源规划来源，'previous'（最近一个有不同规划的检查点）或具体的检查点ID
            merge_strategy: 合并策略
                - 'union': 取并集，去重（同名 Agent 保留当前规划的）
                - 'append': 追加所有（源规划的 Agent 添加到当前规划末尾）
                - 'selective': 仅包含 agents_to_include 指定的 Agent
            agents_to_include: 要从源规划中包含的 Agent 名称列表（可选）

        Returns:
            操作结果
        """
        if not self._ensure_builder() or not self._builder.current_plan:
            return OperationResult(success=False, message="当前没有规划可合并")

        try:
            # 1. 获取源规划
            source_plan = None
            source_checkpoint_label = None

            checkpoints = self._builder.iteration_manager.get_checkpoints()

            if source == "previous":
                # 找到最近一个有不同规划的检查点
                current_agent_names = {
                    spec.name for spec in self._builder.current_plan.agent_specs
                }

                for ckpt in reversed(checkpoints[:-1]):  # 排除最新的检查点
                    state = (
                        ckpt.state if hasattr(ckpt, "state") else ckpt.get("state", {})
                    )
                    ckpt_plan = state.get("plan", {})
                    if ckpt_plan:
                        ckpt_agents = ckpt_plan.get("agents", [])
                        ckpt_agent_names = {a.get("name", "") for a in ckpt_agents}
                        # 检查是否有不同的 Agent（说明是不同的规划）
                        if ckpt_agent_names != current_agent_names and ckpt_agents:
                            source_plan = ckpt_plan
                            source_checkpoint_label = (
                                ckpt.label
                                if hasattr(ckpt, "label")
                                else ckpt.get("label", "")
                            )
                            break
            else:
                # 根据检查点ID查找
                for ckpt in checkpoints:
                    ckpt_id = (
                        ckpt.checkpoint_id
                        if hasattr(ckpt, "checkpoint_id")
                        else ckpt.get("checkpoint_id", "")
                    )
                    if ckpt_id and (ckpt_id == source or ckpt_id.startswith(source)):
                        state = (
                            ckpt.state
                            if hasattr(ckpt, "state")
                            else ckpt.get("state", {})
                        )
                        source_plan = state.get("plan", {})
                        source_checkpoint_label = (
                            ckpt.label
                            if hasattr(ckpt, "label")
                            else ckpt.get("label", "")
                        )
                        break

            if not source_plan or not source_plan.get("agents"):
                return OperationResult(
                    success=False,
                    message="未找到可合并的源规划。请确保之前有创建过其他规划（可在检查点历史中查看）。",
                )

            # 2. 提取源规划的 Agent 列表
            source_agents = source_plan.get("agents", [])
            current_specs = self._builder.current_plan.agent_specs
            current_agent_names = {spec.name.lower() for spec in current_specs}
            current_display_names = {
                (spec.display_name or spec.name).lower() for spec in current_specs
            }

            # 3. 根据策略合并
            agents_to_add = []

            if merge_strategy == "selective" and agents_to_include:
                # 仅包含指定的 Agent
                include_lower = {name.lower() for name in agents_to_include}
                for agent in source_agents:
                    name = agent.get("name", "")
                    display_name = agent.get("display_name", name)
                    if (
                        name.lower() in include_lower
                        or display_name.lower() in include_lower
                    ):
                        agents_to_add.append(agent)
            elif merge_strategy == "union":
                # 取并集，去重
                for agent in source_agents:
                    name = agent.get("name", "")
                    display_name = agent.get("display_name", name)
                    if (
                        name.lower() not in current_agent_names
                        and display_name.lower() not in current_display_names
                    ):
                        agents_to_add.append(agent)
            else:  # append
                # 追加所有，但重命名同名的
                for agent in source_agents:
                    name = agent.get("name", "")
                    if name.lower() in current_agent_names:
                        # 重命名
                        agent = agent.copy()
                        agent["name"] = f"{name}_merged"
                        if agent.get("display_name"):
                            agent["display_name"] = f"{agent['display_name']}（合并）"
                    agents_to_add.append(agent)

            if not agents_to_add:
                return OperationResult(
                    success=True,
                    message=f"源规划（{source_checkpoint_label}）中没有需要添加的 Agent（可能都已存在于当前规划中）。",
                )

            # 4. 添加 Agent 到当前规划
            from .interactive_builder import AgentSpec

            added_names = []
            for agent_dict in agents_to_add:
                # 创建 AgentSpec
                new_spec = AgentSpec(
                    name=agent_dict.get("name", ""),
                    display_name=agent_dict.get("display_name"),
                    task=agent_dict.get("task", ""),
                    dependencies=agent_dict.get("dependencies", []),
                    suggested_tools=agent_dict.get("tools", []),
                )
                self._builder.current_plan.agent_specs.append(new_spec)
                added_names.append(new_spec.display_name or new_spec.name)

            # 5. 更新工作流结构描述
            self._builder.current_plan.workflow_structure = (
                f"{self._builder.current_plan.workflow_structure or ''}\n"
                f"（已合并来自 {source_checkpoint_label} 的 {len(added_names)} 个 Agent）"
            ).strip()

            # 通知状态机：规划被修改（合并新增 specs）
            merged_spec_names = [
                a.get("name", "") for a in agents_to_add if a.get("name")
            ]
            self._builder.fsm.on_plan_modified(added_specs=merged_spec_names)

            # 6. 创建检查点
            self._builder.iteration_manager.checkpoint(
                label=f"merge_plans_{source_checkpoint_label}",
                stage=self._builder.current_stage,
                state=self._builder._get_current_state(),
            )

            return OperationResult(
                success=True,
                message=f"已成功合并规划！从 {source_checkpoint_label} 添加了 {len(added_names)} 个 Agent: {', '.join(added_names)}",
                data={
                    "source_checkpoint": source_checkpoint_label,
                    "added_agents": added_names,
                    "merge_strategy": merge_strategy,
                    "total_agents": len(self._builder.current_plan.agent_specs),
                },
                workflow_changed=True,
            )

        except Exception as e:
            logger.error(f"合并规划失败: {e}, traceback: {traceback.format_exc()}")
            return OperationResult(success=False, message=f"合并规划失败: {str(e)}")

    async def iterate_plan(
        self,
        user_request: str,
        include_history: bool = True,
    ) -> OperationResult:
        """
        智能迭代规划 - LLM 驱动的规划更新

        根据用户的自然语言请求，结合历史规划和当前规划上下文，
        让 LLM 深度理解用户意图，生成新的完整规划。

        适用场景：
        - "把上一版规划的 XXX Agent 加入当前规划"
        - "整合两次规划，取各自的优点"
        - "修改当前规划，增加数据验证环节"
        - "根据我的反馈重新设计规划"

        Args:
            user_request: 用户的自然语言请求/反馈
            include_history: 是否包含历史规划（默认True）

        Returns:
            操作结果，包含新生成的规划
        """
        if not self._ensure_builder():
            return OperationResult(success=False, message="请先创建工作流")

        try:
            # 1. 提取历史规划（从检查点）
            previous_plans = self._extract_previous_plans() if include_history else None

            # 2. 构建迭代上下文
            iteration_context = self._build_iteration_context(
                user_request, previous_plans
            )

            logger.info(
                f"智能迭代规划: user_request={user_request[:100]}..., history_plans={len(previous_plans) if previous_plans else 0}"
            )

            # 3. 调用增强的 _generate_plan
            plan = await self._builder._generate_plan(
                task_description=self._task_description,
                previous_plans=previous_plans,
                user_feedback=user_request,
                iteration_context=iteration_context,
            )

            if plan:
                # 4. 更新状态
                self._builder.current_plan = plan

                # 通知状态机：规划完全替换
                self._builder.fsm.on_plan_created()

                # 5. 创建检查点
                self._builder.iteration_manager.checkpoint(
                    label="iterate_plan",
                    stage=self._builder.current_stage,
                    state=self._builder._get_current_state(),
                )

                # 6. 构建结果摘要
                agent_names = [
                    spec.display_name or spec.name for spec in plan.agent_specs
                ]

                return OperationResult(
                    success=True,
                    message=f"已根据您的要求重新生成规划！新规划包含 {len(plan.agent_specs)} 个 Agent: {', '.join(agent_names)}",
                    data={
                        "plan": plan.to_dict(),
                        "agent_count": len(plan.agent_specs),
                        "agents": agent_names,
                    },
                    workflow_changed=True,
                )
            else:
                return OperationResult(success=False, message="规划生成失败，请重试")

        except Exception as e:
            logger.error(f"智能迭代规划失败: {e}, traceback: {traceback.format_exc()}")
            return OperationResult(success=False, message=f"规划迭代失败: {str(e)}")

    def _extract_previous_plans(self, limit: int = 5) -> List[Dict[str, Any]]:
        """
        从检查点提取历史规划

        Args:
            limit: 最多提取的历史规划数量

        Returns:
            历史规划列表（已去重）
        """
        if not self._builder:
            return []

        plans = []
        checkpoints = self._builder.iteration_manager.get_checkpoints()

        seen_plans = set()  # 用于去重
        for ckpt in reversed(checkpoints):
            state = ckpt.state if hasattr(ckpt, "state") else ckpt.get("state", {})
            plan = state.get("plan", {})
            if plan and plan.get("agents"):
                # 简化表示，用于 LLM 理解
                plan_summary = {
                    "checkpoint_label": (
                        ckpt.label if hasattr(ckpt, "label") else ckpt.get("label", "")
                    ),
                    "timestamp": (
                        ckpt.timestamp
                        if hasattr(ckpt, "timestamp")
                        else ckpt.get("timestamp", "")
                    ),
                    "task_description": plan.get("task_description", ""),
                    "agents": [
                        {
                            "name": a.get("name"),
                            "display_name": a.get("display_name"),
                            "task": a.get("task"),
                            "dependencies": a.get("dependencies", []),
                            "suggested_tools": a.get(
                                "suggested_tools", a.get("tools", [])
                            ),
                        }
                        for a in plan.get("agents", [])
                    ],
                }
                # 用 agent 名称列表作为去重 key
                plan_key = str(sorted([a["name"] for a in plan_summary["agents"]]))
                if plan_key not in seen_plans:
                    seen_plans.add(plan_key)
                    plans.append(plan_summary)
                    if len(plans) >= limit:
                        break

        return plans

    def _build_iteration_context(
        self, user_request: str, previous_plans: Optional[List[Dict[str, Any]]]
    ) -> str:
        """
        构建迭代上下文描述

        Args:
            user_request: 用户请求
            previous_plans: 历史规划列表

        Returns:
            迭代上下文描述字符串
        """
        if not previous_plans:
            return "这是首次规划迭代，无历史规划可参考"

        context_parts = [f"用户请求: {user_request}"]
        context_parts.append(f"可参考的历史规划数量: {len(previous_plans)}")

        # 分析用户意图，提供更明确的指导
        user_request_lower = user_request.lower()
        if any(kw in user_request for kw in ["整合", "合并", "融合", "加入", "添加到"]):
            context_parts.append(
                "用户意图分析: 希望整合历史规划中的部分 Agent 到新规划"
            )
            context_parts.append(
                "建议: 分析历史规划中用户提到的 Agent，将其整合到新规划中，并建立合适的依赖关系"
            )
        elif any(kw in user_request for kw in ["修改", "调整", "更新", "改进"]):
            context_parts.append("用户意图分析: 希望修改当前规划的部分内容")
            context_parts.append("建议: 基于当前规划进行局部修改，保持整体结构不变")
        elif any(kw in user_request for kw in ["添加", "增加", "新增", "加个"]):
            context_parts.append("用户意图分析: 希望在当前规划基础上添加新 Agent")
            context_parts.append(
                "建议: 保留当前规划的所有 Agent，添加用户要求的新 Agent"
            )
        elif any(kw in user_request for kw in ["删除", "移除", "去掉", "不要"]):
            context_parts.append("用户意图分析: 希望从当前规划中删除某些 Agent")
            context_parts.append("建议: 移除用户指定的 Agent，并修复依赖关系")
        elif any(kw in user_request for kw in ["上一版", "之前", "刚才", "前面"]):
            context_parts.append("用户意图分析: 用户提到了历史规划中的内容")
            context_parts.append(
                "建议: 从历史规划中找到用户提到的 Agent，整合到新规划中"
            )
        else:
            context_parts.append("用户意图分析: 一般性的规划修改请求")
            context_parts.append("建议: 仔细理解用户需求，生成符合要求的完整规划")

        return "\n".join(context_parts)

    async def assemble_workflow(self) -> OperationResult:
        """
        组装工作流

        当重新组装已加载的工作流时，会保留原有的 workflow_id、name、description 等标识，
        确保后续保存时能正确更新原有工作流，而不是创建新的工作流。

        Returns:
            操作结果
        """
        if not self._ensure_builder() or not self._builder.draft_agents:
            return OperationResult(success=False, message="没有可用的 Agent")

        try:
            from .interactive_builder import InteractionStage

            self._builder.current_stage = InteractionStage.WORKFLOW

            # ========== 保存现有工作流的标识（用于重新组装场景）==========
            existing_workflow_id = None
            existing_workflow_name = None
            existing_workflow_description = None
            existing_workflow_version = None
            is_reassembly = False

            if self._builder.draft_workflow:
                existing_workflow_id = self._builder.draft_workflow.workflow_id
                existing_workflow_name = self._builder.draft_workflow.name
                existing_workflow_description = self._builder.draft_workflow.description
                existing_workflow_version = self._builder.draft_workflow.version
                is_reassembly = True
                logger.info(
                    f"重新组装已有工作流: {existing_workflow_name} ({existing_workflow_id})"
                )

            # 确保所有草稿 Agent 都注册到 AgentRegistry
            for agent in self._builder.draft_agents:
                if not self.meta_agent.agent_registry.get_definition(agent.agent_id):
                    self.meta_agent.agent_registry.register_definition(agent)
                    logger.debug(f"注册草稿 Agent: {agent.agent_id}")

            workflow = await self.meta_agent.generate_workflow(
                task_description=self._task_description,
                available_agents=[a.agent_id for a in self._builder.draft_agents],
            )

            if workflow:
                # ========== 如果是重新组装，恢复原有的工作流标识 ==========
                if is_reassembly and existing_workflow_id:
                    workflow.workflow_id = existing_workflow_id
                    workflow.name = existing_workflow_name
                    workflow.description = existing_workflow_description
                    # 版本号递增（表示工作流结构有变化）
                    if existing_workflow_version:
                        try:
                            parts = existing_workflow_version.split(".")
                            parts[-1] = str(int(parts[-1]) + 1)
                            workflow.version = ".".join(parts)
                        except (ValueError, IndexError):
                            workflow.version = "1.0.1"
                    logger.info(
                        f"已恢复工作流标识: {workflow.name} ({workflow.workflow_id}), "
                        f"版本: {existing_workflow_version} → {workflow.version}"
                    )

                self._builder.draft_workflow = workflow

                # 通知状态机：工作流组装完成
                self._builder.fsm.on_workflow_assembled()

                self._builder.iteration_manager.checkpoint(
                    label="assemble_workflow",
                    stage=self._builder.current_stage,
                    state=self._builder._get_current_state(),
                )

                action = "重新组装" if is_reassembly else "组装"
                return OperationResult(
                    success=True,
                    message=f"已{action}工作流，包含 {len(workflow.nodes)} 个节点",
                    data={"workflow_id": workflow.workflow_id},
                    workflow_changed=True,
                )
            else:
                return OperationResult(success=False, message="组装工作流失败")

        except Exception as e:
            logger.error(f"组装工作流失败: {e}, traceback: {traceback.format_exc()}")
            return OperationResult(success=False, message=str(e))

    # ========== 状态操作 ==========

    async def approve_current_state(self) -> OperationResult:
        """
        批准当前状态，进入下一阶段。

        由 BuilderStateMachine.resolve_approve() 决定实际执行什么操作，
        而非硬编码基于 InteractionStage 的 if-elif 分支。

        Returns:
            操作结果
        """
        if not self._ensure_builder():
            return OperationResult(success=False, message="没有可批准的内容")

        from .interactive_builder import ApproveAction

        try:
            action = self._builder.fsm.resolve_approve()
            logger.info(f"approve_current_state: FSM resolved action = {action.value}")

            if action == ApproveAction.GENERATE_ALL_AGENTS:
                # 发送批准消息
                if self._progress_callback:
                    try:
                        await self._progress_callback(
                            {
                                "type": "approval_started",
                                "stage": "plan",
                                "message": "规划已批准，正在生成 Agents...",
                            }
                        )
                        await asyncio.sleep(0)
                    except Exception as cb_error:
                        logger.warning(f"批准消息回调执行失败: {cb_error}")

                result = await self.generate_agents_from_plan()
                if result.success:
                    return OperationResult(
                        success=True,
                        message=result.message,
                        data=result.data,
                        workflow_changed=True,
                    )
                return result

            elif action == ApproveAction.GENERATE_NEW_AGENTS:
                # 增量生成新增的 Agents
                if self._progress_callback:
                    try:
                        await self._progress_callback(
                            {
                                "type": "approval_started",
                                "stage": "agent",
                                "message": "正在生成新增的 Agents...",
                            }
                        )
                        await asyncio.sleep(0)
                    except Exception as cb_error:
                        logger.warning(f"批准消息回调执行失败: {cb_error}")

                result = await self._generate_incremental_agents()
                if result.success:
                    return OperationResult(
                        success=True,
                        message=result.message,
                        data=result.data,
                        workflow_changed=True,
                    )
                return result

            elif action == ApproveAction.REGENERATE_ALL_AGENTS:
                # 规划大幅变动，全量重新生成
                if self._progress_callback:
                    try:
                        await self._progress_callback(
                            {
                                "type": "approval_started",
                                "stage": "plan",
                                "message": "规划已变更，正在重新生成所有 Agents...",
                            }
                        )
                        await asyncio.sleep(0)
                    except Exception as cb_error:
                        logger.warning(f"批准消息回调执行失败: {cb_error}")

                # 清空现有 agents 再全量生成
                self._builder.draft_agents.clear()
                result = await self.generate_agents_from_plan()
                if result.success:
                    return OperationResult(
                        success=True,
                        message=result.message,
                        data=result.data,
                        workflow_changed=True,
                    )
                return result

            elif action == ApproveAction.ASSEMBLE_WORKFLOW:
                # Agents 就绪，组装/重新组装工作流
                if self._progress_callback:
                    try:
                        await self._progress_callback(
                            {
                                "type": "approval_started",
                                "stage": "agent",
                                "message": "Agents 已批准，正在组装工作流...",
                            }
                        )
                        await asyncio.sleep(0)
                    except Exception as cb_error:
                        logger.warning(f"批准消息回调执行失败: {cb_error}")

                result = await self.assemble_workflow()
                if result.success:
                    return OperationResult(
                        success=True,
                        message=result.message,
                        data=result.data,
                        workflow_changed=True,
                    )
                return result

            elif action == ApproveAction.CONFIRM_READY:
                # 一切就绪
                self._builder.iteration_manager.checkpoint(
                    label="workflow_approved",
                    stage=self._builder.current_stage,
                    state=self._builder._get_current_state(),
                )

                return OperationResult(
                    success=True,
                    message="工作流已确认！您可以说'执行'来运行它，或说'保存'来保存它。",
                    workflow_changed=False,
                )

            else:  # ApproveAction.NOTHING_TO_DO
                return OperationResult(success=True, message="当前没有需要确认的内容。")

        except Exception as e:
            logger.error(f"批准状态失败: {e}, traceback: {traceback.format_exc()}")
            return OperationResult(success=False, message=str(e))

    async def _generate_incremental_agents(
        self, progress_callback: Optional[Callable] = None
    ) -> OperationResult:
        """
        增量生成 Agents —— 仅为 FSM 中标记的新增 specs 生成，不重复生成已有的。

        Returns:
            操作结果
        """
        if not self._ensure_builder() or not self._builder.current_plan:
            return OperationResult(success=False, message="当前没有工作流规划")

        callback = progress_callback or self._progress_callback
        new_spec_names = set(self._builder.fsm.new_specs_since_generation)

        if not new_spec_names:
            return OperationResult(
                success=True,
                message="没有需要增量生成的 Agent",
                workflow_changed=False,
            )

        try:
            from .interactive_builder import InteractionStage

            specs_to_generate = [
                spec
                for spec in self._builder.current_plan.agent_specs
                if spec.name in new_spec_names
            ]

            if not specs_to_generate:
                return OperationResult(
                    success=True,
                    message="没有找到需要生成的 Agent 规格",
                    workflow_changed=False,
                )

            generated = []
            failed = []
            total = len(specs_to_generate)

            for i, spec in enumerate(specs_to_generate):
                display_name = spec.display_name or spec.name

                if callback:
                    try:
                        await callback(
                            {
                                "type": "agent_generation_progress",
                                "current": i + 1,
                                "total": total,
                                "agent_name": spec.name,
                                "display_name": display_name,
                                "status": "generating",
                                "message": f"正在生成 {display_name}...",
                            }
                        )
                        await asyncio.sleep(0)
                    except Exception as cb_error:
                        logger.warning(f"进度回调执行失败: {cb_error}")

                full_description = f"Agent名称: {spec.name}\n显示名称: {display_name}\n任务: {spec.task}"
                if spec.dependencies:
                    full_description += f"\n依赖: {', '.join(spec.dependencies)}"

                try:
                    agent = await self.meta_agent.create_agent(
                        task_description=full_description,
                        tools=spec.suggested_tools or None,
                    )

                    if agent:
                        if not agent.display_name:
                            agent.display_name = display_name
                        self._builder.draft_agents.append(agent)
                        generated.append(spec.name)

                        if callback:
                            try:
                                await callback(
                                    {
                                        "type": "agent_generation_progress",
                                        "current": i + 1,
                                        "total": total,
                                        "agent_name": agent.name,
                                        "display_name": agent.display_name,
                                        "status": "completed",
                                        "message": f"{agent.display_name} 生成完成",
                                    }
                                )
                                await asyncio.sleep(0)
                            except Exception as cb_error:
                                logger.warning(f"进度回调执行失败: {cb_error}")
                    else:
                        failed.append(spec.name)

                except Exception as agent_error:
                    logger.error(f"增量生成 Agent {spec.name} 失败: {agent_error}")
                    failed.append(spec.name)

            # 通知状态机：增量生成完成
            if generated:
                self._builder.fsm.on_incremental_agents_generated(generated)

            self._builder.iteration_manager.checkpoint(
                label="incremental_generate_agents",
                stage=self._builder.current_stage,
                state=self._builder._get_current_state(),
            )

            message = f"已增量生成 {len(generated)} 个 Agent"
            if failed:
                message += f"（{len(failed)} 个失败）"

            return OperationResult(
                success=len(generated) > 0,
                message=message,
                data={
                    "generated": generated,
                    "failed": failed,
                },
                workflow_changed=True,
            )

        except Exception as e:
            logger.error(
                f"增量生成 Agent 失败: {e}, traceback: {traceback.format_exc()}"
            )
            return OperationResult(success=False, message=str(e))

    async def rollback_to_checkpoint(
        self,
        checkpoint_id: Optional[str] = None,
    ) -> OperationResult:
        """
        回滚到检查点

        Args:
            checkpoint_id: 检查点 ID，为空则回滚到上一个

        Returns:
            操作结果
        """
        if not self._ensure_builder():
            return OperationResult(success=False, message="没有可回滚的内容")

        try:
            checkpoints = self._builder.iteration_manager.get_checkpoints()

            if not checkpoints:
                return OperationResult(success=False, message="没有可用的检查点")

            if checkpoint_id:
                state = self._builder.iteration_manager.rollback(checkpoint_id)
            else:
                # 回滚到倒数第二个（当前状态是最后一个）
                if len(checkpoints) < 2:
                    return OperationResult(success=False, message="没有可回滚的检查点")
                state = self._builder.iteration_manager.rollback(
                    checkpoints[-2].checkpoint_id
                )

            self._builder._restore_state(state)

            return OperationResult(
                success=True,
                message=f"已回滚到检查点: {checkpoint_id or checkpoints[-2].label}",
                workflow_changed=True,
            )

        except Exception as e:
            logger.error(f"回滚失败: {e}, traceback: {traceback.format_exc()}")
            return OperationResult(success=False, message=str(e))

    async def save_workflow(
        self,
        path: Optional[str] = None,
        name: Optional[str] = None,
        description: Optional[str] = None,
        tags: Optional[List[str]] = None,
        author: str = "user",
        save_to_database: bool = True,
    ) -> OperationResult:
        """
        保存工作流（优先保存到数据库）

        Args:
            path: 保存路径（可选，用于本地文件备份）
            name: 工作流名称
            description: 工作流描述
            tags: 标签列表
            author: 作者
            save_to_database: 是否保存到数据库（默认 True）

        Returns:
            操作结果，包含工作流信息卡片数据
        """
        if not self._ensure_builder():
            return OperationResult(success=False, message="没有可保存的工作流")

        if not self._builder.draft_workflow:
            return OperationResult(success=False, message="没有可保存的工作流定义")

        # FSM 前置校验：确保工作流不是过期的
        fsm = self._builder.fsm
        if not fsm.can_save:
            if fsm.needs_agent_generation:
                return OperationResult(
                    success=False,
                    message="有新增或变更的 Agent 尚未生成，请先说'确认'来生成后再保存。",
                )
            if fsm.needs_workflow_assembly:
                return OperationResult(
                    success=False,
                    message="Agent 已变更，工作流需要重新组装后才能保存。请先说'确认'来重新组装。",
                )

        try:
            from pathlib import Path as FilePath
            import json
            import os

            workflow = self._builder.draft_workflow
            agents = self._builder.draft_agents

            # 设置工作流名称和描述
            if name:
                workflow.name = name
            if description:
                workflow.description = description

            # 如果没有提供名称，使用任务描述的前 50 个字符
            if not workflow.name:
                workflow.name = (self._task_description or "未命名工作流")[:50]

            result_data = {}
            db_saved = False
            saved_agents_count = 0
            failed_agents = []

            # ========== 优先保存到数据库 ==========
            if (
                save_to_database
                and os.getenv("ENABLE_POSTGRES", "false").lower() == "true"
            ):
                try:
                    from src.services import WorkflowService, AgentService
                    from src.storage.database import AsyncDatabaseManager
                    from src.storage.repositories import (
                        WorkflowDefinitionRepository,
                        WorkflowExecutionRepository,
                        AgentRepository,
                    )
                    from src.storage.config import PostgreSQLConfig

                    config = PostgreSQLConfig(
                        host=os.getenv("POSTGRES_HOST", "localhost"),
                        port=int(os.getenv("POSTGRES_PORT", "5432")),
                        database=os.getenv("POSTGRES_DB", "agent_framework"),
                        user=os.getenv("POSTGRES_USER", "postgres"),
                        password=os.getenv("POSTGRES_PASSWORD", ""),
                    )
                    db = AsyncDatabaseManager(config)
                    await db.connect()

                    # 初始化服务
                    workflow_repo = WorkflowDefinitionRepository(db._session_factory)
                    execution_repo = WorkflowExecutionRepository(db._session_factory)
                    agent_repo = AgentRepository(db._session_factory)
                    workflow_service = WorkflowService(workflow_repo, execution_repo)
                    agent_service = AgentService(agent_repo)

                    # 保存工作流到数据库
                    workflow_data = workflow.model_dump(mode="json")
                    if tags:
                        workflow_data["tags"] = tags

                    workflow_detail = await workflow_service.create_workflow_from_dict(
                        workflow_data=workflow_data,
                        author=author,
                    )

                    # 保存或更新所有 Agents 到数据库
                    updated_agents_count = 0
                    for agent_def in agents:
                        try:
                            agent_data = (
                                agent_def.model_dump(mode="json")
                                if hasattr(agent_def, "model_dump")
                                else agent_def.__dict__
                            )
                            agent_id = agent_data.get("agent_id")

                            # 检查 Agent 是否已存在
                            existing_agent = await agent_repo.get_by_agent_id(agent_id)
                            if existing_agent:
                                # 更新已存在的 Agent
                                await agent_service.update_agent(
                                    agent_id, {"definition": agent_data}
                                )
                                await agent_service.activate_agent(agent_id)
                                updated_agents_count += 1
                            else:
                                # 创建新 Agent
                                created_agent = await agent_service.create_agent_from_dict(
                                    agent_data=agent_data,
                                    author=author,
                                )
                                # 自动激活已保存的 Agent（从 draft 变为 active）
                                await agent_service.activate_agent(created_agent.agent_id)
                                saved_agents_count += 1
                        except Exception as agent_error:
                            agent_name = getattr(agent_def, "name", "unknown")
                            logger.error(
                                f"保存 Agent '{agent_name}' 失败: {agent_error}"
                            )
                            failed_agents.append(agent_name)

                    await db.close()

                    # 构建工作流信息卡片数据
                    result_data = self._build_workflow_info_card(
                        workflow_detail=workflow_detail,
                        workflow=workflow,
                        agents=agents,
                        saved_agents_count=saved_agents_count,
                    )
                    if failed_agents:
                        result_data["failed_agents"] = failed_agents
                    db_saved = True

                    logger.info(
                        f"工作流已保存到数据库: {workflow_detail.name} "
                        f"(ID: {workflow_detail.workflow_id}), "
                        f"Agents: 新建 {saved_agents_count}, 更新 {updated_agents_count} / 共 {len(agents)}"
                        + (f", 失败: {failed_agents}" if failed_agents else "")
                    )

                except Exception as db_error:
                    logger.error(f"保存到数据库失败: {db_error}")
                    import traceback

                    logger.debug(f"详细错误: {traceback.format_exc()}")

            # ========== 本地文件备份 ==========
            save_data = {
                "task_description": self._task_description,
                "plan": (
                    self._builder.current_plan.to_dict()
                    if self._builder.current_plan
                    else None
                ),
                "agents": [
                    a.model_dump() if hasattr(a, "model_dump") else a.__dict__
                    for a in agents
                ],
                "workflow": (
                    workflow.model_dump() if hasattr(workflow, "model_dump") else None
                ),
                "saved_at": datetime.now().isoformat(),
            }

            # 确定本地保存路径
            if not path:
                if self.storage_path:
                    save_dir = FilePath(self.storage_path)
                else:
                    save_dir = FilePath("./workspaces/saved_workflows")
                save_dir.mkdir(parents=True, exist_ok=True)
                path = str(
                    save_dir
                    / f"workflow_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
                )

            with open(path, "w", encoding="utf-8") as f:
                json.dump(save_data, f, ensure_ascii=False, indent=2)

            result_data["local_path"] = path

            # 构建返回消息
            if db_saved:
                message = (
                    f"工作流 '{result_data.get('name', workflow.name)}' 已保存到数据库"
                )
                if failed_agents:
                    message += (
                        f"（警告：{len(failed_agents)} 个 Agent 保存失败: "
                        f"{', '.join(failed_agents)}）"
                    )
                return OperationResult(
                    success=True,
                    message=message,
                    data=result_data,
                    workflow_changed=False,
                )
            else:
                # 数据库未启用，只保存到本地
                result_data.update(
                    {
                        "type": "workflow_info_card",
                        "name": workflow.name,
                        "description": workflow.description or "",
                        "agent_count": len(agents),
                        "node_count": len(workflow.nodes) if workflow.nodes else 0,
                        "saved_to": "local",
                    }
                )
                return OperationResult(
                    success=True,
                    message=f"工作流已保存到本地: {path}（数据库未启用）",
                    data=result_data,
                    workflow_changed=False,
                )

        except Exception as e:
            logger.error(f"保存工作流失败: {e}, traceback: {traceback.format_exc()}")
            return OperationResult(success=False, message=str(e))

    def _build_workflow_info_card(
        self,
        workflow_detail,
        workflow,
        agents: List,
        saved_agents_count: int,
    ) -> Dict[str, Any]:
        """
        构建工作流信息卡片数据

        Args:
            workflow_detail: 数据库返回的工作流详情
            workflow: 工作流定义
            agents: Agent 列表
            saved_agents_count: 成功保存的 Agent 数量

        Returns:
            工作流信息卡片数据字典
        """
        return {
            "type": "workflow_info_card",
            "id": workflow_detail.id,
            "workflow_id": workflow_detail.workflow_id,
            "name": workflow_detail.name,
            "description": workflow_detail.description or "",
            "version": workflow_detail.version,
            "agent_count": len(agents),
            "saved_agents_count": saved_agents_count,
            "node_count": len(workflow.nodes) if workflow.nodes else 0,
            "edge_count": len(workflow.edges) if workflow.edges else 0,
            "tags": workflow_detail.tags or [],
            "author": workflow_detail.author,
            "created_at": workflow_detail.created_at,
            "saved_to": "database",
        }

    # ========== 执行操作 ==========

    async def execute_workflow(
        self,
        params: Optional[Dict[str, Any]] = None,
    ) -> OperationResult:
        """
        执行工作流

        Args:
            params: 执行参数

        Returns:
            操作结果
        """
        if not self._ensure_builder() or not self._builder.draft_workflow:
            return OperationResult(success=False, message="没有可执行的工作流")

        try:
            from src.orchestration.workflow_engine import WorkflowEngine

            # 初始化工作流引擎（使用 MetaAgent 的 registry）
            if not self._workflow_engine:
                # 使用统一的路径获取方法
                executions_path = str(self._get_executions_path())

                # 加载应用层工作流配置
                try:
                    from src.config import get_app_config_loader

                    app_wf_config = get_app_config_loader().get_workflow_config()
                except Exception:
                    app_wf_config = {}

                self._workflow_engine = WorkflowEngine(
                    agent_registry=self.meta_agent.agent_registry,
                    tool_registry=self.tool_registry,
                    workspace_base_path=executions_path,
                    app_workflow_config=app_wf_config,
                )

            # 定义事件回调，转发执行事件
            # 注意：不再发送 execution_started/execution_completed，因为 WorkflowEngine 已经发送 workflow_started/workflow_completed
            async def event_callback(event: Dict[str, Any]) -> None:
                # 保存当前执行的 workflow_id，用于干预操作
                if event.get("event_type") == "workflow_started":
                    self._current_workflow_id = event.get("workflow_id")
                elif event.get("event_type") in (
                    "workflow_completed",
                    "workflow_failed",
                    "workflow_cancelled",
                ):
                    # 执行结束时清理 workflow_id（但保留一段时间以便查询）
                    pass  # 暂时不清理，允许后续查询

                if self._progress_callback:
                    # 直接转发 WorkflowEngine 的事件
                    await self._progress_callback(event)

            # 使用流式执行
            result = await self._workflow_engine.execute_with_streaming(
                workflow_definition=self._builder.draft_workflow,
                initial_context=params or {},
                event_callback=event_callback,
            )

            # WorkflowResult 是一个 dataclass，需要正确访问其属性
            # 构建详细的结果数据，包含 execution_id 用于前端查询
            nodes_completed = len(
                [r for r in result.node_results.values() if r.status == "success"]
            )
            nodes_failed = len(
                [r for r in result.node_results.values() if r.status == "failed"]
            )
            total_nodes = len(result.node_results)

            return OperationResult(
                success=result.status.value == "completed",
                message=f"工作流执行完成，状态: {result.status.value}",
                data={
                    "execution_id": result.workflow_id,  # 执行 ID，用于查询执行历史
                    "status": result.status.value,
                    "total_duration_ms": result.total_duration_ms,
                    "nodes_completed": nodes_completed,
                    "nodes_failed": nodes_failed,
                    "total_nodes": total_nodes,
                    "started_at": result.started_at,
                    "completed_at": result.completed_at,
                    "node_results": (
                        {
                            k: {
                                "status": v.status,
                                "duration_ms": v.duration_ms,
                                "error": v.error,
                            }
                            for k, v in result.node_results.items()
                        }
                        if result.node_results
                        else {}
                    ),
                },
            )

        except Exception as e:
            # 通知执行失败
            if self._progress_callback:
                await self._progress_callback(
                    {
                        "event_type": "execution_failed",
                        "error": str(e),
                        "message": f"工作流执行失败: {str(e)}",
                    }
                )
            logger.error(f"执行工作流失败: {e}, traceback: {traceback.format_exc()}")
            return OperationResult(success=False, message=str(e))

    async def pause_execution(self) -> OperationResult:
        """暂停执行"""
        if not self._current_workflow_id or not self._is_workflow_active():
            return OperationResult(success=False, message="没有正在执行的工作流")

        if self._workflow_engine:
            success = await self._workflow_engine.pause(self._current_workflow_id)
            if success:
                logger.info(f"工作流已暂停: {self._current_workflow_id}")
                return OperationResult(
                    success=True,
                    message="工作流已暂停，输入'继续'可恢复执行",
                )
            return OperationResult(
                success=False, message="暂停失败，工作流可能不在运行状态"
            )
        return OperationResult(success=False, message="工作流引擎未初始化")

    async def resume_execution(self) -> OperationResult:
        """恢复执行"""
        if not self._current_workflow_id:
            return OperationResult(success=False, message="没有可恢复的工作流")

        if self._workflow_engine:
            # 检查是否真的处于暂停状态
            if not self._workflow_engine.is_paused(self._current_workflow_id):
                return OperationResult(
                    success=False,
                    message="工作流未处于暂停状态，可能已完成或已恢复",
                )

            success = await self._workflow_engine.resume_execution(
                self._current_workflow_id
            )
            if success:
                logger.info(f"工作流已恢复: {self._current_workflow_id}")
                return OperationResult(success=True, message="工作流已恢复执行")
            return OperationResult(success=False, message="恢复失败，请重试")
        return OperationResult(success=False, message="工作流引擎未初始化")

    async def stop_execution(self) -> OperationResult:
        """停止执行"""
        if not self._current_workflow_id:
            return OperationResult(success=False, message="没有正在执行的工作流")

        if self._workflow_engine:
            workflow_id = self._current_workflow_id
            # 通过 engine.cancel() 走 FSM 标准路径
            success = await self._workflow_engine.cancel(workflow_id)
            if success:
                logger.info(f"工作流已停止: {workflow_id}")
                return OperationResult(
                    success=True, message="工作流已停止执行。当前执行已被取消。"
                )
            return OperationResult(success=False, message="停止失败，工作流可能已结束")
        return OperationResult(success=False, message="工作流引擎未初始化")

    async def skip_node(self, node_id: Optional[str] = None) -> OperationResult:
        """
        跳过指定节点

        Args:
            node_id: 要跳过的节点 ID，如果不指定则尝试跳过当前正在等待的节点
        """
        if not self._current_workflow_id or not self._is_workflow_active():
            return OperationResult(success=False, message="没有正在执行的工作流")

        if not self._workflow_engine:
            return OperationResult(success=False, message="工作流引擎未初始化")

        # 如果没有指定 node_id，尝试获取当前节点或下一个待执行节点
        if not node_id:
            # 从 WorkflowEngine 获取当前或下一个待执行节点
            # 这里需要 WorkflowEngine 提供相关接口
            if hasattr(self._workflow_engine, "_current_executing_node"):
                current_node = self._workflow_engine._current_executing_node.get(
                    self._current_workflow_id
                )
                if current_node:
                    node_id = current_node

        if not node_id:
            return OperationResult(
                success=False,
                message="请指定要跳过的节点 ID 或名称",
            )

        success = await self._workflow_engine.skip_node(
            self._current_workflow_id, node_id
        )
        if success:
            logger.info(f"将跳过节点: {node_id}")
            return OperationResult(success=True, message=f"将跳过节点: {node_id}")
        return OperationResult(success=False, message=f"跳过节点失败: {node_id}")

    async def inject_context(self, context: Dict[str, Any]) -> OperationResult:
        """
        向正在执行的工作流注入额外上下文

        Args:
            context: 要注入的上下文数据（键值对）
        """
        if not self._current_workflow_id or not self._is_workflow_active():
            return OperationResult(success=False, message="没有正在执行的工作流")

        if not self._workflow_engine:
            return OperationResult(success=False, message="工作流引擎未初始化")

        if not context:
            return OperationResult(success=False, message="请提供要注入的上下文数据")

        # 调用 WorkflowEngine 的 inject_context 方法
        if hasattr(self._workflow_engine, "inject_context"):
            success = await self._workflow_engine.inject_context(
                self._current_workflow_id, context
            )
            if success:
                logger.info(f"已注入上下文: {list(context.keys())}")
                return OperationResult(
                    success=True,
                    message=f"已注入上下文: {list(context.keys())}",
                )
            return OperationResult(success=False, message="注入上下文失败")
        else:
            # 如果 WorkflowEngine 没有 inject_context 方法，直接存储到 _injected_context
            if not hasattr(self._workflow_engine, "_injected_context"):
                self._workflow_engine._injected_context = {}
            if self._current_workflow_id not in self._workflow_engine._injected_context:
                self._workflow_engine._injected_context[self._current_workflow_id] = {}
            self._workflow_engine._injected_context[self._current_workflow_id].update(
                context
            )
            logger.info(f"已注入上下文（直接存储）: {list(context.keys())}")
            return OperationResult(
                success=True,
                message=f"已注入上下文: {list(context.keys())}",
            )

    # ========== 执行历史操作 ==========

    async def get_execution_history(self, limit: int = 10) -> OperationResult:
        """
        获取工作流执行历史列表

        Args:
            limit: 最多返回的记录数

        Returns:
            操作结果，包含执行历史列表
        """
        try:
            # 使用统一的路径获取方法
            executions_dir = self._get_executions_path()

            if not executions_dir.exists():
                return OperationResult(
                    success=True, message="暂无执行记录", data={"history": []}
                )

            records = []
            # 扫描执行目录
            workflow_dirs = sorted(
                [d for d in executions_dir.iterdir() if d.is_dir()],
                key=lambda x: x.stat().st_mtime,
                reverse=True,
            )

            for workflow_dir in workflow_dirs[
                : limit * 2
            ]:  # 多扫描一些，因为有些可能是节点目录
                # 检查是否有检查点目录（工作流执行目录的标志）
                checkpoint_dir = workflow_dir / "checkpoints"
                if not checkpoint_dir.exists():
                    continue

                # 尝试加载最新的检查点
                record = self._load_execution_record(workflow_dir)
                if record:
                    records.append(record)
                    if len(records) >= limit:
                        break

            return OperationResult(
                success=True,
                message=f"找到 {len(records)} 条执行记录",
                data={"history": records},
            )

        except Exception as e:
            logger.error(f"获取执行历史失败: {e}")
            return OperationResult(success=False, message=str(e))

    def _load_execution_record(self, workflow_dir: Path) -> Optional[Dict[str, Any]]:
        """从工作流目录加载执行记录"""
        try:
            checkpoint_dir = workflow_dir / "checkpoints"
            if not checkpoint_dir.exists():
                return None

            # 找到最新的检查点文件
            checkpoint_files = sorted(
                checkpoint_dir.glob("ckpt_*.json"),
                key=lambda x: x.stat().st_mtime,
                reverse=True,
            )

            if not checkpoint_files:
                return None

            with open(checkpoint_files[0], "r", encoding="utf-8") as f:
                checkpoint = json.load(f)

            # 解析检查点数据
            node_results = checkpoint.get("node_results", {})

            # 统计节点状态
            nodes_completed = sum(
                1 for r in node_results.values() if r.get("status") == "success"
            )
            nodes_failed = sum(
                1 for r in node_results.values() if r.get("status") == "failed"
            )
            nodes_total = len(node_results)

            # 计算总耗时
            total_duration = sum(r.get("duration_ms", 0) for r in node_results.values())

            # 判断整体状态 - 从检查点加载并规范化
            raw_status = checkpoint.get("status", "running")

            # 规范化状态（处理字符串和可能的枚举残留）
            status_lower = str(raw_status).lower()
            if status_lower in ("completed", "workflowstatus.completed"):
                status = "success"
            elif status_lower in ("failed", "workflowstatus.failed"):
                status = "failed"
            elif status_lower in ("cancelled", "workflowstatus.cancelled"):
                status = "cancelled"
            elif status_lower in (
                "running",
                "workflowstatus.running",
                "pending",
                "workflowstatus.pending",
            ):
                status = "running"
            else:
                status = "running"

            # 基于实际节点结果覆盖状态（如果状态为 running 但实际已完成）
            if status == "running":
                if nodes_failed > 0:
                    status = "failed"
                elif nodes_completed == nodes_total and nodes_total > 0:
                    status = "success"

            # 获取时间信息
            started_at = checkpoint.get("created_at", "")
            if node_results:
                # 尝试从节点结果获取开始时间
                start_times = [
                    r.get("started_at")
                    for r in node_results.values()
                    if r.get("started_at")
                ]
                if start_times:
                    started_at = min(start_times)

            return {
                "executionId": checkpoint.get("checkpoint_id", workflow_dir.name),
                "workflowId": checkpoint.get("workflow_id", workflow_dir.name),
                "status": status,
                "startedAt": started_at,
                "completedAt": checkpoint.get("completed_at"),
                "totalDurationMs": total_duration,
                "nodesTotal": nodes_total,
                "nodesCompleted": nodes_completed,
                "nodesFailed": nodes_failed,
            }

        except Exception as e:
            logger.warning(f"加载执行记录失败 {workflow_dir}: {e}")
            return None

    async def get_execution_detail(self, execution_id: str) -> OperationResult:
        """
        获取某次执行的详细信息

        Args:
            execution_id: 执行 ID

        Returns:
            操作结果，包含执行详情（所有节点的 input/output）
        """
        try:
            # 首先尝试从数据库获取执行记录
            try:
                from src.storage.database import AsyncDatabaseManager
                from src.services.workflow_service import WorkflowService
                
                db = AsyncDatabaseManager()
                await db.connect()
                try:
                    service = WorkflowService(db.session)
                    db_detail = await service.get_execution_detail(execution_id)
                    
                    if db_detail:
                        # 数据库中找到了执行记录，构造返回结果
                        status = db_detail.get("status", "pending")
                        # 规范化状态
                        if status == "completed":
                            status = "success"
                        
                        # 从 initial_context 获取触发来源
                        initial_context = db_detail.get("initial_context", {}) or {}
                        triggered_by = initial_context.get("triggered_by", "manual")
                        
                        result_data = {
                            "executionId": db_detail.get("id"),
                            "workflowId": db_detail.get("workflow_definition_id"),
                            "status": status,
                            "startedAt": db_detail.get("started_at"),
                            "completedAt": db_detail.get("completed_at"),
                            "totalDurationMs": db_detail.get("total_duration_ms", 0),
                            "error": db_detail.get("error"),
                            "triggeredBy": triggered_by,
                            "nodeResults": db_detail.get("node_results", {}),
                            "source": "database",  # 标记数据来源
                        }
                        
                        return OperationResult(
                            success=True,
                            message="成功获取执行详情（数据库）",
                            data=result_data,
                        )
                finally:
                    await db.close()
            except Exception as db_err:
                logger.debug(f"从数据库获取执行记录失败，尝试从文件系统获取: {db_err}")
            
            # 从本地文件系统查找（旧逻辑作为后备）
            executions_dir = self._get_executions_path()

            # 查找对应的执行目录
            target_dir = None
            for workflow_dir in executions_dir.iterdir():
                if not workflow_dir.is_dir():
                    continue
                checkpoint_dir = workflow_dir / "checkpoints"
                if not checkpoint_dir.exists():
                    continue
                # 检查是否匹配
                if execution_id in workflow_dir.name:
                    target_dir = workflow_dir
                    break
                # 检查检查点文件
                for ckpt_file in checkpoint_dir.glob("*.json"):
                    if execution_id in ckpt_file.stem:
                        target_dir = workflow_dir
                        break
                if target_dir:
                    break

            if not target_dir:
                return OperationResult(
                    success=False, message=f"未找到执行记录: {execution_id}"
                )

            # 加载检查点
            checkpoint_dir = target_dir / "checkpoints"
            checkpoint_files = sorted(
                checkpoint_dir.glob("ckpt_*.json"),
                key=lambda x: x.stat().st_mtime,
                reverse=True,
            )

            if not checkpoint_files:
                return OperationResult(success=False, message=f"未找到检查点文件")

            with open(checkpoint_files[0], "r", encoding="utf-8") as f:
                checkpoint = json.load(f)

            # 构建详细的节点结果
            node_results = {}
            for node_id, result in checkpoint.get("node_results", {}).items():
                # 尝试加载节点的输入输出
                node_workspace = executions_dir / f"{target_dir.name}_{node_id}"

                node_detail = {
                    "nodeId": node_id,
                    "nodeName": result.get("node_name", node_id),
                    "status": result.get("status", "pending"),
                    "startedAt": result.get("started_at"),
                    "completedAt": result.get("completed_at"),
                    "durationMs": result.get("duration_ms"),
                    "error": result.get("error"),
                }

                # 尝试加载输入
                input_file = node_workspace / "input" / "input.json"
                if input_file.exists():
                    try:
                        with open(input_file, "r", encoding="utf-8") as f:
                            node_detail["input"] = json.load(f)
                    except:
                        pass

                # 尝试加载输出
                output_file = node_workspace / "output" / "result.json"
                if output_file.exists():
                    try:
                        with open(output_file, "r", encoding="utf-8") as f:
                            node_detail["output"] = json.load(f)
                    except Exception:
                        pass

                # 扫描 output 目录中的附加文件（.md 报告等）
                # Agent 的正式输出产物在 output/ 目录下，result.json 可能仅包含摘要，
                # 附加文件（如 .md 报告）往往包含最完整的分析内容
                output_dir = node_workspace / "output"
                if output_dir.exists():
                    additional_files = []
                    try:
                        for fp in sorted(output_dir.iterdir()):
                            if not fp.is_file() or fp.name == "result.json":
                                continue
                            file_info = {
                                "filename": fp.name,
                                "path": str(fp.relative_to(node_workspace)),
                                "size_bytes": fp.stat().st_size,
                                "type": fp.suffix.lstrip("."),
                            }
                            # 文本类文件嵌入内容（上限 500KB）
                            if (
                                fp.suffix
                                in (
                                    ".md",
                                    ".txt",
                                    ".csv",
                                    ".json",
                                    ".html",
                                    ".xml",
                                    ".yaml",
                                    ".yml",
                                )
                                and fp.stat().st_size < 500_000
                            ):
                                try:
                                    file_info["content"] = fp.read_text(
                                        encoding="utf-8"
                                    )
                                except Exception:
                                    pass
                            additional_files.append(file_info)
                    except OSError:
                        pass
                    if additional_files:
                        node_detail["output_files"] = additional_files

                node_results[node_id] = node_detail

            return OperationResult(
                success=True,
                message="获取执行详情成功",
                data={
                    "executionId": execution_id,
                    "workflowId": checkpoint.get("workflow_id"),
                    "nodeResults": node_results,
                    "context": checkpoint.get("context"),
                },
            )

        except Exception as e:
            logger.error(f"获取执行详情失败: {e}")
            return OperationResult(success=False, message=str(e))

    # ========== Agent 优化操作 ==========

    async def optimize_agent_prompt(
        self,
        agent_name: str,
        field: str,
        current_value: str,
        optimization_goal: Optional[str] = None,
    ) -> OperationResult:
        """
        使用 LLM 优化 Agent 的 Prompt 字段

        Args:
            agent_name: Agent 名称
            field: 要优化的字段（如 'role_description', 'core_capability', 'task_context'）
            current_value: 当前字段值
            optimization_goal: 优化目标描述（可选）

        Returns:
            操作结果，包含优化后的内容
        """
        try:
            # 构建优化提示
            field_names = {
                "role_description": "角色描述",
                "core_capability": "核心能力",
                "task_context": "任务上下文",
                "description": "描述",
                "display_name": "显示名称",
            }

            field_display = field_names.get(field, field)
            goal = optimization_goal or "使其更清晰、更专业、更有效"

            prompt = f"""你是一个专业的 Prompt 优化专家。请优化以下 Agent 配置中的「{field_display}」字段。

## Agent 名称
{agent_name}

## 当前内容
{current_value}

## 优化目标
{goal}

## 优化要求
1. 保持原意，但使表述更清晰、更专业
2. 使用简洁有力的语言
3. 如果是角色描述，应该明确角色定位和专业能力
4. 如果是核心能力，应该具体说明能做什么
5. 如果是任务上下文，应该提供足够的背景信息

请直接输出优化后的内容，不要包含解释或说明。"""

            # 调用 LLM
            response = await self.meta_agent._call_llm(prompt)

            # 清理响应（移除可能的引号和多余空白）
            optimized_value = response.strip()
            if optimized_value.startswith('"') and optimized_value.endswith('"'):
                optimized_value = optimized_value[1:-1]
            if optimized_value.startswith("'") and optimized_value.endswith("'"):
                optimized_value = optimized_value[1:-1]

            return OperationResult(
                success=True,
                message=f"已优化「{field_display}」字段",
                data={
                    "field": field,
                    "original_value": current_value,
                    "optimized_value": optimized_value,
                },
            )

        except Exception as e:
            logger.error(
                f"优化 Agent Prompt 失败: {e}, traceback: {traceback.format_exc()}"
            )
            return OperationResult(success=False, message=f"优化失败: {str(e)}")

    async def update_agent_definition(
        self, agent_name: str, updates: Dict[str, Any]
    ) -> OperationResult:
        """
        更新 Agent 定义

        Args:
            agent_name: Agent 名称
            updates: 要更新的字段和值

        Returns:
            操作结果
        """
        if not self._builder:
            return OperationResult(success=False, message="没有正在进行的工作流")

        try:
            # 在 draft_agents 中查找 agent
            agent = None
            for a in self._builder.draft_agents:
                if a.name == agent_name:
                    agent = a
                    break

            if not agent:
                return OperationResult(
                    success=False, message=f"未找到 Agent: {agent_name}"
                )

            # 应用更新
            for key, value in updates.items():
                if "." in key:
                    # 处理嵌套字段（如 'background_instruction.role_description'）
                    parts = key.split(".")
                    obj = agent
                    for part in parts[:-1]:
                        obj = getattr(obj, part, None)
                        if obj is None:
                            break
                    if obj is not None:
                        setattr(obj, parts[-1], value)
                else:
                    if hasattr(agent, key):
                        setattr(agent, key, value)

            # 自动递增版本号
            old_version = agent.version
            try:
                parts = agent.version.split(".")
                parts[-1] = str(int(parts[-1]) + 1)
                agent.version = ".".join(parts)
            except (ValueError, IndexError):
                # 如果版本号格式不正确，使用默认递增
                agent.version = "1.0.1"

            # 通知状态机：Agent 被修改
            if self._builder:
                self._builder.fsm.on_agent_regenerated(agent_name)

            display_name = agent.display_name or agent.name
            return OperationResult(
                success=True,
                message=f"已更新「{display_name}」(v{old_version} → v{agent.version})",
                data={
                    "agent_name": agent_name,
                    "updated_fields": list(updates.keys()),
                    "old_version": old_version,
                    "new_version": agent.version,
                },
                workflow_changed=True,
            )

        except Exception as e:
            logger.error(
                f"更新 Agent 定义失败: {e}, traceback: {traceback.format_exc()}"
            )
            return OperationResult(success=False, message=str(e))

    async def get_agent_definition(self, agent_name: str) -> OperationResult:
        """
        获取 Agent 的完整定义

        Args:
            agent_name: Agent 名称

        Returns:
            操作结果，包含 Agent 定义
        """
        if not self._builder:
            return OperationResult(success=False, message="没有正在进行的工作流")

        try:
            # 在 draft_agents 中查找 agent
            for agent in self._builder.draft_agents:
                if agent.name == agent_name:
                    agent_dict = (
                        agent.model_dump()
                        if hasattr(agent, "model_dump")
                        else agent.__dict__
                    )
                    return OperationResult(
                        success=True,
                        message=f"获取 Agent 定义成功",
                        data={"agent_definition": agent_dict},
                    )

            return OperationResult(success=False, message=f"未找到 Agent: {agent_name}")

        except Exception as e:
            logger.error(
                f"获取 Agent 定义失败: {e}, traceback: {traceback.format_exc()}"
            )
            return OperationResult(success=False, message=str(e))

    # ========== 查询操作 ==========

    def get_current_plan(self) -> Optional[Dict[str, Any]]:
        """获取当前规划"""
        if self._builder and self._builder.current_plan:
            return self._builder.current_plan.to_dict()
        return None

    def get_current_agents(self) -> List[Dict[str, Any]]:
        """获取当前 Agent 列表（规划中的 agent specs）"""
        if not self._builder:
            return []

        # 优先返回规划中的 agent specs
        if self._builder.current_plan and self._builder.current_plan.agent_specs:
            return [spec.to_dict() for spec in self._builder.current_plan.agent_specs]

        # 否则返回 draft agents
        return [
            a.model_dump() if hasattr(a, "model_dump") else a.__dict__
            for a in self._builder.draft_agents
        ]

    def get_draft_agents(self) -> List[Dict[str, Any]]:
        """获取已生成的 draft agents（完整的 AgentDefinition）"""
        if not self._builder:
            return []

        return [
            a.model_dump() if hasattr(a, "model_dump") else a.__dict__
            for a in self._builder.draft_agents
        ]

    def get_current_workflow(self) -> Optional[Dict[str, Any]]:
        """获取当前工作流"""
        if self._builder and self._builder.draft_workflow:
            if hasattr(self._builder.draft_workflow, "model_dump"):
                return self._builder.draft_workflow.model_dump()
            return self._builder.draft_workflow.__dict__
        return None

    def get_checkpoints(self) -> List[Dict[str, Any]]:
        """获取检查点列表"""
        if not self._builder:
            return []
        return [
            ckpt.to_dict() for ckpt in self._builder.iteration_manager.get_checkpoints()
        ]

    def _is_workflow_active(self) -> bool:
        """检查当前工作流是否处于活跃状态（运行中或暂停中），通过 FSM 查询"""
        if not self._workflow_engine or not self._current_workflow_id:
            return False
        return self._workflow_engine.is_running(
            self._current_workflow_id
        ) or self._workflow_engine.is_paused(self._current_workflow_id)

    def get_execution_status(self) -> Dict[str, Any]:
        """获取执行状态（委托给 WorkflowEngine 的 FSM）"""
        is_executing = False
        is_paused = False
        if self._workflow_engine and self._current_workflow_id:
            is_executing = self._workflow_engine.is_running(self._current_workflow_id)
            is_paused = self._workflow_engine.is_paused(self._current_workflow_id)

        return {
            "is_executing": is_executing or is_paused,  # 活跃中（运行或暂停）
            "is_paused": is_paused,
            "current_workflow_id": self._current_workflow_id,
            "has_workflow": self._builder and self._builder.draft_workflow is not None,
        }

    def get_current_stage(self) -> str:
        """获取当前阶段"""
        if self._builder:
            return self._builder.current_stage.value
        return "idle"

    def get_available_tools(self) -> List[Dict[str, Any]]:
        """获取可用工具列表"""
        if not self.tool_registry:
            return []

        try:
            return self.tool_registry.list_tools()
        except Exception as e:
            logger.warning(f"获取可用工具列表失败: {e}")
            return []

    # ========== 工作流库和智能体库管理 ==========

    async def search_workflows(
        self,
        query: Optional[str] = None,
        tags: Optional[List[str]] = None,
        limit: int = 10,
    ) -> OperationResult:
        """
        搜索已保存的工作流

        Args:
            query: 搜索关键词（可选）
            tags: 标签过滤（可选）
            limit: 返回数量限制

        Returns:
            包含工作流列表的操作结果
        """
        import os

        try:
            # 检查是否启用了数据库
            if os.getenv("ENABLE_POSTGRES", "false").lower() != "true":
                return OperationResult(
                    success=False,
                    message="数据库未启用，无法搜索工作流。请设置 ENABLE_POSTGRES=true 并配置数据库连接。",
                    data={"workflows": []},
                )

            from src.services import WorkflowService
            from src.services.workflow_service import WorkflowFilters
            from src.storage.database import AsyncDatabaseManager
            from src.storage.repositories import (
                WorkflowDefinitionRepository,
                WorkflowExecutionRepository,
            )
            from src.storage.config import PostgreSQLConfig

            # 创建数据库连接
            config = PostgreSQLConfig(
                host=os.getenv("POSTGRES_HOST", "localhost"),
                port=int(os.getenv("POSTGRES_PORT", "5432")),
                database=os.getenv("POSTGRES_DB", "agent_framework"),
                user=os.getenv("POSTGRES_USER", "postgres"),
                password=os.getenv("POSTGRES_PASSWORD", ""),
            )
            db = AsyncDatabaseManager(config)
            await db.connect()

            try:
                workflow_repo = WorkflowDefinitionRepository(db._session_factory)
                execution_repo = WorkflowExecutionRepository(db._session_factory)
                service = WorkflowService(workflow_repo, execution_repo)

                # 构建过滤条件
                filters = WorkflowFilters(
                    query=query,
                    tags=tags,
                    is_active=True,  # 只搜索激活的工作流
                    limit=limit,
                )

                workflows = await service.list_workflows(filters)

                # 格式化结果
                workflow_list = [
                    {
                        "id": w.id,
                        "workflow_id": w.workflow_id,
                        "name": w.name,
                        "description": w.description,
                        "version": w.version,
                        "node_count": w.node_count,
                        "edge_count": w.edge_count,
                        "tags": w.tags,
                        "author": w.author,
                        "created_at": w.created_at,
                        "updated_at": w.updated_at,
                    }
                    for w in workflows
                ]

                if not workflow_list:
                    message = "没有找到匹配的工作流。"
                    if query:
                        message = f"没有找到包含 '{query}' 的工作流。"
                else:
                    message = f"找到 {len(workflow_list)} 个工作流："
                    for w in workflow_list[:5]:  # 只在消息中显示前5个
                        message += f"\n- **{w['name']}**: {w['description'][:50] if w['description'] else '无描述'}..."

                return OperationResult(
                    success=True,
                    message=message,
                    data={
                        "type": "workflow_search_result",
                        "workflows": workflow_list,
                        "total": len(workflow_list),
                    },
                )

            finally:
                await db.close()

        except Exception as e:
            logger.error(f"搜索工作流失败: {e}")
            return OperationResult(
                success=False,
                message=f"搜索工作流失败: {str(e)}",
                data={"workflows": []},
            )

    async def load_saved_workflow(
        self,
        workflow_id: str,
    ) -> OperationResult:
        """
        加载已保存的工作流到当前会话

        Args:
            workflow_id: 工作流 ID 或名称

        Returns:
            操作结果，包含工作流信息和执行历史
        """
        import os

        if not workflow_id:
            return OperationResult(
                success=False,
                message="请提供要加载的工作流 ID 或名称。",
            )
        workflow_id = workflow_id.strip()
        workflow_id = workflow_id.strip()

        try:
            # 检查是否启用了数据库
            if os.getenv("ENABLE_POSTGRES", "false").lower() != "true":
                return OperationResult(
                    success=False,
                    message="数据库未启用，无法加载工作流。请设置 ENABLE_POSTGRES=true 并配置数据库连接。",
                )

            from src.services import WorkflowService, AgentService
            from src.services.workflow_service import WorkflowFilters
            from src.storage.database import AsyncDatabaseManager
            from src.storage.repositories import (
                WorkflowDefinitionRepository,
                WorkflowExecutionRepository,
                AgentRepository,
            )
            from src.storage.config import PostgreSQLConfig
            from src.definitions import WorkflowDefinition, AgentDefinition

            # 创建数据库连接
            config = PostgreSQLConfig(
                host=os.getenv("POSTGRES_HOST", "localhost"),
                port=int(os.getenv("POSTGRES_PORT", "5432")),
                database=os.getenv("POSTGRES_DB", "agent_framework"),
                user=os.getenv("POSTGRES_USER", "postgres"),
                password=os.getenv("POSTGRES_PASSWORD", ""),
            )
            db = AsyncDatabaseManager(config)
            await db.connect()

            try:
                workflow_repo = WorkflowDefinitionRepository(db._session_factory)
                execution_repo = WorkflowExecutionRepository(db._session_factory)
                agent_repo = AgentRepository(db._session_factory)
                service = WorkflowService(workflow_repo, execution_repo)

                workflow_detail = None
                workflow_summary = None  # 保存摘要信息（包含 node_count）
                loaded_by_db_id = False

                # 1) 尝试按数据库主键 ID 直接加载（支持 "id:xxx" 或直接传入 id）
                database_id_candidate = (
                    workflow_id[3:] if workflow_id.startswith("id:") else workflow_id
                )
                if database_id_candidate:
                    logger.info(f"尝试按数据库主键加载工作流: {database_id_candidate}")
                    workflow_detail = await service.get_workflow_by_id(
                        database_id_candidate
                    )
                    if workflow_detail:
                        loaded_by_db_id = True

                # 2) 如果未找到，则按 workflow_id / name 进行模糊搜索
                if not workflow_detail:
                    filters = WorkflowFilters(query=workflow_id, limit=5)
                    workflows = await service.list_workflows(filters)

                    if workflows:
                        # 优先匹配精确的 workflow_id
                        exact_match = next(
                            (w for w in workflows if w.workflow_id == workflow_id),
                            None,
                        )
                        if exact_match:
                            workflow_summary = exact_match
                            workflow_detail = await service.get_workflow_by_id(
                                exact_match.id
                            )
                        else:
                            # 多个匹配时拒绝自动选择，要求用户明确指定
                            if len(workflows) > 1:
                                return OperationResult(
                                    success=False,
                                    message=(
                                        "找到多个匹配的工作流，请通过唯一 ID 进行加载。"
                                    ),
                                    data={
                                        "type": "workflow_search_result",
                                        "workflows": [
                                            {
                                                "id": w.id,
                                                "workflow_id": w.workflow_id,
                                                "name": w.name,
                                                "description": w.description,
                                                "version": w.version,
                                                "node_count": w.node_count,
                                                "edge_count": w.edge_count,
                                                "tags": w.tags,
                                                "author": w.author,
                                                "created_at": w.created_at,
                                                "updated_at": w.updated_at,
                                            }
                                            for w in workflows
                                        ],
                                        "total": len(workflows),
                                    },
                                )
                            workflow_summary = workflows[0]
                            workflow_detail = await service.get_workflow_by_id(
                                workflows[0].id
                            )

                if not workflow_detail:
                    return OperationResult(
                        success=False,
                        message=f"找不到工作流: {workflow_id}",
                    )

                # 获取执行历史（优先按 workflow_definition_id 精确查询）
                if loaded_by_db_id:
                    execution_history = await execution_repo.get_by_workflow(
                        workflow_definition_id=workflow_detail.id, limit=10
                    )
                else:
                    execution_history = await service.get_execution_history(
                        workflow_detail.workflow_id, limit=10
                    )

                # 将工作流加载到 builder
                definition = workflow_detail.definition
                workflow = WorkflowDefinition(**definition)

                # ========== 关键修复：加载工作流引用的 Agents ==========
                # 从工作流节点中提取所有 agent_id
                agent_ids = set()
                for node in workflow.nodes:
                    if node.agent_id:
                        agent_ids.add(node.agent_id)
                    # 也检查 config 中的 agent_id（兼容旧格式）
                    if node.config and node.config.get("agent_id"):
                        agent_ids.add(node.config.get("agent_id"))

                # 从数据库加载这些 Agents 并注册到 AgentRegistry
                loaded_agents = []
                for agent_id in agent_ids:
                    try:
                        agent_model = await agent_repo.get_by_agent_id(agent_id)
                        if agent_model and agent_model.definition_json:
                            # 从数据库记录构建 AgentDefinition
                            agent_def = AgentDefinition(**agent_model.definition_json)
                            loaded_agents.append(agent_def)

                            # 注册到 AgentRegistry（用于执行时查找）
                            if not self.meta_agent.agent_registry.get_definition(
                                agent_id
                            ):
                                self.meta_agent.agent_registry.register_definition(
                                    agent_def
                                )
                                logger.debug(f"已注册 Agent 到 Registry: {agent_id}")
                        else:
                            logger.warning(f"Agent 不存在于数据库: {agent_id}")
                    except Exception as agent_error:
                        logger.warning(f"加载 Agent {agent_id} 失败: {agent_error}")

                logger.info(
                    f"工作流加载完成: {workflow.name}, "
                    f"已加载 {len(loaded_agents)}/{len(agent_ids)} 个 Agents"
                )

                # 初始化或更新 builder
                from .interactive_builder import InteractiveWorkflowBuilder

                if not self._builder:
                    self._builder = InteractiveWorkflowBuilder(
                        meta_agent=self.meta_agent,
                        callback=None,
                        storage_path=self.storage_path,
                    )

                self._builder.draft_workflow = workflow
                # 设置加载的 agents 到 draft_agents
                self._builder.draft_agents = loaded_agents
                self._task_description = workflow.description or workflow.name

                # 格式化执行历史
                def _normalize_status(raw_status: Optional[str]) -> Optional[str]:
                    if raw_status in ("completed", "success"):
                        return "success"
                    return raw_status

                history_list = []
                for h in execution_history:
                    # service.get_execution_history 返回 ExecutionSummary
                    # execution_repo.get_by_workflow 返回 WorkflowExecutionModel
                    if hasattr(h, "to_dict"):
                        node_results = h.node_results or {}
                        nodes_completed = sum(
                            1
                            for r in node_results.values()
                            if r.get("status") == "completed"
                        )
                        nodes_failed = sum(
                            1
                            for r in node_results.values()
                            if r.get("status") == "failed"
                        )
                        history_list.append(
                            {
                                "execution_id": h.id,
                                "status": _normalize_status(
                                    h.status.value if h.status else None
                                ),
                                "started_at": (
                                    h.started_at.isoformat() if h.started_at else None
                                ),
                                "completed_at": (
                                    h.completed_at.isoformat()
                                    if h.completed_at
                                    else None
                                ),
                                "total_duration_ms": h.total_duration_ms,
                                "nodes_completed": nodes_completed,
                                "nodes_failed": nodes_failed,
                            }
                        )
                    else:
                        history_list.append(
                            {
                                "execution_id": h.id,
                                "status": _normalize_status(h.status),
                                "started_at": h.started_at,
                                "completed_at": h.completed_at,
                                "total_duration_ms": h.total_duration_ms,
                                "nodes_completed": h.nodes_completed,
                                "nodes_failed": h.nodes_failed,
                            }
                        )

                # 从定义中计算节点数
                node_count = len(workflow.nodes) if workflow.nodes else 0
                if workflow_summary:
                    node_count = workflow_summary.node_count

                message = f"✅ 已加载工作流: **{workflow_detail.name}**\n"
                message += f"- 版本: v{workflow_detail.version}\n"
                message += f"- 节点数: {node_count}\n"
                if execution_history:
                    message += f"- 执行历史: {len(execution_history)} 条记录\n"
                message += "\n工作流已准备就绪，您可以直接执行或进行修改。"

                return OperationResult(
                    success=True,
                    message=message,
                    data={
                        "type": "workflow_loaded",
                        "workflow": {
                            "id": workflow_detail.id,
                            "workflow_id": workflow_detail.workflow_id,
                            "name": workflow_detail.name,
                            "description": workflow_detail.description,
                            "version": workflow_detail.version,
                            "node_count": node_count,
                        },
                        "execution_history": history_list,
                    },
                    workflow_changed=True,
                )

            finally:
                await db.close()

        except Exception as e:
            logger.error(f"加载工作流失败: {e}")
            return OperationResult(
                success=False,
                message=f"加载工作流失败: {str(e)}",
            )

    async def search_agents(
        self,
        query: Optional[str] = None,
        domain_type: Optional[str] = None,
        is_template: Optional[bool] = None,
        limit: int = 10,
    ) -> OperationResult:
        """
        搜索已保存的 Agent

        Args:
            query: 搜索关键词（可选）
            domain_type: 领域类型过滤（可选）
            is_template: 是否只搜索模板（可选）
            limit: 返回数量限制

        Returns:
            包含 Agent 列表的操作结果
        """
        import os

        try:
            # 检查是否启用了数据库
            if os.getenv("ENABLE_POSTGRES", "false").lower() != "true":
                return OperationResult(
                    success=False,
                    message="数据库未启用，无法搜索 Agent。请设置 ENABLE_POSTGRES=true 并配置数据库连接。",
                    data={"agents": []},
                )

            from src.services import AgentService
            from src.services.agent_service import AgentFilters
            from src.storage.database import AsyncDatabaseManager
            from src.storage.repositories import AgentRepository
            from src.storage.config import PostgreSQLConfig

            # 创建数据库连接
            config = PostgreSQLConfig(
                host=os.getenv("POSTGRES_HOST", "localhost"),
                port=int(os.getenv("POSTGRES_PORT", "5432")),
                database=os.getenv("POSTGRES_DB", "agent_framework"),
                user=os.getenv("POSTGRES_USER", "postgres"),
                password=os.getenv("POSTGRES_PASSWORD", ""),
            )
            db = AsyncDatabaseManager(config)
            await db.connect()

            try:
                agent_repo = AgentRepository(db._session_factory)
                service = AgentService(agent_repo)

                # 构建过滤条件（不过滤 status，显示所有 Agent）
                filters = AgentFilters(
                    query=query,
                    domain_type=domain_type,
                    is_template=is_template,
                    limit=limit,
                )

                agents = await service.list_agents(filters)

                # 格式化结果
                agent_list = [
                    {
                        "id": a.id,
                        "agent_id": a.agent_id,
                        "name": a.name,
                        "description": a.description,
                        "version": a.version,
                        "domain_type": a.domain_type,
                        "execution_type": a.execution_type,
                        "model_name": a.model_name,
                        "tags": a.tags,
                        "is_template": a.is_template,
                        "created_at": a.created_at,
                        "updated_at": a.updated_at,
                    }
                    for a in agents
                ]

                if not agent_list:
                    message = "没有找到匹配的 Agent。"
                    if query:
                        message = f"没有找到包含 '{query}' 的 Agent。"
                else:
                    message = f"找到 {len(agent_list)} 个 Agent："
                    for a in agent_list[:5]:  # 只在消息中显示前5个
                        desc = a["description"][:50] if a["description"] else "无描述"
                        message += (
                            f"\n- **{a['name']}** ({a['domain_type']}): {desc}..."
                        )

                return OperationResult(
                    success=True,
                    message=message,
                    data={
                        "type": "agent_search_result",
                        "agents": agent_list,
                        "total": len(agent_list),
                    },
                )

            finally:
                await db.close()

        except Exception as e:
            logger.error(f"搜索 Agent 失败: {e}")
            return OperationResult(
                success=False,
                message=f"搜索 Agent 失败: {str(e)}",
                data={"agents": []},
            )

    async def add_saved_agent(
        self,
        agent_id: str,
    ) -> OperationResult:
        """
        将已保存的 Agent 添加到当前工作流

        Args:
            agent_id: Agent ID 或名称

        Returns:
            操作结果
        """
        import os

        if not agent_id:
            return OperationResult(
                success=False,
                message="请提供要添加的 Agent ID 或名称。",
            )
        agent_id = agent_id.strip()

        # 检查是否有当前工作流
        if not self._builder or not self._builder.draft_workflow:
            return OperationResult(
                success=False,
                message="请先创建或加载一个工作流，然后再添加 Agent。",
            )

        try:
            # 检查是否启用了数据库
            if os.getenv("ENABLE_POSTGRES", "false").lower() != "true":
                return OperationResult(
                    success=False,
                    message="数据库未启用，无法添加已保存的 Agent。请设置 ENABLE_POSTGRES=true 并配置数据库连接。",
                )

            from src.services import AgentService
            from src.services.agent_service import AgentFilters
            from src.storage.database import AsyncDatabaseManager
            from src.storage.repositories import AgentRepository
            from src.storage.config import PostgreSQLConfig
            from src.definitions import AgentDefinition

            # 创建数据库连接
            config = PostgreSQLConfig(
                host=os.getenv("POSTGRES_HOST", "localhost"),
                port=int(os.getenv("POSTGRES_PORT", "5432")),
                database=os.getenv("POSTGRES_DB", "agent_framework"),
                user=os.getenv("POSTGRES_USER", "postgres"),
                password=os.getenv("POSTGRES_PASSWORD", ""),
            )
            db = AsyncDatabaseManager(config)
            await db.connect()

            try:
                agent_repo = AgentRepository(db._session_factory)
                service = AgentService(agent_repo)

                agent_detail = None

                # 1) 尝试按数据库主键 ID 直接加载（支持 "id:xxx" 或直接传入 id）
                database_id_candidate = (
                    agent_id[3:] if agent_id.startswith("id:") else agent_id
                )
                if database_id_candidate:
                    logger.info(f"尝试按数据库主键加载 Agent: {database_id_candidate}")
                    agent_detail = await service.get_agent_by_id(database_id_candidate)

                # 2) 如果未找到，则按 agent_id / name 进行搜索
                if not agent_detail:
                    agent_detail = await service.get_agent(agent_id)

                    if not agent_detail:
                        filters = AgentFilters(query=agent_id, limit=5)
                        agents = await service.list_agents(filters)
                        if agents:
                            exact_match = next(
                                (a for a in agents if a.agent_id == agent_id),
                                None,
                            )
                            if exact_match:
                                agent_detail = await service.get_agent_by_id(
                                    exact_match.id
                                )
                            else:
                                if len(agents) > 1:
                                    return OperationResult(
                                        success=False,
                                        message=(
                                            "找到多个匹配的 Agent，请通过唯一 ID 进行添加。"
                                        ),
                                        data={
                                            "type": "agent_search_result",
                                            "agents": [
                                                {
                                                    "id": a.id,
                                                    "agent_id": a.agent_id,
                                                    "name": a.name,
                                                    "description": a.description,
                                                    "version": a.version,
                                                    "domain_type": a.domain_type,
                                                    "execution_type": a.execution_type,
                                                    "model_name": a.model_name,
                                                    "tags": a.tags,
                                                    "is_template": a.is_template,
                                                    "created_at": a.created_at,
                                                    "updated_at": a.updated_at,
                                                }
                                                for a in agents
                                            ],
                                            "total": len(agents),
                                        },
                                    )
                                agent_detail = await service.get_agent_by_id(
                                    agents[0].id
                                )

                if not agent_detail:
                    return OperationResult(
                        success=False,
                        message=f"找不到 Agent: {agent_id}",
                    )

                # 从数据库定义创建 AgentDefinition
                agent_def = AgentDefinition(**agent_detail.definition)

                # 添加到工作流的 agents 字典
                self._builder.draft_workflow.agents[agent_def.agent_id] = agent_def

                message = f"✅ 已将 **{agent_detail.name}** 添加到当前工作流。\n"
                message += f"- Agent ID: {agent_def.agent_id}\n"
                message += f"- 领域类型: {agent_detail.domain_type}\n"
                message += "\n您可以继续添加更多 Agent，或者修改工作流结构。"

                return OperationResult(
                    success=True,
                    message=message,
                    data={
                        "type": "agent_added",
                        "agent": {
                            "id": agent_detail.id,
                            "agent_id": agent_detail.agent_id,
                            "name": agent_detail.name,
                            "description": agent_detail.description,
                        },
                    },
                    workflow_changed=True,
                )

            finally:
                await db.close()

        except Exception as e:
            logger.error(f"添加 Agent 失败: {e}")
            return OperationResult(
                success=False,
                message=f"添加 Agent 失败: {str(e)}",
            )

    # ========== 辅助方法 ==========

    def _generate_workflow_structure(self) -> str:
        """生成工作流结构描述"""
        if not self._builder or not self._builder.current_plan:
            return ""

        specs = self._builder.current_plan.agent_specs
        if not specs:
            return "空工作流"

        # 构建描述
        parts = []
        for spec in specs:
            if spec.dependencies:
                parts.append(f"{spec.name} (依赖: {', '.join(spec.dependencies)})")
            else:
                parts.append(f"{spec.name} (起始节点)")

        return " → ".join(parts)

    def _get_valid_tools(self) -> set:
        """
        从 ToolRegistry 动态获取有效工具列表

        Returns:
            有效工具 ID 集合
        """
        if self._valid_tools_cache is not None:
            return self._valid_tools_cache

        valid_tools = set()

        # 从 ToolRegistry 获取已注册的工具
        if self.tool_registry:
            try:
                tools_list = self.tool_registry.list_tools()
                for tool_info in tools_list:
                    tool_id = tool_info.get("tool_id", "")
                    if tool_id:
                        valid_tools.add(tool_id)
                    # 也添加别名
                    alias = tool_info.get("alias", "")
                    if alias:
                        valid_tools.add(alias)
            except Exception as e:
                logger.warning(f"无法从 ToolRegistry 获取工具列表: {e}")

        # 如果没有从 registry 获取到，使用默认的内置工具
        if not valid_tools:
            valid_tools = {
                "qveris_search_tools",
                "qveris_execute_tool",
                "file_ls",
                "file_read",
                "file_write",
                "file_edit",
                "file_append",
                "bash_execute",
                "bash_execute_safe",
            }

        self._valid_tools_cache = valid_tools
        logger.debug(f"有效工具列表: {valid_tools}")
        return valid_tools

    def _validate_tools(self, tools: List[str]) -> List[str]:
        """
        验证并过滤工具列表，只保留有效工具

        Args:
            tools: 待验证的工具列表

        Returns:
            有效的工具列表
        """
        valid_tools = self._get_valid_tools()

        validated = []
        for tool in tools:
            tool_stripped = tool.strip()
            # 检查是否是有效工具
            if tool_stripped in valid_tools:
                validated.append(tool_stripped)
            else:
                # 尝试映射常见的别名到有效工具
                tool_lower = tool_stripped.lower()
                mapped = False

                if "qveris" in tool_lower or "远程" in tool_lower:
                    if (
                        "qveris_search_tools" in valid_tools
                        and "qveris_search_tools" not in validated
                    ):
                        validated.append("qveris_search_tools")
                        mapped = True
                    if (
                        "qveris_execute_tool" in valid_tools
                        and "qveris_execute_tool" not in validated
                    ):
                        validated.append("qveris_execute_tool")
                        mapped = True
                elif "file" in tool_lower or "文件" in tool_lower:
                    for ft in ["file_read", "file_write", "file_ls"]:
                        if ft in valid_tools and ft not in validated:
                            validated.append(ft)
                            mapped = True
                elif (
                    "bash" in tool_lower
                    or "shell" in tool_lower
                    or "命令" in tool_lower
                ):
                    if (
                        "bash_execute_safe" in valid_tools
                        and "bash_execute_safe" not in validated
                    ):
                        validated.append("bash_execute_safe")
                        mapped = True

                if not mapped:
                    logger.warning(f"工具 '{tool}' 不存在于注册表中，已忽略")

        # 确保至少有基础工具
        if not validated:
            default_tools = ["qveris_search_tools", "qveris_execute_tool"]
            validated = [t for t in default_tools if t in valid_tools]
            if not validated:
                # 最后的备选
                validated = list(valid_tools)[:2] if valid_tools else []

        return validated

    def refresh_tools_cache(self) -> None:
        """刷新工具缓存"""
        self._valid_tools_cache = None
