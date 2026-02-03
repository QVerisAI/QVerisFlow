# Agent 核心层设计（基于 SDK）

## 1. SDK 选型分析

### 1.1 主流 Agent SDK 对比

| SDK | 优点 | 缺点 | 适用场景 |
|-----|------|------|----------|
| **LangGraph** | 灵活的状态机、支持多 LLM、社区活跃 | 学习曲线略陡 | 复杂工作流 |
| **OpenAI Agents SDK** | 官方支持、简单易用 | 绑定 OpenAI | 简单 Agent |
| **Claude Agent SDK** | 最佳实践内置、工具丰富 | 绑定 Anthropic | Claude 应用 |
| **AutoGen** | 多 Agent 对话、微软支持 | 较重 | 研究场景 |

### 1.2 推荐方案：LangGraph + 扩展

**选择 LangGraph 作为核心引擎的理由：**

1. **多 LLM 支持** - 通过 LangChain 支持 OpenRouter、OpenAI、Anthropic 等
2. **项目现有集成** - 已有 `UnifiedLLMClient` 和 LangChain 集成
3. **灵活的状态管理** - 支持复杂工作流和条件分支
4. **内置持久化** - 支持 checkpoint，便于错误恢复
5. **可扩展性强** - 可以轻松扩展我们的定制功能

```
┌─────────────────────────────────────────────────────────────┐
│                    架构层次                                  │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  ┌──────────────────────────────────────────────────────┐   │
│  │            我们的扩展层 (Extension Layer)             │   │
│  │  • 声明式配置（YAML Agent/Workflow 定义）             │   │
│  │  • 工作空间管理（文件系统交互）                        │   │
│  │  • 三层验证机制                                       │   │
│  │  • @工具名 / #上下文名 引用解析                       │   │
│  │  • 智能演化（Meta Agent、Prompt 优化）                │   │
│  └──────────────────────────────────────────────────────┘   │
│                            │                                 │
│                            ▼                                 │
│  ┌──────────────────────────────────────────────────────┐   │
│  │               LangGraph (核心引擎)                    │   │
│  │  • 状态机工作流                                       │   │
│  │  • 条件分支                                          │   │
│  │  • 并行执行                                          │   │
│  │  • Checkpoint 持久化                                 │   │
│  └──────────────────────────────────────────────────────┘   │
│                            │                                 │
│                            ▼                                 │
│  ┌──────────────────────────────────────────────────────┐   │
│  │               LangChain (LLM 抽象)                    │   │
│  │  • 多 Provider 支持                                   │   │
│  │  • Tool/Function Calling                             │   │
│  │  • Message 管理                                       │   │
│  └──────────────────────────────────────────────────────┘   │
│                            │                                 │
│                            ▼                                 │
│  ┌──────────────────────────────────────────────────────┐   │
│  │             UnifiedLLMClient (现有)                   │   │
│  │  • OpenRouter / OpenAI / Anthropic                   │   │
│  │  • Token 追踪                                         │   │
│  │  • 降级策略                                           │   │
│  └──────────────────────────────────────────────────────┘   │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

---

## 2. 核心循环实现（基于 LangGraph）

### 2.1 Agent 状态定义

```python
# etf_common/agent_framework/core/agent_state.py

from typing import Dict, Any, Optional, List, Annotated
from typing_extensions import TypedDict
from langgraph.graph.message import add_messages
from datetime import datetime


class AgentState(TypedDict):
    """
    Agent 状态定义（LangGraph 兼容）
    
    使用 TypedDict 以便 LangGraph 进行状态管理
    """
    
    # === 基本信息 ===
    agent_id: str
    task_id: str
    
    # === 消息历史（LangGraph 标准）===
    messages: Annotated[list, add_messages]
    
    # === 执行状态 ===
    phase: str  # gather_context, take_action, verify_work, complete, failed
    iteration: int
    max_iterations: int
    
    # === 上下文 ===
    gathered_context: str
    context_compressed: bool
    
    # === 验证 ===
    verification_passed: bool
    verification_feedback: str
    verification_score: float
    
    # === 结果 ===
    result: Optional[Dict[str, Any]]
    output_files: List[str]
    
    # === 草稿 ===
    draft_versions: List[str]
    current_draft: str
    
    # === 错误 ===
    errors: List[Dict[str, Any]]
    
    # === 工作空间路径 ===
    workspace_path: str


