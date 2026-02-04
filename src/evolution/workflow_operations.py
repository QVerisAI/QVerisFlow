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

        # 执行状态
        self._is_executing = False
        self._execution_task = None

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

    def _ensure_builder(self) -> bool:
        """确保 builder 已初始化"""
        return self._builder is not None

    def _init_builder(self, task_description: str) -> None:
        """初始化构建器"""
        from .interactive_builder import InteractiveWorkflowBuilder

        self._task_description = task_description
        self._builder = InteractiveWorkflowBuilder(
            meta_agent=self.meta_agent,
            callback=None,  # 不使用回调，由 DialogueAgent 处理
            storage_path=self.storage_path,
            max_iterations_per_step=3,
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

            # 创建检查点
            self._builder.iteration_manager.checkpoint(
                label=f"add_agent_{name}",
                stage=self._builder.current_stage,
                state=self._builder._get_current_state(),
            )

            # 使用显示名称进行用户友好的反馈
            friendly_name = display_name or name
            return OperationResult(
                success=True,
                message=f"已添加「{friendly_name}」到工作流规划",
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

        Returns:
            操作结果
        """
        if not self._ensure_builder() or not self._builder.draft_agents:
            return OperationResult(success=False, message="没有可用的 Agent")

        try:
            from .interactive_builder import InteractionStage

            self._builder.current_stage = InteractionStage.WORKFLOW

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
                self._builder.draft_workflow = workflow

                self._builder.iteration_manager.checkpoint(
                    label="assemble_workflow",
                    stage=self._builder.current_stage,
                    state=self._builder._get_current_state(),
                )

                return OperationResult(
                    success=True,
                    message=f"已组装工作流，包含 {len(workflow.nodes)} 个节点",
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
        批准当前状态，进入下一阶段

        Returns:
            操作结果
        """
        if not self._ensure_builder():
            return OperationResult(success=False, message="没有可批准的内容")

        from .interactive_builder import InteractionStage

        current_stage = self._builder.current_stage

        try:
            if current_stage == InteractionStage.PLAN:
                # 1. 先发送批准消息（在生成之前）
                if self._progress_callback:
                    try:
                        await self._progress_callback(
                            {
                                "type": "approval_started",
                                "stage": "plan",
                                "message": "规划已批准，正在生成 Agents...",
                            }
                        )
                        # 让出事件循环，确保消息能够立即发送到前端
                        await asyncio.sleep(0)
                    except Exception as cb_error:
                        logger.warning(f"批准消息回调执行失败: {cb_error}")

                # 2. 执行生成
                result = await self.generate_agents_from_plan()

                # 3. 返回最终汇总（不再包含"规划已批准"前缀，因为已经单独发送）
                if result.success:
                    return OperationResult(
                        success=True,
                        message=result.message,
                        data=result.data,
                        workflow_changed=True,
                    )
                return result

            elif current_stage == InteractionStage.AGENT:
                # 1. 先发送批准消息
                if self._progress_callback:
                    try:
                        await self._progress_callback(
                            {
                                "type": "approval_started",
                                "stage": "agent",
                                "message": "Agents 已批准，正在组装工作流...",
                            }
                        )
                        # 让出事件循环，确保消息能够立即发送到前端
                        await asyncio.sleep(0)
                    except Exception as cb_error:
                        logger.warning(f"批准消息回调执行失败: {cb_error}")

                # 2. 组装工作流
                result = await self.assemble_workflow()
                if result.success:
                    return OperationResult(
                        success=True,
                        message=result.message,
                        data=result.data,
                        workflow_changed=True,
                    )
                return result

            elif current_stage == InteractionStage.WORKFLOW:
                # 工作流已完成
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

            return OperationResult(success=True, message="当前状态已确认")

        except Exception as e:
            logger.error(f"批准状态失败: {e}, traceback: {traceback.format_exc()}")
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

                    # 保存所有 Agents 到数据库
                    for agent_def in agents:
                        try:
                            agent_data = (
                                agent_def.model_dump(mode="json")
                                if hasattr(agent_def, "model_dump")
                                else agent_def.__dict__
                            )
                            await agent_service.create_agent_from_dict(
                                agent_data=agent_data,
                                author=author,
                            )
                            saved_agents_count += 1
                        except Exception as agent_error:
                            logger.warning(f"保存 Agent 失败: {agent_error}")

                    await db.close()

                    # 构建工作流信息卡片数据
                    result_data = self._build_workflow_info_card(
                        workflow_detail=workflow_detail,
                        workflow=workflow,
                        agents=agents,
                        saved_agents_count=saved_agents_count,
                    )
                    db_saved = True

                    logger.info(
                        f"工作流已保存到数据库: {workflow_detail.name} "
                        f"(ID: {workflow_detail.workflow_id}), "
                        f"Agents: {saved_agents_count}/{len(agents)}"
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

                self._workflow_engine = WorkflowEngine(
                    agent_registry=self.meta_agent.agent_registry,
                    tool_registry=self.tool_registry,
                    workspace_base_path=executions_path,
                )

            # 定义事件回调，转发执行事件
            # 注意：不再发送 execution_started/execution_completed，因为 WorkflowEngine 已经发送 workflow_started/workflow_completed
            async def event_callback(event: Dict[str, Any]) -> None:
                if self._progress_callback:
                    # 直接转发 WorkflowEngine 的事件
                    await self._progress_callback(event)

            # 使用流式执行
            self._is_executing = True
            result = await self._workflow_engine.execute_with_streaming(
                workflow_definition=self._builder.draft_workflow,
                initial_context=params or {},
                event_callback=event_callback,
            )
            self._is_executing = False

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
            self._is_executing = False
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
        if not self._is_executing:
            return OperationResult(success=False, message="没有正在执行的工作流")

        # TODO: 实现暂停逻辑
        return OperationResult(success=True, message="执行已暂停")

    async def resume_execution(self) -> OperationResult:
        """恢复执行"""
        # TODO: 实现恢复逻辑
        return OperationResult(success=True, message="执行已恢复")

    async def stop_execution(self) -> OperationResult:
        """停止执行"""
        if self._workflow_engine:
            # TODO: 实现停止逻辑
            self._is_executing = False
        return OperationResult(success=True, message="执行已停止")

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
            # 使用统一的路径获取方法
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
                    except:
                        pass

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

    def get_execution_status(self) -> Dict[str, Any]:
        """获取执行状态"""
        return {
            "is_executing": self._is_executing,
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
