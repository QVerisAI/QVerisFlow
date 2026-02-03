# Claude Agent SDK 深度集成方案

## 📋 目录

1. [概述与目标](#1-概述与目标)
2. [设计哲学与核心原则](#2-设计哲学与核心原则)
3. [整体架构设计](#3-整体架构设计)
4. [四层集成架构详解](#4-四层集成架构详解)
5. [扩展性设计](#5-扩展性设计)
6. [稳定性与可靠性](#6-稳定性与可靠性)
7. [使用指南与最佳实践](#7-使用指南与最佳实践)
8. [API 参考](#8-api-参考)
9. [迁移指南](#9-迁移指南)
10. [未来规划](#10-未来规划)

---

## 1. 概述与目标

### 1.1 集成背景

agent_framework 是一个企业级的智能 Agent 开发框架，基于 LangGraph 构建，支持声明式配置、工作空间管理、三层验证机制和智能演化。Claude Agent SDK 是 Anthropic 官方发布的 Agent 开发工具包，提供了 MCP 工具协议、Hooks 机制等强大能力。

本集成方案旨在**将 Claude Agent SDK 的优势融入现有框架**，在保持原有架构稳定性的同时，扩展框架能力边界。

### 1.2 集成目标

| 目标 | 描述 | 优先级 |
|------|------|--------|
| **无缝兼容** | 现有代码无需修改即可继续使用 | P0 |
| **渐进增强** | 用户可按需选择集成层级 | P0 |
| **能力扩展** | 引入 MCP 生态、Hooks 机制 | P0 |
| **高扩展性** | 支持自定义适配器、插件机制 | P1 |
| **高稳定性** | 完善的错误处理、降级策略 | P1 |
| **高可用性** | 清晰的 API、丰富的文档 | P1 |

### 1.3 集成后的能力矩阵

| 能力维度 | 集成前 | 集成后 |
|----------|--------|--------|
| **LLM 后端** | UnifiedLLMClient (多 Provider) | ✅ + ClaudeSDKClient (原生优化) |
| **工具生态** | ToolRegistry (自建) | ✅ + MCP 社区工具生态 |
| **执行引擎** | LangGraph 状态图 | ✅ + Claude SDK 原生执行 (可选) |
| **执行控制** | Verifier (结果验证) | ✅ + Hooks (过程控制) |
| **调试能力** | 工作空间文件系统 | ✅ + Claude Code 日志 |
| **适用场景** | 企业级复杂任务 | ✅ 从简单到复杂全覆盖 |

---

## 2. 设计哲学与核心原则

### 2.1 核心设计原则

#### 原则一：渐进增强 (Progressive Enhancement)

```
不破坏 → 可选增强 → 按需升级
```

现有代码保持完全兼容，新能力作为可选增强项，用户根据需求渐进升级。

#### 原则二：关注点分离 (Separation of Concerns)

```
基础设施层 → 工具层 → 核心层 → 编排层
```

每层独立演进，通过明确的接口契约连接，降低耦合度。

#### 原则三：适配器模式 (Adapter Pattern)

```
外部系统 ←→ 适配器 ←→ 框架内部
```

所有外部依赖通过适配器接入，便于替换和扩展。

#### 原则四：优雅降级 (Graceful Degradation)

```
首选方案 → 备选方案 → 最小功能集
```

当首选方案不可用时，自动降级到备选方案，确保系统可用性。

### 2.2 与 Anthropic 官方原则的对齐

| Anthropic 原则 | 我们的实现 |
|---------------|-----------|
| 给 Agent 一台计算机 | 文件系统 + Bash + 代码执行作为核心工具 |
| 文件系统是交互总线 | 工作空间管理，所有数据通过文件传递 |
| Coding Agent 是基础 | 支持结构化内容生成和文件操作 |
| 清晰的验证规则 | 三层验证机制 (规则 + 视觉 + LLM) |

---

## 3. 整体架构设计

### 3.1 架构总览

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           应用层 (Applications)                              │
│  ┌──────────────────┐  ┌──────────────────┐  ┌──────────────────────────┐  │
│  │  金融分析 Agent   │  │  研报生成 Agent   │  │   自定义领域 Agent       │  │
│  └────────┬─────────┘  └────────┬─────────┘  └────────────┬─────────────┘  │
│           │                     │                          │                │
├───────────┼─────────────────────┼──────────────────────────┼────────────────┤
│           │           编排层 (Orchestration)                │                │
│           ▼                     ▼                          ▼                │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌────────────┐  │   │
│  │  │WorkflowEngine│  │SmartRouter │  │SubAgentMgr │  │HooksManager│  │   │
│  │  │ 工作流引擎   │  │ 智能路由器  │  │子Agent管理  │  │ Hooks管理  │  │   │
│  │  └─────────────┘  └─────────────┘  └─────────────┘  └────────────┘  │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                   │                                         │
├───────────────────────────────────┼─────────────────────────────────────────┤
│                         核心层 (Core)                                        │
│                                   ▼                                         │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │               执行器选择 (Executor Selector)                         │   │
│  │  ┌───────────────────────────┐  ┌───────────────────────────────┐  │   │
│  │  │      BaseAgent            │  │     ClaudeNativeAgent         │  │   │
│  │  │   (LangGraph 执行)         │  │    (SDK 原生执行)              │  │   │
│  │  │  • 复杂工作流              │  │  • 简单任务                    │  │   │
│  │  │  • 多 Agent 协作           │  │  • MCP 生态工具                │  │   │
│  │  │  • 自定义执行图            │  │  • Hooks 细粒度控制            │  │   │
│  │  └───────────────────────────┘  └───────────────────────────────┘  │   │
│  │                                                                     │   │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────────────┐│   │
│  │  │ Workspace   │  │ Verifier    │  │ AgentState (LangGraph)      ││   │
│  │  │ 工作空间管理 │  │ 三层验证器  │  │ 状态管理                    ││   │
│  │  └─────────────┘  └─────────────┘  └─────────────────────────────┘│   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                   │                                         │
├───────────────────────────────────┼─────────────────────────────────────────┤
│                         工具层 (Tools)                                       │
│                                   ▼                                         │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────────────┐ │   │
│  │  │ToolRegistry │◀─┤MCPToolAdapter├──┤   外部 MCP 服务器            │ │   │
│  │  │ 工具注册表   │  │ MCP适配器   │  │  (社区工具生态)              │ │   │
│  │  └─────────────┘  └─────────────┘  └─────────────────────────────┘ │   │
│  │        │                                                            │   │
│  │        ▼                                                            │   │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────────────┐ │   │
│  │  │ 文件系统工具 │  │  Bash 工具  │  │      业务工具               │ │   │
│  │  │  ls/read/   │  │  execute    │  │  财务/公告/研报搜索         │ │   │
│  │  │  write/edit │  │             │  │                             │ │   │
│  │  └─────────────┘  └─────────────┘  └─────────────────────────────┘ │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                   │                                         │
├───────────────────────────────────┼─────────────────────────────────────────┤
│                       定义层 (Definitions)                                   │
│                                   ▼                                         │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────────────┐ │   │
│  │  │AgentDef     │  │ToolDef     │  │WorkflowDef                 │ │   │
│  │  │ Agent定义   │  │ 工具定义    │  │ 工作流定义                  │ │   │
│  │  └─────────────┘  └─────────────┘  └─────────────────────────────┘ │   │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────────────┐ │   │
│  │  │PromptStruct │  │RefResolver │  │SchemaValidator             │ │   │
│  │  │三层Prompt   │  │引用解析器   │  │ Schema验证                  │ │   │
│  │  └─────────────┘  └─────────────┘  └─────────────────────────────┘ │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                   │                                         │
├───────────────────────────────────┼─────────────────────────────────────────┤
│                      基础设施层 (Infrastructure)                             │
│                                   ▼                                         │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │  ┌─────────────────────────────────────────────────────────────┐   │   │
│  │  │               LLM 客户端抽象 (LLMClientInterface)            │   │   │
│  │  │  ┌───────────────────┐      ┌───────────────────────────┐  │   │   │
│  │  │  │ UnifiedLLMClient  │      │    ClaudeSDKClient        │  │   │   │
│  │  │  │ (LangChain 集成)  │      │   (SDK 原生适配)           │  │   │   │
│  │  │  │  • OpenRouter     │      │  • MCP 原生支持            │  │   │   │
│  │  │  │  • OpenAI         │      │  • Hooks 原生支持          │  │   │   │
│  │  │  │  • Anthropic      │      │  • 流式响应优化            │  │   │   │
│  │  │  └───────────────────┘      └───────────────────────────┘  │   │   │
│  │  └─────────────────────────────────────────────────────────────┘   │   │
│  │                                                                     │   │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────────────┐│   │
│  │  │ LangGraph   │  │ PostgreSQL  │  │     OSS + Redis             ││   │
│  │  │ 状态图引擎   │  │ 结构化存储   │  │   文件存储 + 缓存            ││   │
│  │  └─────────────┘  └─────────────┘  └─────────────────────────────┘│   │
│  └─────────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 3.2 数据流图

```
用户请求
    │
    ▼
┌─────────────────┐
│  SmartRouter    │ ──────────────────────────┐
│  (智能路由)      │                           │
└────────┬────────┘                           │
         │                                    │
         ▼ 选择执行器                          │
    ┌────┴────┐                               │
    ▼         ▼                               │
┌────────┐ ┌──────────────┐                   │
│BaseAgent│ │ClaudeNative │                   │
│(LangGraph│ │Agent(SDK)  │                   │
└────┬────┘ └──────┬──────┘                   │
     │             │                          │
     └──────┬──────┘                          │
            ▼                                  │
    ┌───────────────┐                         │
    │  核心循环      │                         │
    │ gather_context│◀─────────────────────────┘
    │ take_action   │         ↑ 反馈
    │ verify_work   │─────────┘
    └───────┬───────┘
            │
            ▼
    ┌───────────────┐
    │   Workspace   │
    │  (文件系统)    │
    └───────┬───────┘
            │
            ▼
      执行结果输出
```

### 3.3 组件依赖图

```
                    ┌──────────────────┐
                    │  ClaudeNativeAgent│
                    └────────┬─────────┘
                             │ extends
                             ▼
                    ┌──────────────────┐
                    │    BaseAgent     │
                    └────────┬─────────┘
                             │ uses
              ┌──────────────┼──────────────┐
              │              │              │
              ▼              ▼              ▼
     ┌────────────┐ ┌────────────┐ ┌────────────┐
     │AgentGraph  │ │ Workspace  │ │ Verifier   │
     │Builder     │ │            │ │            │
     └──────┬─────┘ └────────────┘ └────────────┘
            │
            │ uses
            ▼
     ┌────────────┐        ┌──────────────┐
     │LLMClient   │◀───────│ClaudeSDKClient│
     │Interface   │        └──────────────┘
     └──────┬─────┘
            │ impl
            ▼
     ┌────────────┐
     │UnifiedLLM  │
     │Client      │
     └────────────┘
```

---

## 4. 四层集成架构详解

### 4.1 层级总览

| 层级 | 组件 | 职责 | 扩展点 |
|------|------|------|--------|
| **L1 基础设施层** | `ClaudeSDKClient` | SDK 客户端适配 | 新 LLM Provider |
| **L2 工具层** | `MCPToolAdapter` | MCP 工具集成 | 新工具协议 |
| **L3 核心层** | `ClaudeNativeAgent` | SDK 原生执行 | 新执行策略 |
| **L4 编排层** | `HooksManager` | Hooks 机制管理 | 新 Hook 类型 |

### 4.2 L1 基础设施层 - ClaudeSDKClient

#### 职责

- 封装 Claude Agent SDK 客户端
- 提供与 `UnifiedLLMClient` 兼容的接口
- 支持 MCP 服务器和 Hooks 配置

#### 核心接口

```python
class LLMClientInterface(Protocol):
    """LLM 客户端接口协议"""
    
    async def ainvoke(self, messages: List[Message]) -> str:
        """异步调用"""
        ...
    
    async def astream(self, messages: List[Message]) -> AsyncIterator[str]:
        """流式调用"""
        ...
    
    def get_langchain_client(self) -> Any:
        """获取 LangChain 兼容客户端"""
        ...


class ClaudeSDKClient(LLMClientInterface):
    """Claude SDK 客户端适配器"""
    
    def __init__(
        self,
        model_name: str = "claude-sonnet-4-20250514",
        temperature: float = 0.3,
        max_tokens: int = 4096,
        mcp_servers: Optional[Dict[str, Any]] = None,
        hooks: Optional[Dict[str, List[Any]]] = None,
        api_key: Optional[str] = None,
    ):
        ...
```

#### 降级策略

```python
class LLMClientFactory:
    """LLM 客户端工厂，支持优雅降级"""
    
    @staticmethod
    def create(
        preferred: str = "claude_sdk",
        fallback: str = "unified"
    ) -> LLMClientInterface:
        """创建 LLM 客户端，支持降级"""
        
        if preferred == "claude_sdk":
            try:
                from claude_agent_sdk import ClaudeSDKClient
                return ClaudeSDKClient(...)
            except ImportError:
                logger.warning("Claude SDK 未安装，降级到 UnifiedLLMClient")
        
        return UnifiedLLMClient(provider="anthropic")
```

### 4.3 L2 工具层 - MCPToolAdapter

#### 职责

- 桥接 MCP 工具生态和 ToolRegistry
- 支持外部 MCP 服务器和 SDK 内置工具
- 提供工具双向同步

#### 工具集成流程

```
外部 MCP 服务器                    SDK 内置工具
      │                                │
      ▼                                ▼
┌─────────────────────────────────────────────┐
│             MCPToolAdapter                   │
│  ┌─────────────┐     ┌─────────────────┐   │
│  │import_from_ │     │register_sdk_    │   │
│  │mcp_server() │     │server()         │   │
│  └──────┬──────┘     └────────┬────────┘   │
│         │                     │             │
│         └──────────┬──────────┘             │
│                    ▼                        │
│         ┌──────────────────┐               │
│         │ _convert_to_     │               │
│         │ ToolDefinition() │               │
│         └────────┬─────────┘               │
│                  │                          │
└──────────────────┼──────────────────────────┘
                   ▼
          ┌───────────────┐
          │ ToolRegistry  │
          │   (注册)       │
          └───────────────┘
```

#### 工具分类映射

```python
MCP_CATEGORY_MAPPING = {
    "filesystem": ToolCategory.FILE_SYSTEM,
    "database": ToolCategory.DATA_ACCESS,
    "search": ToolCategory.DOCUMENT_SEARCH,
    "calculator": ToolCategory.GENERAL,
    # 可扩展...
}
```

### 4.4 L3 核心层 - ClaudeNativeAgent

#### 职责

- 提供 Claude SDK 原生执行流程
- 继承 BaseAgent 保持接口兼容
- 支持运行时切换执行模式

#### 执行模式对比

| 特性 | LangGraph 执行 | SDK 原生执行 |
|------|---------------|-------------|
| **执行流程** | 状态图驱动 | 简化循环 |
| **状态管理** | 完整状态图 | 最小状态 |
| **检查点** | LangGraph MemorySaver | SDK 内置 |
| **MCP 工具** | 通过适配器 | 原生支持 |
| **Hooks** | 不支持 | 原生支持 |
| **适用场景** | 复杂工作流 | 简单任务 |

#### 执行模式选择策略

```python
class ExecutionModeSelector:
    """执行模式选择器"""
    
    @staticmethod
    def select(
        task_complexity: str,
        need_mcp_tools: bool,
        need_hooks: bool,
        multi_agent: bool
    ) -> str:
        """根据任务特征选择执行模式"""
        
        # 需要多 Agent 协作 → LangGraph
        if multi_agent:
            return "langgraph"
        
        # 需要 Hooks 或 MCP 工具 → SDK
        if need_hooks or need_mcp_tools:
            return "sdk"
        
        # 复杂任务 → LangGraph
        if task_complexity == "high":
            return "langgraph"
        
        # 默认 → SDK (更轻量)
        return "sdk"
```

### 4.5 L4 编排层 - HooksManager

#### 职责

- 管理 Hooks 的注册和生命周期
- 提供预定义的常用 Hooks
- 与验证层集成

#### Hook 事件生命周期

```
请求开始
    │
    ▼
┌─────────────────┐
│  PreToolUse     │ ← 工具执行前检查
│  (验证/限流)     │
└────────┬────────┘
         │ allow/deny
         ▼
┌─────────────────┐
│   工具执行       │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  PostToolUse    │ ← 工具执行后处理
│  (日志/审计)     │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  PreResponse    │ ← 响应前检查
│  (内容过滤)      │
└────────┬────────┘
         │
         ▼
响应返回
```

#### 预定义 Hooks 清单

| Hook 名称 | 事件 | 功能 |
|----------|------|------|
| `block_dangerous_commands` | PreToolUse | 阻止危险 Shell 命令 |
| `log_tool_usage` | PreToolUse | 记录工具调用日志 |
| `rate_limit_tool` | PreToolUse | 工具调用频率限制 |
| `validate_tool_input` | PreToolUse | 输入参数验证 |
| `integrate_with_verifier` | PostToolUse | 集成验证器检查输出 |

---

## 5. 扩展性设计

### 5.1 插件架构

```python
class PluginInterface(Protocol):
    """插件接口协议"""
    
    @property
    def name(self) -> str:
        """插件名称"""
        ...
    
    @property
    def version(self) -> str:
        """插件版本"""
        ...
    
    def initialize(self, context: PluginContext) -> None:
        """初始化插件"""
        ...
    
    def shutdown(self) -> None:
        """关闭插件"""
        ...


class PluginManager:
    """插件管理器"""
    
    def __init__(self):
        self._plugins: Dict[str, PluginInterface] = {}
    
    def register(self, plugin: PluginInterface) -> None:
        """注册插件"""
        self._plugins[plugin.name] = plugin
        plugin.initialize(self._create_context())
    
    def get(self, name: str) -> Optional[PluginInterface]:
        """获取插件"""
        return self._plugins.get(name)
```

### 5.2 适配器扩展点

```python
class LLMAdapterRegistry:
    """LLM 适配器注册表"""
    
    _adapters: Dict[str, Type[LLMClientInterface]] = {
        "claude_sdk": ClaudeSDKClient,
        "unified": UnifiedLLMClient,
    }
    
    @classmethod
    def register(cls, name: str, adapter_class: Type[LLMClientInterface]):
        """注册新的 LLM 适配器"""
        cls._adapters[name] = adapter_class
    
    @classmethod
    def create(cls, name: str, **kwargs) -> LLMClientInterface:
        """创建适配器实例"""
        if name not in cls._adapters:
            raise ValueError(f"Unknown adapter: {name}")
        return cls._adapters[name](**kwargs)


class ToolProtocolAdapter(Protocol):
    """工具协议适配器接口"""
    
    async def list_tools(self) -> List[ToolDefinition]:
        """列出可用工具"""
        ...
    
    async def execute(self, tool_id: str, params: Dict) -> Any:
        """执行工具"""
        ...


class MCPProtocolAdapter(ToolProtocolAdapter):
    """MCP 协议适配器"""
    ...


class OpenAPIAdapter(ToolProtocolAdapter):
    """OpenAPI 协议适配器 (可扩展)"""
    ...
```

### 5.3 配置驱动的扩展

```yaml
# config/claude_integration.yaml

llm_client:
  type: claude_sdk
  model: claude-sonnet-4-20250514
  fallback:
    type: unified
    provider: anthropic

mcp_servers:
  filesystem:
    type: stdio
    command: uvx
    args: ["mcp-server-filesystem", "/data"]
    auto_import: true
  
  calculator:
    type: sdk
    tools:
      - calculate
      - convert_units

hooks:
  security:
    enabled: true
    rules:
      - block_dangerous_commands
      - log_tool_usage
  
  rate_limit:
    enabled: true
    tools: ["*"]
    limit: 100
    window: 60

execution:
  default_mode: auto  # auto | sdk | langgraph
  mode_selection:
    complex_workflow: langgraph
    simple_task: sdk
    multi_agent: langgraph
```

---

## 6. 稳定性与可靠性

### 6.1 错误处理策略

```python
class ErrorHandler:
    """统一错误处理器"""
    
    @staticmethod
    async def handle_with_retry(
        func: Callable,
        max_retries: int = 3,
        backoff_factor: float = 2.0,
        fallback: Optional[Callable] = None
    ) -> Any:
        """带重试和降级的错误处理"""
        
        last_error = None
        
        for attempt in range(max_retries):
            try:
                return await func()
            except TransientError as e:
                # 暂时性错误，重试
                last_error = e
                wait_time = backoff_factor ** attempt
                await asyncio.sleep(wait_time)
            except PermanentError as e:
                # 永久性错误，直接降级
                last_error = e
                break
        
        # 所有重试失败，尝试降级
        if fallback:
            logger.warning(f"降级执行: {last_error}")
            return await fallback()
        
        raise last_error


class ErrorClassifier:
    """错误分类器"""
    
    TRANSIENT_ERRORS = [
        "RateLimitError",
        "ServiceUnavailable",
        "Timeout",
    ]
    
    PERMANENT_ERRORS = [
        "AuthenticationError",
        "InvalidRequest",
        "NotFound",
    ]
    
    @classmethod
    def classify(cls, error: Exception) -> str:
        """分类错误类型"""
        error_name = type(error).__name__
        
        if error_name in cls.TRANSIENT_ERRORS:
            return "transient"
        if error_name in cls.PERMANENT_ERRORS:
            return "permanent"
        
        return "unknown"
```

### 6.2 降级策略矩阵

| 组件 | 首选 | 降级方案 1 | 降级方案 2 |
|------|------|-----------|-----------|
| LLM 客户端 | ClaudeSDKClient | UnifiedLLMClient | 本地缓存响应 |
| 工具执行 | MCP 服务器 | 本地实现 | 跳过 (标记失败) |
| 执行模式 | SDK 原生 | LangGraph | 同步阻塞执行 |
| 验证器 | LLM Judge | 规则验证 | 跳过验证 |

### 6.3 健康检查

```python
class HealthChecker:
    """健康检查器"""
    
    async def check_all(self) -> Dict[str, HealthStatus]:
        """检查所有组件健康状态"""
        
        checks = {
            "llm_client": self._check_llm_client,
            "mcp_servers": self._check_mcp_servers,
            "tool_registry": self._check_tool_registry,
            "workspace": self._check_workspace,
        }
        
        results = {}
        for name, check_func in checks.items():
            try:
                status = await check_func()
                results[name] = status
            except Exception as e:
                results[name] = HealthStatus(
                    healthy=False,
                    message=str(e)
                )
        
        return results
    
    async def _check_llm_client(self) -> HealthStatus:
        """检查 LLM 客户端"""
        try:
            # 发送简单测试请求
            response = await self.llm_client.ainvoke([
                {"role": "user", "content": "ping"}
            ])
            return HealthStatus(healthy=True, latency_ms=...)
        except Exception as e:
            return HealthStatus(healthy=False, message=str(e))
```

### 6.4 监控与可观测性

```python
class MetricsCollector:
    """指标收集器"""
    
    def __init__(self):
        self.counters = {
            "llm_calls_total": Counter(),
            "tool_calls_total": Counter(),
            "errors_total": Counter(),
        }
        self.histograms = {
            "llm_latency_seconds": Histogram(),
            "tool_latency_seconds": Histogram(),
        }
    
    def record_llm_call(self, duration: float, success: bool):
        """记录 LLM 调用"""
        self.counters["llm_calls_total"].inc()
        self.histograms["llm_latency_seconds"].observe(duration)
        if not success:
            self.counters["errors_total"].inc()
    
    def export_prometheus(self) -> str:
        """导出 Prometheus 格式指标"""
        ...
```

---

## 7. 使用指南与最佳实践

### 7.1 快速开始

#### 最小示例 (30 秒)

```python
from utils.claude_client import ClaudeSDKClient
from core import BaseAgent

# 1. 创建 Claude 客户端
claude_client = ClaudeSDKClient(model_name="claude-sonnet-4-20250514")

# 2. 在现有 Agent 中使用
agent = BaseAgent(
    definition=your_agent_def,
    workspace=your_workspace,
    llm_client=claude_client  # 就这么简单！
)

# 3. 运行
result = await agent.run("执行任务")
```

#### 使用 MCP 工具 (1 分钟)

```python
from tools.mcp_adapter import mcp_tool
from definitions import ToolCategory

@mcp_tool(
    tool_id="my_tool",
    name="我的工具",
    description="工具描述",
    input_schema={"type": "object", "properties": {"param": {"type": "string"}}},
    category=ToolCategory.GENERAL
)
async def my_tool(param: str) -> dict:
    return {"result": f"处理: {param}"}
```

#### 使用 Hooks (2 分钟)

```python
from orchestration.hooks import HooksManager, HookEvent

hooks_mgr = HooksManager()

@hooks_mgr.register_hook(HookEvent.PRE_TOOL_USE, "my_tool")
async def validate_input(input_data, tool_use_id, context):
    if not input_data.get("tool_input", {}).get("param"):
        return {"hookSpecificOutput": {"permissionDecision": "deny"}}
    return {}

# 应用到 Agent
agent = ClaudeNativeAgent(..., hooks=hooks_mgr.get_hooks_config())
```

### 7.2 场景化最佳实践

#### 场景 1: 简单任务，追求速度

```python
# 推荐: SDK 原生执行
agent = ClaudeNativeAgent(
    definition=agent_def,
    workspace=workspace,
    use_sdk_execution=True,  # SDK 原生，更快
)
```

#### 场景 2: 复杂工作流，多 Agent 协作

```python
# 推荐: LangGraph 执行
agent = BaseAgent(
    definition=agent_def,
    workspace=workspace,
    llm_client=UnifiedLLMClient(),  # LangGraph + LangChain
)
```

#### 场景 3: 需要 MCP 生态工具

```python
# 推荐: SDK 原生 + MCP 适配器
mcp_adapter = MCPToolAdapter(tool_registry)
await mcp_adapter.import_from_mcp_server("filesystem", {...})

agent = ClaudeNativeAgent(
    definition=agent_def,
    workspace=workspace,
    mcp_servers=mcp_adapter.get_mcp_server_config(),
)
```

#### 场景 4: 需要细粒度执行控制

```python
# 推荐: SDK 原生 + Hooks
hooks = create_security_hooks()

agent = ClaudeNativeAgent(
    definition=agent_def,
    workspace=workspace,
    hooks=hooks,
    verifier=verifier,  # 结合验证器
)
```

### 7.3 性能优化建议

| 优化点 | 建议 | 预期效果 |
|--------|------|---------|
| **LLM 调用** | 启用流式响应 | 减少首字节延迟 |
| **工具执行** | 高频工具使用进程内 SDK 工具 | 减少 IPC 开销 |
| **MCP 服务器** | 低频工具使用外部服务器 | 减少内存占用 |
| **Hooks** | 仅在必要时启用 | 减少执行开销 |
| **验证** | 规则验证短路 LLM 验证 | 减少 LLM 调用 |

---

## 8. API 参考

### 8.1 ClaudeSDKClient

```python
class ClaudeSDKClient:
    """Claude SDK 客户端适配器"""
    
    def __init__(
        self,
        model_name: str = "claude-sonnet-4-20250514",
        api_key: Optional[str] = None,
        mcp_servers: Optional[Dict[str, Any]] = None,
        hooks: Optional[Dict[str, List[Any]]] = None,
        temperature: float = 0.3,
        max_tokens: int = 4096,
    ):
        """
        初始化 Claude SDK 客户端
        
        Args:
            model_name: 模型名称
            api_key: API Key (默认从环境变量读取)
            mcp_servers: MCP 服务器配置
            hooks: Hooks 配置
            temperature: 温度参数
            max_tokens: 最大输出 token 数
        """
        ...
    
    async def ainvoke(self, messages: List[Dict]) -> str:
        """异步调用"""
        ...
    
    async def astream(self, messages: List[Dict]) -> AsyncIterator[str]:
        """流式调用"""
        ...
    
    def get_langchain_client(self) -> Any:
        """获取 LangChain 兼容客户端"""
        ...
    
    def add_hook(self, event: str, hook) -> None:
        """动态添加 Hook"""
        ...
    
    def add_mcp_server(self, name: str, config: Dict) -> None:
        """动态添加 MCP 服务器"""
        ...
```

### 8.2 MCPToolAdapter

```python
class MCPToolAdapter:
    """MCP 工具适配器"""
    
    def __init__(self, tool_registry: ToolRegistry):
        """初始化适配器"""
        ...
    
    async def import_from_mcp_server(
        self,
        server_name: str,
        server_config: Dict[str, Any],
        category: ToolCategory = ToolCategory.GENERAL,
        auto_register: bool = True
    ) -> List[ToolDefinition]:
        """从外部 MCP 服务器导入工具"""
        ...
    
    def register_sdk_server(
        self,
        server_name: str,
        sdk_server: Any,
        category: ToolCategory = ToolCategory.GENERAL,
        auto_register: bool = True
    ) -> List[ToolDefinition]:
        """注册 SDK 内置 MCP 服务器"""
        ...
    
    def get_mcp_server_config(self) -> Dict[str, Any]:
        """获取 MCP 服务器配置"""
        ...
    
    def get_allowed_tools(self) -> List[str]:
        """获取允许的工具列表"""
        ...
```

### 8.3 ClaudeNativeAgent

```python
class ClaudeNativeAgent(BaseAgent):
    """Claude 原生 Agent"""
    
    def __init__(
        self,
        definition: AgentDefinition,
        workspace: AgentWorkspace,
        tool_registry: Any = None,
        verifier: Optional[BaseVerifier] = None,
        llm_client: Any = None,
        config: Optional[Dict[str, Any]] = None,
        mcp_servers: Optional[Dict[str, Any]] = None,
        hooks: Optional[Dict[str, List[Any]]] = None,
        use_sdk_execution: bool = True,
    ):
        """初始化 Claude 原生 Agent"""
        ...
    
    async def run(
        self,
        task_description: Optional[str] = None,
        input_data: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """运行 Agent"""
        ...
    
    def add_hook(self, event: str, hook_matcher) -> None:
        """动态添加 Hook"""
        ...
    
    def add_mcp_server(self, name: str, server_config: Dict) -> None:
        """动态添加 MCP 服务器"""
        ...
```

### 8.4 HooksManager

```python
class HooksManager:
    """Hooks 管理器"""
    
    def __init__(self):
        """初始化管理器"""
        ...
    
    def register_hook(
        self,
        event: HookEvent,
        matcher: str,
        hook_func: Optional[Callable] = None
    ) -> Optional[Callable]:
        """注册 Hook (支持装饰器)"""
        ...
    
    def get_hooks_config(self) -> Dict[str, List[Any]]:
        """获取 Hooks 配置"""
        ...
    
    def remove_hook(self, event: HookEvent, matcher: str) -> None:
        """移除 Hook"""
        ...
    
    def clear_hooks(self, event: Optional[HookEvent] = None) -> None:
        """清除 Hooks"""
        ...
```

---

## 9. 迁移指南

### 9.1 从 BaseAgent 迁移到 ClaudeNativeAgent

#### 步骤 1: 检查兼容性

```python
# 检查是否使用了 LangGraph 特有功能
uses_langgraph_features = (
    has_custom_state_graph or
    has_conditional_edges or
    has_multi_agent_coordination
)

if uses_langgraph_features:
    print("建议继续使用 BaseAgent")
else:
    print("可以迁移到 ClaudeNativeAgent")
```

#### 步骤 2: 最小改动迁移

```python
# Before
from core import BaseAgent

agent = BaseAgent(
    definition=agent_def,
    workspace=workspace,
    llm_client=unified_client,
)

# After (最小改动)
from core import ClaudeNativeAgent

agent = ClaudeNativeAgent(
    definition=agent_def,
    workspace=workspace,
    # llm_client 会自动创建 ClaudeSDKClient
)
```

#### 步骤 3: 添加新功能

```python
# 添加 MCP 工具
agent = ClaudeNativeAgent(
    ...,
    mcp_servers={"calculator": calculator_config},
)

# 添加 Hooks
agent = ClaudeNativeAgent(
    ...,
    hooks=create_security_hooks(),
)
```

### 9.2 迁移检查清单

- [ ] 确认不依赖 LangGraph 特有功能
- [ ] 测试现有工具在新环境下的兼容性
- [ ] 验证输出格式一致性
- [ ] 性能基准测试对比
- [ ] 错误处理逻辑验证

---

## 10. 未来规划

### 10.1 短期 (1-2 个月)

- [ ] 完善错误处理和边界情况
- [ ] 添加更多预定义 Hooks
- [ ] 性能基准测试和优化
- [ ] 补充单元测试和集成测试

### 10.2 中期 (3-6 个月)

- [ ] 支持更多 MCP 服务器
- [ ] 与 LangSmith/LangFuse 集成 (可观测性)
- [ ] 支持 Claude SDK 的子代理功能
- [ ] 开发可视化调试工具

### 10.3 长期 (6-12 个月)

- [ ] 基于 SDK 的分布式执行
- [ ] Agent 市场 (分享 MCP 工具和 Hooks)
- [ ] 自动化性能优化建议
- [ ] IDE 插件支持

---

## 附录

### A. 相关文档索引

| 文档 | 描述 |
|------|------|
| [00_overview.md](./00_overview.md) | 框架总体设计概述 |
| [01_core_agent.md](./01_core_agent.md) | Agent 核心层设计 |
| [05_tools.md](./05_tools.md) | 工具系统设计 |
| [06_orchestration.md](./06_orchestration.md) | 编排层设计 |
| [04_verification.md](./04_verification.md) | 验证机制设计 |

### B. 示例代码

完整示例请参见: `examples/claude_sdk_integration_example.py`

### C. 常见问题

**Q: 何时使用 SDK 执行 vs LangGraph 执行？**

A: 
- SDK 执行: 简单任务、需要 MCP 工具、需要 Hooks
- LangGraph 执行: 复杂工作流、多 Agent 协作、自定义执行图

**Q: MCP 工具和 ToolRegistry 工具有什么区别？**

A:
- MCP 工具: 来自 Claude SDK 生态，标准化接口
- ToolRegistry 工具: 框架内部工具，支持 @引用

两者可以结合使用，MCPToolAdapter 负责桥接。

**Q: Hooks 和 Verifier 有什么区别？**

A:
- Hooks: 执行过程中的控制点 (权限、限流、日志)
- Verifier: 最终输出的验证 (格式、内容质量)

两者配合使用效果最佳。

---

## 11. 当前实现状态

### 11.1 已实现的组件

| 组件 | 文件路径 | 状态 | 描述 |
|------|----------|------|------|
| **ClaudeClient** | `src/utils/claude_client.py` | ✅ 已实现 | Claude API 客户端封装 |
| **ClaudeAgent** | `src/core/claude_agent.py` | ✅ 已实现 | Claude 原生 Agent 实现 |
| **BaseAgent** | `src/core/base_agent.py` | ✅ 已实现 | LangGraph 基础 Agent |
| **ToolRegistry** | `src/tools/registry.py` | ✅ 已实现 | 工具注册表（含重试机制） |
| **AgentWorkspace** | `src/workspace/workspace.py` | ✅ 已实现 | 工作空间管理（含隔离机制） |

### 11.2 核心功能实现

```python
# src/utils/claude_client.py - Claude SDK 客户端

class ClaudeClient:
    """
    Claude API 客户端
    
    功能：
    - 消息生成
    - 工具调用
    - 流式响应
    - Token 追踪
    """
    
    def __init__(
        self,
        api_key: str = None,
        model: str = "claude-sonnet-4-20250514",
        max_tokens: int = 4096,
        temperature: float = 0.3,
    ):
        ...
    
    async def generate(
        self,
        messages: List[Dict],
        tools: List[Dict] = None,
        system: str = None,
    ) -> str:
        """生成响应"""
        ...
    
    async def stream(
        self,
        messages: List[Dict],
        tools: List[Dict] = None,
    ) -> AsyncIterator[str]:
        """流式生成"""
        ...
```

```python
# src/core/claude_agent.py - Claude 原生 Agent

class ClaudeAgent:
    """
    Claude 原生 Agent
    
    直接使用 Claude SDK 进行任务执行，
    支持工具调用和迭代优化。
    """
    
    def __init__(
        self,
        definition: AgentDefinition,
        workspace: AgentWorkspace,
        claude_client: ClaudeClient = None,
        tool_registry: ToolRegistry = None,
        verifier: BaseVerifier = None,
    ):
        ...
    
    async def run(
        self,
        task_description: str = None,
        input_data: Dict[str, Any] = None,
    ) -> Dict[str, Any]:
        """运行 Agent"""
        ...
```

### 11.3 与 LangGraph 的集成

框架支持两种执行模式：

1. **LangGraph 模式** (`BaseAgent`)
   - 适用于复杂工作流
   - 支持多 Agent 协作
   - 状态图驱动
   - 支持外部检查点存储（Redis/PostgreSQL）

2. **Claude 原生模式** (`ClaudeAgent`)
   - 适用于简单任务
   - 更轻量快速
   - 原生工具支持

### 11.4 使用示例

```python
# 使用 Claude 原生 Agent
from utils.claude_client import ClaudeClient
from core.claude_agent import ClaudeAgent

claude_client = ClaudeClient(model="claude-sonnet-4-20250514")

agent = ClaudeAgent(
    definition=agent_def,
    workspace=workspace,
    claude_client=claude_client,
    tool_registry=tool_registry,
)

result = await agent.run(
    task_description="分析贵州茅台的投资价值"
)
```

---

**版本**: v2.1.0  
**更新日期**: 2026-01-23  
**维护者**: agent_framework 团队