def create_initial_state(
    agent_id: str,
    task_id: str,
    workspace_path: str,
    max_iterations: int = 10
) -> AgentState:
    """创建初始状态"""
    return AgentState(
        agent_id=agent_id,
        task_id=task_id,
        messages=[],
        phase="gather_context",
        iteration=0,
        max_iterations=max_iterations,
        gathered_context="",
        context_compressed=False,
        verification_passed=False,
        verification_feedback="",
        verification_score=0.0,
        result=None,
        output_files=[],
        draft_versions=[],
        current_draft="",
        errors=[],
        workspace_path=workspace_path
    )
```

### 2.2 Agent 核心循环（LangGraph 实现）

```python
# etf_common/agent_framework/core/agent_graph.py

from typing import Dict, Any, Optional, Callable, Literal
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage

from .agent_state import AgentState, create_initial_state
from ..workspace import AgentWorkspace
from ..definitions import AgentDefinition
from ..verification import BaseVerifier


class AgentGraphBuilder:
    """
    Agent 图构建器
    
    使用 LangGraph 构建标准的 Agent 核心循环：
    gather_context → take_action → verify_work → (repeat or complete)
    """
    
    def __init__(
        self,
        definition: AgentDefinition,
        workspace: AgentWorkspace,
        llm_client: Any,
        verifier: Optional[BaseVerifier] = None,
        tools: list = None
    ):
        self.definition = definition
        self.workspace = workspace
        self.llm_client = llm_client
        self.verifier = verifier
        self.tools = tools or []
        
        # 获取 LangChain 客户端
        self.langchain_llm = llm_client.get_langchain_client()
        
        # 如果有工具，绑定到 LLM
        if self.tools:
            self.langchain_llm = self.langchain_llm.bind_tools(self.tools)
    
    def build(self) -> StateGraph:
        """
        构建 Agent 图
        
        Returns:
            可编译的 StateGraph
        """
        # 创建图
        graph = StateGraph(AgentState)
        
        # 添加节点
        graph.add_node("gather_context", self._gather_context_node)
        graph.add_node("take_action", self._take_action_node)
        graph.add_node("verify_work", self._verify_work_node)
        graph.add_node("handle_error", self._handle_error_node)
        
        # 设置入口
        graph.set_entry_point("gather_context")
        
        # 添加边
        graph.add_edge("gather_context", "take_action")
        graph.add_edge("take_action", "verify_work")
        
        # 条件边：验证后决定下一步
        graph.add_conditional_edges(
            "verify_work",
            self._should_continue,
            {
                "continue": "gather_context",  # 验证失败，继续迭代
                "complete": END,                # 验证通过，结束
                "max_iterations": END,          # 达到最大迭代
                "error": "handle_error"         # 错误处理
            }
        )
        
        graph.add_edge("handle_error", END)
        
        return graph
    
    def compile(self, checkpointer=None):
        """
        编译图
        
        Args:
            checkpointer: 检查点存储（用于持久化和恢复）
            
        Returns:
            编译后的可执行图
        """
        graph = self.build()
        
        # 默认使用内存检查点
        if checkpointer is None:
            checkpointer = MemorySaver()
        
        return graph.compile(checkpointer=checkpointer)
    
    # ========== 节点实现 ==========
    
    async def _gather_context_node(self, state: AgentState) -> Dict[str, Any]:
        """
        收集上下文节点
        
        职责：
        1. 读取任务描述
        2. 调用搜索工具收集信息
        3. 处理之前的验证反馈
        """
        workspace = AgentWorkspace.from_path(state["workspace_path"])
        
        # 读取任务
        task, input_data = workspace.read_task()
        
        # 构建收集上下文的 prompt
        context_prompt = self._build_context_prompt(
            task=task,
            input_data=input_data,
            previous_feedback=state.get("verification_feedback", "")
        )
        
        # 调用 LLM（可能会调用工具）
        messages = [
            SystemMessage(content=self.definition.background_instruction.to_prompt()),
            HumanMessage(content=context_prompt)
        ]
        
        response = await self.langchain_llm.ainvoke(messages)
        
        # 处理工具调用结果
        gathered_context = self._process_tool_calls(response, workspace)
        
        # 保存上下文
        workspace.save_gathered_context(gathered_context)
        
        return {
            "gathered_context": gathered_context,
            "messages": [response],
            "iteration": state["iteration"] + 1
        }
    
    async def _take_action_node(self, state: AgentState) -> Dict[str, Any]:
        """
        执行动作节点
        
        职责：
        1. 基于上下文生成输出
        2. 写入草稿
        3. 调用必要的工具
        """
        workspace = AgentWorkspace.from_path(state["workspace_path"])
        
        # 构建执行 prompt
        action_prompt = self._build_action_prompt(
            context=state["gathered_context"],
            previous_draft=state.get("current_draft", "")
        )
        
        # 调用 LLM
        messages = state["messages"] + [
            HumanMessage(content=action_prompt)
        ]
        
        response = await self.langchain_llm.ainvoke(messages)
        
        # 解析结果
        result = self._parse_response(response.content)
        
        # 写入草稿
        draft_version = len(state["draft_versions"]) + 1
        draft_path = f"scratch/draft_v{draft_version}.md"
        workspace.write_file(draft_path, response.content)
        
        return {
            "result": result,
            "current_draft": response.content,
            "draft_versions": state["draft_versions"] + [draft_path],
            "messages": [response]
        }
    
    async def _verify_work_node(self, state: AgentState) -> Dict[str, Any]:
        """
        验证工作节点
        
        职责：
        1. 规则验证
        2. LLM 评判（可选）
        3. 记录验证结果
        """
        if self.verifier is None:
            return {
                "verification_passed": True,
                "verification_feedback": "",
                "verification_score": 1.0,
                "phase": "complete"
            }
        
        # 执行验证
        result = await self.verifier.verify(
            output=state["result"],
            context={
                "gathered_context": state["gathered_context"],
                "iteration": state["iteration"]
            }
        )
        
        workspace = AgentWorkspace.from_path(state["workspace_path"])
        workspace.log_action("verification", {
            "passed": result.passed,
            "score": result.score,
            "feedback": result.feedback
        })
        
        return {
            "verification_passed": result.passed,
            "verification_feedback": result.feedback,
            "verification_score": result.score,
            "phase": "complete" if result.passed else "gather_context"
        }
    
    async def _handle_error_node(self, state: AgentState) -> Dict[str, Any]:
        """错误处理节点"""
        workspace = AgentWorkspace.from_path(state["workspace_path"])
        workspace.log_error("Agent execution failed", {
            "errors": state["errors"]
        })
        
        return {
            "phase": "failed"
        }
    
    # ========== 条件判断 ==========
    
    def _should_continue(
        self, 
        state: AgentState
    ) -> Literal["continue", "complete", "max_iterations", "error"]:
        """判断是否继续迭代"""
        
        if state.get("errors") and len(state["errors"]) >= 3:
            return "error"
        
        if state["iteration"] >= state["max_iterations"]:
            return "max_iterations"
        
        if state["verification_passed"]:
            return "complete"
        
        return "continue"
    
    # ========== 辅助方法 ==========
    
    def _build_context_prompt(
        self,
        task: str,
        input_data: Dict[str, Any],
        previous_feedback: str
    ) -> str:
        """构建上下文收集 prompt"""
        prompt_parts = [
            f"## 任务\n{task}",
            f"\n## 输入数据\n{input_data}"
        ]
        
        if previous_feedback:
            prompt_parts.append(
                f"\n## 之前的验证反馈（请据此补充信息）\n{previous_feedback}"
            )
        
        prompt_parts.append(
            "\n请收集完成任务所需的上下文信息。"
            "如果需要搜索或查询数据，请使用可用的工具。"
        )
        
        return "\n".join(prompt_parts)
    
    def _build_action_prompt(
        self,
        context: str,
        previous_draft: str
    ) -> str:
        """构建执行动作 prompt"""
        prompt_parts = [
            f"## 收集的上下文\n{context}",
            f"\n## 输出要求\n{self.definition.output_instruction.to_prompt()}"
        ]
        
        if previous_draft:
            prompt_parts.append(
                f"\n## 之前的草稿（请改进）\n{previous_draft}"
            )
        
        prompt_parts.append(
            f"\n## 任务\n{self.definition.user_instruction.task_description}"
        )
        
        return "\n".join(prompt_parts)
    
    def _process_tool_calls(self, response, workspace) -> str:
        """处理工具调用结果"""
        # 如果有工具调用，提取结果
        if hasattr(response, 'tool_calls') and response.tool_calls:
            results = []
            for tool_call in response.tool_calls:
                results.append(f"## {tool_call['name']}\n{tool_call.get('output', '')}")
            return "\n\n".join(results)
        
        return response.content
    
    def _parse_response(self, content: str) -> Dict[str, Any]:
        """解析响应内容"""
        import json
        
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            # 尝试提取 JSON
            if "```json" in content:
                start = content.find("```json") + 7
                end = content.find("```", start)
                if end > start:
                    return json.loads(content[start:end].strip())
            
            # 返回原始内容
            return {"raw_content": content}
