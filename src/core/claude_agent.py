"""
Claude 原生 Agent

基于 Claude Agent SDK 实现的执行器，作为 BaseAgent 的替代选项。
适用于需要充分利用 Claude SDK 特性的场景。

设计原则：
1. 继承 BaseAgent，保持接口兼容性
2. 使用 Claude SDK 替代 LangGraph 执行
3. 充分利用 MCP 工具和 Hooks 机制
"""

from typing import Dict, Any, Optional, List
from datetime import datetime

from .base_agent import BaseAgent
from ..workspace import AgentWorkspace, WorkspaceConfig
from ..definitions import AgentDefinition
from ..verification import BaseVerifier
from src.utils.logger import get_logger

logger = get_logger()


class ClaudeNativeAgent(BaseAgent):
    """
    Claude 原生 Agent

    使用 Claude Agent SDK 的原生执行流程，而不是 LangGraph。

    优势：
    - 更简洁的执行流程
    - 原生 MCP 工具支持
    - Hooks 机制
    - 更好的 Claude 模型适配

    适用场景：
    - 单一 Agent 任务
    - 需要使用 MCP 生态工具
    - 需要细粒度的执行控制（Hooks）

    用法：
    ```python
    from core import ClaudeNativeAgent
    from definitions import AgentDefinition
    from workspace import AgentWorkspace, WorkspaceConfig

    # 创建 Agent
    agent = ClaudeNativeAgent(
        definition=agent_def,
        workspace=workspace,
        tool_registry=tool_registry,
        verifier=verifier,
        mcp_servers={"calculator": calculator_server},
        hooks={"PreToolUse": [check_tool_hook]}
    )

    # 运行
    result = await agent.run(
        task_description="计算投资回报率",
        input_data={"principal": 100000, "rate": 0.05}
    )
    ```
    """

    def __init__(
        self,
        definition: AgentDefinition,
        workspace: AgentWorkspace,
        tool_registry: Any = None,
        verifier: Optional[BaseVerifier] = None,
        llm_client: Any = None,
        config: Optional[Dict[str, Any]] = None,
        # Claude SDK 特有参数
        mcp_servers: Optional[Dict[str, Any]] = None,
        hooks: Optional[Dict[str, List[Any]]] = None,
        use_sdk_execution: bool = True,
    ):
        """
        初始化 Claude 原生 Agent

        Args:
            definition: Agent 定义
            workspace: 工作空间
            tool_registry: 工具注册表
            verifier: 验证器
            llm_client: LLM 客户端（可选，会自动创建 Claude SDK 客户端）
            config: 额外配置
            mcp_servers: MCP 服务器配置
            hooks: Hooks 配置
            use_sdk_execution: 是否使用 SDK 原生执行（vs LangGraph）
        """
        self.use_sdk_execution = use_sdk_execution
        self.mcp_servers = mcp_servers or {}
        self.hooks = hooks or {}

        # 如果未提供 llm_client，创建 Claude SDK 客户端
        if llm_client is None and use_sdk_execution:
            from ..utils.claude_client import ClaudeSDKClient

            llm_client = ClaudeSDKClient(
                model_name=definition.llm_config.model_name,
                temperature=definition.llm_config.temperature,
                max_tokens=definition.llm_config.max_tokens,
                mcp_servers=self.mcp_servers,
                hooks=self.hooks,
            )

        # 调用父类初始化
        super().__init__(
            definition=definition,
            workspace=workspace,
            tool_registry=tool_registry,
            verifier=verifier,
            llm_client=llm_client,
            config=config,
        )

        logger.info(f"✅ Claude 原生 Agent 初始化: {definition.agent_id}")

    async def run(
        self,
        task_description: Optional[str] = None,
        input_data: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        运行 Agent（使用 Claude SDK 原生执行）

        Args:
            task_description: 任务描述
            input_data: 输入数据

        Returns:
            执行结果
        """
        if self.use_sdk_execution:
            return await self._run_with_sdk(task_description, input_data)
        else:
            # 回退到 LangGraph 执行
            return await super().run(task_description, input_data)

    async def _run_with_sdk(
        self,
        task_description: Optional[str],
        input_data: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """
        使用 Claude SDK 原生执行

        实现标准的核心循环：
        gather_context → take_action → verify_work → repeat
        """
        from ..utils.claude_client import ClaudeSDKClient

        # 写入任务
        if task_description:
            self.workspace.write_task(task_description, input_data)

        # 读取任务
        task, input_data = self.workspace.read_task()

        # 初始化状态
        iteration = 0
        max_iterations = self.definition.llm_config.max_iterations
        verification_passed = False
        result = None
        verification_feedback = ""

        try:
            while iteration < max_iterations and not verification_passed:
                iteration += 1
                logger.info(f"🔄 迭代 {iteration}/{max_iterations}")

                # ========== Phase 1: Gather Context ==========
                context_prompt = self._build_context_prompt(
                    task=task, input_data=input_data, feedback=verification_feedback
                )

                gathered_context = await self._call_claude(context_prompt)
                self.workspace.save_gathered_context(gathered_context)
                self.workspace.log_action(
                    "gather_context",
                    {"iteration": iteration, "context_length": len(gathered_context)},
                )

                # ========== Phase 2: Take Action ==========
                action_prompt = self._build_action_prompt(
                    context=gathered_context, task=task
                )

                action_result = await self._call_claude(action_prompt)

                # 保存草稿
                draft_path = self.workspace.write_draft(action_result, iteration)
                self.workspace.log_action(
                    "take_action", {"iteration": iteration, "draft_path": draft_path}
                )

                # 解析结果
                result = self._parse_result(action_result)

                # ========== Phase 3: Verify Work ==========
                if self.verifier:
                    verification_result = await self.verifier.verify(
                        output=result,
                        context={
                            "gathered_context": gathered_context,
                            "iteration": iteration,
                        },
                    )

                    verification_passed = verification_result.passed
                    verification_feedback = verification_result.feedback

                    self.workspace.log_action(
                        "verify_work",
                        {
                            "iteration": iteration,
                            "passed": verification_passed,
                            "score": verification_result.score,
                            "feedback": verification_feedback,
                        },
                    )

                    if not verification_passed:
                        logger.warning(f"⚠️ 验证未通过: {verification_feedback}")
                else:
                    # 无验证器，直接通过
                    verification_passed = True
                    verification_feedback = "No verifier configured"

            # 写入最终结果
            if result:
                self.workspace.write_result(result)

            success = verification_passed or iteration >= max_iterations

            return {
                "agent_id": self.definition.agent_id,
                "task_id": self.workspace.config.task_id,
                "success": success,
                "result": result,
                "iterations": iteration,
                "verification_passed": verification_passed,
                "verification_feedback": verification_feedback,
                "execution_mode": "claude_sdk_native",
            }

        except Exception as e:
            logger.error(f"❌ Agent 执行失败: {e}")
            self.workspace.log_error(f"执行失败: {str(e)}")

            return {
                "agent_id": self.definition.agent_id,
                "task_id": self.workspace.config.task_id,
                "success": False,
                "error": str(e),
                "iterations": iteration,
                "execution_mode": "claude_sdk_native",
            }

    async def _call_claude(self, prompt: str) -> str:
        """
        调用 Claude SDK

        Args:
            prompt: 提示词

        Returns:
            响应文本
        """
        from ..utils.claude_client import ClaudeSDKClient

        if not isinstance(self.llm_client, ClaudeSDKClient):
            # 回退到标准调用
            return await self.llm_client.ainvoke(prompt)

        # 使用 Claude SDK
        return await self.llm_client.ainvoke(prompt)

    def _build_context_prompt(
        self, task: str, input_data: Optional[Dict[str, Any]], feedback: str
    ) -> str:
        """构建上下文收集 prompt"""
        system_prompt = self.definition.build_system_prompt()

        parts = [
            f"# System\n{system_prompt}",
            f"\n# Task\n{task}",
        ]

        if input_data:
            import json

            parts.append(
                f"\n# Input Data\n```json\n{json.dumps(input_data, indent=2)}\n```"
            )

        if feedback:
            parts.append(f"\n# Previous Feedback\n{feedback}\n\n请根据反馈补充信息。")

        parts.append(
            "\n# Instructions\n请收集完成任务所需的上下文信息。如需数据，使用可用的工具。"
        )

        return "\n".join(parts)

    def _build_action_prompt(self, context: str, task: str) -> str:
        """构建执行动作 prompt"""
        output_prompt = self.definition.build_output_prompt()
        user_prompt = self.definition.build_user_prompt()

        parts = [
            f"# Gathered Context\n{context}",
            f"\n# Task\n{task}",
            f"\n# Output Requirements\n{output_prompt}",
            f"\n# Instructions\n{user_prompt}",
        ]

        return "\n".join(parts)

    def _parse_result(self, content: str) -> Dict[str, Any]:
        """解析结果"""
        import json

        try:
            return json.loads(content)
        except json.JSONDecodeError:
            # 尝试提取 JSON
            if "```json" in content:
                start = content.find("```json") + 7
                end = content.find("```", start)
                if end > start:
                    try:
                        return json.loads(content[start:end].strip())
                    except json.JSONDecodeError:
                        pass

            return {"raw_content": content}

    # ========== Claude SDK 特有功能 ==========

    def add_hook(self, event: str, hook_matcher):
        """
        动态添加 Hook

        Args:
            event: 事件名称
            hook_matcher: Hook 匹配器
        """
        if event not in self.hooks:
            self.hooks[event] = []
        self.hooks[event].append(hook_matcher)

        # 更新 llm_client
        from ..utils.claude_client import ClaudeSDKClient

        if isinstance(self.llm_client, ClaudeSDKClient):
            self.llm_client.add_hook(event, hook_matcher)

        logger.info(f"✅ 添加 Hook: {event}")

    def add_mcp_server(self, name: str, server_config: Dict[str, Any]):
        """
        动态添加 MCP 服务器

        Args:
            name: 服务器名称
            server_config: 服务器配置
        """
        self.mcp_servers[name] = server_config

        # 更新 llm_client
        from ..utils.claude_client import ClaudeSDKClient

        if isinstance(self.llm_client, ClaudeSDKClient):
            self.llm_client.add_mcp_server(name, server_config)

        logger.info(f"✅ 添加 MCP 服务器: {name}")

    @classmethod
    def from_yaml(
        cls,
        yaml_path: str,
        workspace_config: WorkspaceConfig,
        tool_registry: Any = None,
        verifier: Optional[BaseVerifier] = None,
        mcp_servers: Optional[Dict[str, Any]] = None,
        hooks: Optional[Dict[str, List[Any]]] = None,
        use_sdk_execution: bool = True,
    ) -> "ClaudeNativeAgent":
        """
        从 YAML 文件创建 Claude 原生 Agent

        Args:
            yaml_path: YAML 文件路径
            workspace_config: 工作空间配置
            tool_registry: 工具注册表
            verifier: 验证器
            mcp_servers: MCP 服务器配置
            hooks: Hooks 配置
            use_sdk_execution: 是否使用 SDK 原生执行

        Returns:
            ClaudeNativeAgent 实例
        """
        definition = AgentDefinition.from_yaml_file(yaml_path)
        workspace = AgentWorkspace(workspace_config)

        return cls(
            definition=definition,
            workspace=workspace,
            tool_registry=tool_registry,
            verifier=verifier,
            mcp_servers=mcp_servers,
            hooks=hooks,
            use_sdk_execution=use_sdk_execution,
        )
