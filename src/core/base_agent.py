"""
Agent 基类

封装 LangGraph 图，提供简洁的 API 用于执行 Agent。
"""

from typing import Dict, Any, Optional, List, Union
from datetime import datetime

from .agent_graph import AgentGraphBuilder
from .agent_state import create_initial_state
from ..storage.checkpointers import CheckpointerFactory, BaseCheckpointSaver
from ..storage.config import CheckpointStorageConfig as CheckpointerConfig
from ..workspace import AgentWorkspace, WorkspaceConfig
from ..definitions import AgentDefinition
from ..verification import BaseVerifier
from ..observability import get_tracer, get_metrics_collector
from ..storage.config import StorageConfig
from src.utils.logger import get_logger

logger = get_logger()


class BaseAgent:
    """
    Agent 基类（基于 LangGraph）

    封装 LangGraph 图，提供简洁的 API

    支持多种检查点存储后端：
    - memory: 内存存储（默认）
    - redis: Redis 存储（适合分布式部署）
    - postgresql: PostgreSQL 存储（持久化）
    - file: 文件系统存储
    """

    def __init__(
        self,
        definition: AgentDefinition,
        workspace: AgentWorkspace,
        tool_registry: Any = None,  # ToolRegistry
        verifier: Optional[BaseVerifier] = None,
        llm_client: Any = None,
        config: Optional[Dict[str, Any]] = None,
        checkpointer: Optional[BaseCheckpointSaver] = None,
        checkpointer_config: Optional[Union[CheckpointerConfig, Dict[str, Any]]] = None,
    ):
        """
        初始化 Agent

        Args:
            definition: Agent 定义
            workspace: 工作空间
            tool_registry: 工具注册表
            verifier: 验证器
            llm_client: LLM 客户端
            config: 额外配置
            checkpointer: 检查点存储实例（优先使用）
            checkpointer_config: 检查点存储配置（用于自动创建 checkpointer）
        """
        self.definition = definition
        self.workspace = workspace
        self.tool_registry = tool_registry
        self.verifier = verifier
        self.llm_client = llm_client
        self.config = config or {}
        self.checkpointer = checkpointer
        self.checkpointer_config = checkpointer_config

        # 获取工具
        self.tools = self._get_tools()

        # 构建图（传入 tool_registry 用于工具执行）
        self.graph_builder = AgentGraphBuilder(
            definition=definition,
            workspace=workspace,
            llm_client=llm_client,
            verifier=verifier,
            tools=self.tools,
            tool_registry=tool_registry,
        )

        # 编译图（支持外部检查点存储）
        self.graph = self.graph_builder.compile(
            checkpointer=checkpointer,
            checkpointer_config=checkpointer_config,
        )

    async def run(
        self,
        task_description: Optional[str] = None,
        input_data: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        运行 Agent

        Args:
            task_description: 任务描述（可选，可从工作空间读取）
            input_data: 输入数据

        Returns:
            执行结果
        """
        # 获取追踪器和指标收集器
        tracer = get_tracer()
        metrics = get_metrics_collector()

        start_time = datetime.now()

        # 使用追踪器包装执行
        with tracer.start_span(
            "agent_run",
            attributes={
                "agent.id": self.definition.agent_id,
                "agent.name": self.definition.name,
                "task.id": self.workspace.config.task_id,
                "workspace.path": str(self.workspace.root),
            },
        ) as span:
            # 写入任务（如果提供）
            if task_description:
                self.workspace.write_task(task_description, input_data)
                span.set_attribute("task.description_length", len(task_description))

            # 创建初始状态
            initial_state = create_initial_state(
                agent_id=self.definition.agent_id,
                task_id=self.workspace.config.task_id,
                workspace_path=str(self.workspace.root),
                max_iterations=self.definition.llm_config.max_iterations,
            )

            # 执行图
            config = {"configurable": {"thread_id": self.workspace.config.task_id}}

            try:
                span.add_event("graph_execution_started")
                final_state = await self.graph.ainvoke(initial_state, config)
                span.add_event("graph_execution_completed")

                # 写入最终结果
                if final_state.get("result"):
                    self.workspace.write_result(final_state["result"])

                # 记录成功指标
                duration_ms = (datetime.now() - start_time).total_seconds() * 1000
                metrics.counter("agent.runs.total").inc(
                    labels={"agent_id": self.definition.agent_id, "status": "success"}
                )
                metrics.histogram("agent.run.duration_ms").observe(
                    duration_ms, labels={"agent_id": self.definition.agent_id}
                )
                metrics.gauge("agent.iterations").set(
                    final_state.get("iteration", 0),
                    labels={"agent_id": self.definition.agent_id},
                )

                # 设置 span 属性
                span.set_attribute("result.success", True)
                span.set_attribute("result.iterations", final_state.get("iteration", 0))
                span.set_attribute(
                    "result.verification_score",
                    final_state.get("verification_score", 0.0),
                )

                return {
                    "agent_id": self.definition.agent_id,
                    "task_id": self.workspace.config.task_id,
                    "success": final_state.get("verification_passed", False),
                    "result": final_state.get("result"),
                    "iterations": final_state.get("iteration", 0),
                    "output_files": final_state.get("output_files", []),
                    "verification_score": final_state.get("verification_score", 0.0),
                    "duration_ms": duration_ms,
                }

            except Exception as e:
                logger.error(f"Agent 执行失败: {e}")
                self.workspace.log_error(f"执行失败: {str(e)}")

                # 记录失败指标
                duration_ms = (datetime.now() - start_time).total_seconds() * 1000
                metrics.counter("agent.runs.total").inc(
                    labels={"agent_id": self.definition.agent_id, "status": "failed"}
                )
                metrics.counter("agent.runs.errors").inc(
                    labels={
                        "agent_id": self.definition.agent_id,
                        "error_type": type(e).__name__,
                    }
                )

                # 设置 span 错误状态
                span.set_status("error", str(e))
                span.add_event(
                    "exception", {"message": str(e), "type": type(e).__name__}
                )

                return {
                    "agent_id": self.definition.agent_id,
                    "task_id": self.workspace.config.task_id,
                    "success": False,
                    "error": str(e),
                    "iterations": 0,
                    "output_files": [],
                    "duration_ms": duration_ms,
                }

    # 核心本地工具列表 - 这些工具始终可用，无论 tool_references 如何配置
    # 这确保了 Agent 能够与本地文件系统交互，而不是尝试通过远程 API 搜索文件系统工具
    CORE_LOCAL_TOOLS = [
        "file_ls",
        "file_read",
        "file_write",
        "file_edit",
        "file_append",
    ]

    def _get_tools(self) -> List[Any]:
        """
        获取 Agent 可用的工具

        工具加载策略：
        1. 始终加载核心本地工具（文件系统操作）
        2. 如果 definition.tool_references 非空，加载指定的工具
        3. 如果 definition.tool_references 为空，加载注册表中的所有工具

        Returns:
            LangChain 格式的工具列表
        """
        if not self.tool_registry:
            logger.debug("未配置工具注册表，Agent 将不使用任何工具")
            return []

        from ..tools import EnhancedToolRegistry

        # 包装为 EnhancedToolRegistry 以获取 LangChain 工具
        if not isinstance(self.tool_registry, EnhancedToolRegistry):
            enhanced_registry = EnhancedToolRegistry(self.tool_registry)
        else:
            enhanced_registry = self.tool_registry

        tools = []
        loaded_tool_ids = set()  # 跟踪已加载的工具，避免重复

        # === 始终加载核心本地工具（文件系统操作）===
        # 这确保 Agent 能够与本地文件系统交互
        logger.debug(f"加载核心本地工具: {self.CORE_LOCAL_TOOLS}")
        for tool_id in self.CORE_LOCAL_TOOLS:
            if tool_id not in loaded_tool_ids:
                try:
                    tool = enhanced_registry.get_langchain_tool(tool_id)
                    if tool:
                        tools.append(tool)
                        loaded_tool_ids.add(tool_id)
                        logger.debug(f"  ✓ 已加载核心工具: {tool_id}")
                    else:
                        # 核心工具未注册，尝试触发注册
                        logger.debug(f"  ⚠️ 核心工具 {tool_id} 未注册，跳过")
                except Exception as e:
                    logger.warning(f"  ✗ 加载核心工具 {tool_id} 失败: {e}")

        # 检查是否有明确指定的工具引用
        if self.definition.tool_references:
            # 策略 1: 加载指定的工具（排除已加载的核心工具）
            logger.debug(
                f"从 tool_references 加载 {len(self.definition.tool_references)} 个工具"
            )
            for tool_ref in self.definition.tool_references:
                if tool_ref.enabled and tool_ref.tool_id not in loaded_tool_ids:
                    try:
                        tool = enhanced_registry.get_langchain_tool(tool_ref.tool_id)
                        if tool:
                            tools.append(tool)
                            loaded_tool_ids.add(tool_ref.tool_id)
                            logger.debug(f"  ✓ 已加载工具: {tool_ref.tool_id}")
                        else:
                            logger.warning(
                                f"  ✗ 工具 {tool_ref.tool_id} 未在注册表中找到或无实现"
                            )
                    except Exception as e:
                        logger.warning(f"  ✗ 加载工具 {tool_ref.tool_id} 失败: {e}")
        else:
            # 策略 2: 加载注册表中的所有工具
            logger.debug("tool_references 为空，将加载注册表中的所有工具")
            try:
                all_tools = enhanced_registry.get_all_langchain_tools()
                for tool in all_tools:
                    tool_name = getattr(tool, "name", str(tool))
                    if tool_name not in loaded_tool_ids:
                        tools.append(tool)
                        loaded_tool_ids.add(tool_name)
                logger.debug(f"  已加载 {len(tools)} 个工具")
            except Exception as e:
                logger.warning(f"加载所有工具失败: {e}")

        # 日志总结
        if tools:
            tool_names = [getattr(t, "name", str(t)) for t in tools]
            logger.info(f"Agent 可用工具 ({len(tools)}): {tool_names}")
        else:
            logger.warning("Agent 没有加载任何工具，LLM 将无法调用工具")

        return tools

    async def resume(self, checkpoint_id: str) -> Dict[str, Any]:
        """
        从检查点恢复执行

        LangGraph 内置支持，无需额外实现

        Args:
            checkpoint_id: 检查点 ID

        Returns:
            执行结果
        """
        config = {"configurable": {"thread_id": checkpoint_id}}
        try:
            final_state = await self.graph.ainvoke(None, config)
            return {"success": True, "state": final_state}
        except Exception as e:
            logger.error(f"恢复执行失败: {e}")
            return {"success": False, "error": str(e)}

    @classmethod
    def from_yaml(
        cls,
        yaml_path: str,
        workspace_config: WorkspaceConfig,
        llm_client: Any,
        tool_registry: Any = None,
        verifier: Optional[BaseVerifier] = None,
        checkpointer: Optional[BaseCheckpointSaver] = None,
        checkpointer_config: Optional[Union[CheckpointerConfig, Dict[str, Any]]] = None,
    ) -> "BaseAgent":
        """
        从 YAML 文件创建 Agent

        Args:
            yaml_path: Agent 定义 YAML 文件路径
            workspace_config: 工作空间配置
            llm_client: LLM 客户端
            tool_registry: 工具注册表
            verifier: 验证器
            checkpointer: 检查点存储实例
            checkpointer_config: 检查点存储配置

        Returns:
            BaseAgent 实例
        """
        definition = AgentDefinition.from_yaml_file(yaml_path)
        workspace = AgentWorkspace(workspace_config)

        return cls(
            definition=definition,
            workspace=workspace,
            tool_registry=tool_registry,
            verifier=verifier,
            llm_client=llm_client,
            checkpointer=checkpointer,
            checkpointer_config=checkpointer_config,
        )

    @classmethod
    def from_env(
        cls,
        definition: AgentDefinition,
        workspace: AgentWorkspace,
        llm_client: Any,
        tool_registry: Any = None,
        verifier: Optional[BaseVerifier] = None,
    ) -> "BaseAgent":
        """
        使用环境变量配置创建 Agent

        从环境变量读取检查点存储配置：
        - CHECKPOINT_TYPE: memory, redis, postgresql
        - REDIS_URL: Redis 连接 URL
        - POSTGRES_URL: PostgreSQL 连接 URL

        Args:
            definition: Agent 定义
            workspace: 工作空间
            llm_client: LLM 客户端
            tool_registry: 工具注册表
            verifier: 验证器

        Returns:
            BaseAgent 实例
        """
        checkpointer = CheckpointerFactory.from_env()

        return cls(
            definition=definition,
            workspace=workspace,
            tool_registry=tool_registry,
            verifier=verifier,
            llm_client=llm_client,
            checkpointer=checkpointer,
        )

    @classmethod
    def from_storage_config(
        cls,
        definition: AgentDefinition,
        workspace: AgentWorkspace,
        llm_client: Any,
        storage_config: StorageConfig,
        tool_registry: Any = None,
        verifier: Optional[BaseVerifier] = None,
        redis_client: Optional[Any] = None,
        db_manager: Optional[Any] = None,
    ) -> "BaseAgent":
        """
        使用统一存储配置创建 Agent

        Args:
            definition: Agent 定义
            workspace: 工作空间
            llm_client: LLM 客户端
            storage_config: 统一存储配置
            tool_registry: 工具注册表
            verifier: 验证器
            redis_client: Redis 客户端（可选，用于依赖注入）
            db_manager: 数据库管理器（可选，用于依赖注入）

        Returns:
            BaseAgent 实例
        """
        from ..storage.checkpointers import CheckpointerFactory

        checkpointer = CheckpointerFactory.create_from_storage_config(
            storage_config,
            redis_client=redis_client,
            db_manager=db_manager,
        )

        return cls(
            definition=definition,
            workspace=workspace,
            tool_registry=tool_registry,
            verifier=verifier,
            llm_client=llm_client,
            checkpointer=checkpointer,
        )