```

### 2.3 简化的 Agent 封装

```python
# etf_common/agent_framework/core/base_agent.py

from typing import Dict, Any, Optional, List
from datetime import datetime

from .agent_graph import AgentGraphBuilder
from .agent_state import create_initial_state
from ..workspace import AgentWorkspace, WorkspaceConfig
from ..definitions import AgentDefinition
from ..verification import BaseVerifier
from ..tools import ToolRegistry


class BaseAgent:
    """
    Agent 基类（基于 LangGraph）
    
    封装 LangGraph 图，提供简洁的 API
    """
    
    def __init__(
        self,
        definition: AgentDefinition,
        workspace: AgentWorkspace,
        tool_registry: ToolRegistry,
        verifier: Optional[BaseVerifier] = None,
        llm_client: Any = None,
        config: Optional[Dict[str, Any]] = None
    ):
        self.definition = definition
        self.workspace = workspace
        self.tool_registry = tool_registry
        self.verifier = verifier
        self.llm_client = llm_client
        self.config = config or {}
        
        # 获取工具
        self.tools = self._get_tools()
        
        # 构建图
        self.graph_builder = AgentGraphBuilder(
            definition=definition,
            workspace=workspace,
            llm_client=llm_client,
            verifier=verifier,
            tools=self.tools
        )
        
        # 编译图
        self.graph = self.graph_builder.compile()
    
    async def run(
        self,
        task_description: str = None,
        input_data: Dict[str, Any] = None
    ) -> Dict[str, Any]:
        """
        运行 Agent
        
        Args:
            task_description: 任务描述（可选，可从工作空间读取）
            input_data: 输入数据
            
        Returns:
            执行结果
        """
        # 写入任务（如果提供）
        if task_description:
            self.workspace.write_task(task_description, input_data)
        
        # 创建初始状态
        initial_state = create_initial_state(
            agent_id=self.definition.agent_id,
            task_id=self.workspace.config.task_id,
            workspace_path=str(self.workspace.root),
            max_iterations=self.definition.model_config.max_iterations
        )
        
        # 执行图
        config = {"configurable": {"thread_id": self.workspace.config.task_id}}
        
        final_state = await self.graph.ainvoke(initial_state, config)
        
        # 写入最终结果
        if final_state.get("result"):
            self.workspace.write_result(final_state["result"])
        
        return {
            "agent_id": self.definition.agent_id,
            "task_id": self.workspace.config.task_id,
            "success": final_state.get("verification_passed", False),
            "result": final_state.get("result"),
            "iterations": final_state.get("iteration", 0),
            "output_files": final_state.get("output_files", [])
        }
    
    def _get_tools(self) -> list:
        """获取 Agent 可用的工具"""
        tools = []
        
        for tool_ref in self.definition.tool_references:
            if tool_ref.enabled:
                tool = self.tool_registry.get_langchain_tool(tool_ref.tool_id)
                if tool:
                    tools.append(tool)
        
        return tools
    
    async def resume(self, checkpoint_id: str) -> Dict[str, Any]:
        """
        从检查点恢复执行
        
        LangGraph 内置支持，无需额外实现
        """
        config = {"configurable": {"thread_id": checkpoint_id}}
        final_state = await self.graph.ainvoke(None, config)
        return final_state
```

---

## 3. 与现有代码的集成

### 3.1 复用现有 BaseAgent 模式

您现有的 `multi_agent_v2/agents/base_agent.py` 已经有很好的结构，可以作为 LangGraph 节点的实现：

```python
# etf_common/agent_framework/core/langgraph_adapter.py

from typing import Dict, Any
from langgraph.graph import StateGraph

from etf_event.event_impact_analysis.multi_agent_v2.agents.base_agent import (
    BaseAgent as ExistingBaseAgent
)


def adapt_existing_agent(
    agent: ExistingBaseAgent,
    state_key: str = "result"
) -> callable:
    """
    将现有 Agent 适配为 LangGraph 节点
    
    Args:
        agent: 现有的 Agent 实例
        state_key: 输出状态的 key
        
    Returns:
        LangGraph 节点函数
    """
    async def node_func(state: Dict[str, Any]) -> Dict[str, Any]:
        # 调用现有 Agent 的 execute 方法
        result = await agent.execute(**state.get("input", {}))
        
        return {state_key: result}
    
    return node_func


# 使用示例
def create_analysis_graph(
    verification_agent: ExistingBaseAgent,
    investment_agent: ExistingBaseAgent,
    signal_classifier: ExistingBaseAgent
):
    """创建分析工作流图"""
    
    graph = StateGraph(dict)
    
    # 添加现有 Agent 作为节点
    graph.add_node(
        "verification",
        adapt_existing_agent(verification_agent, "verification_result")
    )
    graph.add_node(
        "investment",
        adapt_existing_agent(investment_agent, "investment_result")
    )
    graph.add_node(
        "classification",
        adapt_existing_agent(signal_classifier, "classification_result")
    )
    
    # 定义流程
    graph.set_entry_point("classification")
    graph.add_edge("classification", "verification")
    graph.add_edge("verification", "investment")
    
    return graph.compile()
```

### 3.2 渐进式迁移策略

```python
# 阶段 1: 保持现有 Agent 不变，用 LangGraph 编排
# 阶段 2: 逐步将 Agent 迁移到新的定义格式
# 阶段 3: 添加工作空间和验证功能

# 阶段 1 示例：使用 LangGraph 编排现有 Agent
from langgraph.graph import StateGraph, END
from etf_event.event_impact_analysis.multi_agent_v2.workflow.orchestrator import (
    MultiAgentOrchestrator
)


class HybridOrchestrator:
    """混合编排器：结合现有 Agent 和新框架"""
    
    def __init__(self):
        # 现有的编排器
        self.legacy_orchestrator = MultiAgentOrchestrator()
        
        # 新的 LangGraph 工作流
        self.graph = self._build_enhanced_graph()
    
    def _build_enhanced_graph(self):
        """构建增强的工作流图"""
        
        graph = StateGraph(dict)
        
        # 使用现有 Agent
        graph.add_node("analyze", self._legacy_analyze_node)
        
        # 添加新功能：工作空间持久化
        graph.add_node("persist", self._persist_to_workspace)
        
        # 添加新功能：验证
        graph.add_node("verify", self._verify_result)
        
        graph.set_entry_point("analyze")
        graph.add_edge("analyze", "persist")
        graph.add_edge("persist", "verify")
        graph.add_conditional_edges(
            "verify",
            lambda s: "end" if s.get("verified") else "analyze",
            {"end": END, "analyze": "analyze"}
        )
        
        return graph.compile()
    
    async def _legacy_analyze_node(self, state):
        """调用现有分析逻辑"""
        result = await self.legacy_orchestrator.analyze_comment(
            comment_content=state["content"],
            comment_id=state.get("comment_id"),
            **state.get("extra", {})
        )
        return {"analysis_result": result}
    
    async def _persist_to_workspace(self, state):
        """持久化到工作空间"""
        from ..workspace import AgentWorkspace, WorkspaceConfig
        
        workspace = AgentWorkspace(WorkspaceConfig(
            base_path="./workspaces",
            task_id=state.get("task_id", "default")
        ))
        
        workspace.write_result(state["analysis_result"].model_dump())
        
        return {"workspace_path": str(workspace.root)}
    
    async def _verify_result(self, state):
        """验证结果"""
        # 使用新的验证器
        from ..verification import create_default_verifier
        
        verifier = create_default_verifier()
        result = await verifier.verify(state["analysis_result"])
        
        return {
            "verified": result.passed,
            "verification_feedback": result.feedback
        }
```

---

## 4. 工具集成

### 4.1 将现有工具转换为 LangChain Tools

```python
# etf_common/agent_framework/tools/langchain_adapter.py

from typing import Dict, Any, Callable
from langchain_core.tools import Tool, StructuredTool
from pydantic import BaseModel, Field

from .tool_definition import ToolDefinition
from .tool_registry import ToolRegistry


class LangChainToolAdapter:
    """将框架工具转换为 LangChain Tool"""
    
    @staticmethod
    def adapt(
        definition: ToolDefinition,
        implementation: Callable
    ) -> StructuredTool:
        """
        将工具定义转换为 LangChain StructuredTool
        
        Args:
            definition: 工具定义
            implementation: 工具实现函数
            
        Returns:
            LangChain StructuredTool
        """
        # 动态创建输入 Schema
        input_model = LangChainToolAdapter._create_input_model(
            definition.tool_id,
            definition.input_schema
        )
        
        return StructuredTool(
            name=definition.tool_id,
            description=definition.description,
            args_schema=input_model,
            func=implementation,
            coroutine=implementation if asyncio.iscoroutinefunction(implementation) else None
        )
    
    @staticmethod
    def _create_input_model(name: str, schema: Dict[str, Any]) -> type:
        """从 JSON Schema 创建 Pydantic 模型"""
        from pydantic import create_model
        
        fields = {}
        properties = schema.get("properties", {})
        required = schema.get("required", [])
        
        type_mapping = {
            "string": str,
            "integer": int,
            "number": float,
            "boolean": bool,
            "array": list,
            "object": dict
        }
        
        for field_name, field_def in properties.items():
            field_type = type_mapping.get(field_def.get("type"), Any)
            is_required = field_name in required
            
            if is_required:
                fields[field_name] = (
                    field_type,
                    Field(description=field_def.get("description", ""))
                )
            else:
                fields[field_name] = (
                    Optional[field_type],
                    Field(default=None, description=field_def.get("description", ""))
                )
        
        return create_model(f"{name}Input", **fields)


# 扩展 ToolRegistry
class EnhancedToolRegistry(ToolRegistry):
    """增强的工具注册表，支持 LangChain"""
    
    def get_langchain_tool(self, tool_id: str) -> Optional[StructuredTool]:
        """获取 LangChain 格式的工具"""
        definition = self.get(tool_id)
        implementation = self._implementations.get(tool_id)
        
        if definition and implementation:
            return LangChainToolAdapter.adapt(definition, implementation)
        
        return None
    
    def get_all_langchain_tools(self) -> list:
        """获取所有 LangChain 工具"""
        tools = []
        for tool_id in self._tools:
            tool = self.get_langchain_tool(tool_id)
            if tool:
                tools.append(tool)
        return tools
```

---

## 5. 使用示例

```python
# 完整使用示例

from etf_common.agent_framework import (
    BaseAgent,
    AgentDefinition,
    AgentWorkspace,
    WorkspaceConfig,
    EnhancedToolRegistry,
    CompositeVerifier,
    RuleBasedVerifier,
    JSONFormatRule,
    RequiredFieldsRule
)
from etf_common.llm import UnifiedLLMClient


async def main():
    # 1. 初始化 LLM 客户端
    llm_client = UnifiedLLMClient(
        provider="openrouter",
        model_name="deepseek/deepseek-v3",
        client_type="langchain"
    )
    
    # 2. 初始化工具注册表
    tool_registry = EnhancedToolRegistry()
    # 注册工具...
    
    # 3. 加载 Agent 定义
    agent_def = AgentDefinition.from_yaml_file("agents/financial_analyst.yaml")
    
    # 4. 创建工作空间
    workspace = AgentWorkspace(WorkspaceConfig(
        base_path="./workspaces",
        task_id="analysis_001"
    ))
    
    # 5. 创建验证器
    verifier = CompositeVerifier([
        RuleBasedVerifier([
            JSONFormatRule(),
            RequiredFieldsRule(["company_name", "summary", "investment_opinion"])
        ])
    ])
    
    # 6. 创建并运行 Agent
    agent = BaseAgent(
        definition=agent_def,
        workspace=workspace,
        tool_registry=tool_registry,
        verifier=verifier,
        llm_client=llm_client
    )
    
    result = await agent.run(
        task_description="分析贵州茅台的投资价值",
        input_data={"company": "贵州茅台", "ticker": "600519.SH"}
    )
    
    print(f"分析完成: {result['success']}")
    print(f"迭代次数: {result['iterations']}")
    
    if result['success']:
        print(f"结果: {result['result']}")


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
```

---

## 6. 总结

### 6.1 SDK 优先的好处

| 方面 | 自研 | SDK 优先 |
|------|------|----------|
| 开发时间 | 长 | 短 |
| 维护成本 | 高 | 低 |
| 稳定性 | 需要验证 | 已验证 |
| 功能完整性 | 需要自建 | 内置 |
| 社区支持 | 无 | 有 |
| 升级 | 自己做 | 跟随 SDK |

### 6.2 我们要做的核心工作

1. **声明式配置层** - YAML 定义 Agent/Workflow（已设计）
2. **工作空间管理** - 文件系统交互（已设计）
3. **验证机制** - 三层验证（已设计）
4. **引用解析** - @工具名 / #上下文名（已设计）
5. **智能演化** - Meta Agent、Prompt 优化（已设计）
6. **适配器** - 连接 LangGraph 和我们的扩展

### 6.3 推荐的技术栈

```
我们的扩展层
     │
     ▼
LangGraph (工作流引擎)
     │
     ▼
LangChain (LLM 抽象 + Tools)
     │
     ▼
UnifiedLLMClient (现有)
     │
     ▼
OpenRouter / OpenAI / Anthropic
```

---

## 7. 外部检查点存储

### 7.1 设计目标

默认情况下，LangGraph 使用 `MemorySaver` 进行内存检查点存储。为了支持分布式部署和持久化恢复，框架支持外部检查点存储。

| 存储类型 | 适用场景 | 特点 |
|----------|----------|------|
| Memory | 单实例、开发测试 | 简单、快速、不持久化 |
| Redis | 分布式、多实例共享 | 快速读写、可设置 TTL |
| PostgreSQL | 长期持久化、审计 | 持久化、可查询、合规 |

### 7.2 检查点存储实现

检查点存储位于 `storage/checkpointers/` 模块：

```
storage/checkpointers/
├── __init__.py          # 导出接口
├── base.py              # BaseCheckpointSaver 基类
├── memory_saver.py      # 内存检查点（开发/测试）
├── redis_saver.py       # Redis 检查点（分布式）
├── postgres_saver.py    # PostgreSQL 检查点（持久化）
├── file_saver.py        # 文件系统检查点（本地）
└── factory.py           # CheckpointerFactory 工厂类
```

```python
# storage/checkpointers/factory.py

from storage.config import CheckpointerType, CheckpointStorageConfig
from storage.redis_client import RedisClient
from storage.database import AsyncDatabaseManager

class CheckpointerFactory:
    """检查点存储工厂"""
    
    @staticmethod
    def create(
        config: CheckpointStorageConfig,
        redis_client: Optional[RedisClient] = None,
        db_manager: Optional[AsyncDatabaseManager] = None,
    ) -> BaseCheckpointSaver:
        """
        根据配置创建检查点存储
        
        Args:
            config: 检查点存储配置
            redis_client: Redis 客户端（Redis 类型必需）
            db_manager: 数据库管理器（PostgreSQL 类型必需）
            
        Returns:
            检查点存储实例
        """
        if config.type == CheckpointerType.MEMORY:
            return SimpleMemoryCheckpointSaver()
        
        elif config.type == CheckpointerType.REDIS:
            if redis_client is None:
                raise ValueError("RedisClient must be provided")
            return RedisCheckpointSaver(
                redis_client=redis_client,
                prefix=config.redis_prefix,
                ttl=config.redis_ttl,
            )
        
        elif config.type == CheckpointerType.POSTGRESQL:
            if db_manager is None:
                raise ValueError("AsyncDatabaseManager must be provided")
            return PostgresCheckpointSaver(
                db_manager=db_manager,
                table_name=config.postgres_table,
            )
        
        elif config.type == CheckpointerType.FILE:
            return FileCheckpointSaver(path=config.file_path)
        
        else:
            raise ValueError(f"Unsupported type: {config.type}")
    
    @staticmethod
    def from_env(
        redis_client: Optional[RedisClient] = None,
        db_manager: Optional[AsyncDatabaseManager] = None,
    ) -> BaseCheckpointSaver:
        """从环境变量创建检查点存储"""
        from storage.config import StorageConfig
        config = StorageConfig.from_env().checkpoint
        return CheckpointerFactory.create(config, redis_client, db_manager)
```

### 7.3 配置示例

```yaml
# config/agent_config.yaml

# Redis 检查点存储
checkpoint:
  type: redis
  redis_url: redis://localhost:6379
  prefix: "my_agent:"
  ttl: 3600  # 1 小时

# 或使用 PostgreSQL
checkpoint:
  type: postgres
  connection_string: postgresql://user:pass@localhost/db
  table_name: agent_checkpoints
```

### 7.4 使用外部检查点存储

```python
from core import BaseAgent
from storage.checkpointers import CheckpointerFactory
from storage.config import CheckpointStorageConfig, CheckpointerType
from storage.redis_client import RedisClient

# 方式 1：使用工厂和配置
config = CheckpointStorageConfig(
    type=CheckpointerType.REDIS,
    redis_prefix="my_agent:",
    redis_ttl=7200,
)
redis_client = await RedisClient.get_instance(host="localhost", port=6379)
checkpointer = CheckpointerFactory.create(config, redis_client=redis_client)

# 方式 2：从环境变量创建
checkpointer = CheckpointerFactory.from_env(redis_client=redis_client)

# 创建 Agent 时传入
agent = BaseAgent(
    definition=agent_def,
    workspace=workspace,
    checkpointer=checkpointer,
)

# Agent 的状态将自动持久化到 Redis
result = await agent.run("执行任务")

# 从检查点恢复
recovered_agent = BaseAgent(
    definition=agent_def,
    workspace=workspace,
    checkpointer=checkpointer,
)
result = await recovered_agent.resume(thread_id="task_123")
```

### 7.5 检查点数据库表结构

```sql
-- PostgreSQL 检查点表
CREATE TABLE agent_checkpoints (
    id SERIAL PRIMARY KEY,
    thread_id VARCHAR(255) NOT NULL,
    checkpoint_id VARCHAR(255) NOT NULL,
    parent_id VARCHAR(255),
    checkpoint_data JSONB NOT NULL,
    metadata JSONB,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    
    UNIQUE(thread_id, checkpoint_id)
);

CREATE INDEX idx_checkpoints_thread_id ON agent_checkpoints(thread_id);
CREATE INDEX idx_checkpoints_created_at ON agent_checkpoints(created_at);
```
