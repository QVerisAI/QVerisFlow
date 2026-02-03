# 🚀 Claude Agent SDK 集成 - 快速参考

> **agent_framework** 现已集成 **Claude Agent SDK**，结合两者优势！

## 🎯 一句话总结

**在保持 agent_framework 企业级架构优势的同时，充分利用 Claude SDK 的 MCP 生态和 Hooks 机制。**

---

## 📊 对比表格

### agent_framework vs Claude SDK vs **集成方案**

| 特性 | agent_framework | Claude SDK | **🎉 集成方案** |
|------|----------------|------------|--------------|
| **架构** | 分层架构 | 简洁 API | ✅ **保留分层架构** |
| **配置** | YAML 声明式 | 代码配置 | ✅ **YAML + 代码** |
| **工作空间** | 文件系统优先 | 无 | ✅ **保留工作空间** |
| **验证** | 三层验证 | 无 | ✅ **验证 + Hooks** |
| **工具** | ToolRegistry | MCP | ✅ **两者互通** |
| **执行** | LangGraph | SDK 原生 | ✅ **可选择** |
| **调试** | 工作空间日志 | Claude Code | ✅ **双重日志** |
| **生态** | 自建 | MCP 社区 | ✅ **两个生态** |

---

## 🏗️ 四层集成架构

```
┌─────────────────────────────────────────────────────┐
│  应用层: BaseAgent + ClaudeNativeAgent              │
├─────────────────────────────────────────────────────┤
│  编排层: SmartRouter + HooksManager                 │
├─────────────────────────────────────────────────────┤
│  核心层: AgentGraph + ClaudeAgent                   │
├─────────────────────────────────────────────────────┤
│  工具层: ToolRegistry ⇄ MCPToolAdapter              │
├─────────────────────────────────────────────────────┤
│  基础设施: UnifiedLLMClient + ClaudeSDKClient       │
└─────────────────────────────────────────────────────┘
```

---

## 🚀 快速开始（3 个级别）

### Level 1: 最小集成（30 秒）

```python
from utils.claude_client import ClaudeSDKClient

# 就改这一行！
agent = BaseAgent(..., llm_client=ClaudeSDKClient())
```

### Level 2: 添加 MCP 工具（2 分钟）

```python
from tools.mcp_adapter import mcp_tool

@mcp_tool(tool_id="my_tool", name="工具", ...)
async def my_tool(param: str):
    return {"result": param}
```

### Level 3: 完整功能（5 分钟）

```python
from core.claude_agent import ClaudeNativeAgent
from orchestration.hooks import create_security_hooks

agent = ClaudeNativeAgent(
    ...,
    mcp_servers=mcp_config,
    hooks=create_security_hooks(),
    use_sdk_execution=True  # SDK 原生执行
)
```

---

## 💡 何时使用？

### ✅ 推荐使用 Claude SDK 集成

- 需要使用 MCP 社区工具
- 希望更简洁的执行流程
- 需要细粒度的执行控制（Hooks）
- 新项目，想充分利用新特性

### ⚠️ 继续使用 LangGraph

- 复杂的多 Agent 协作
- 需要自定义执行图
- 现有项目，迁移成本高

### 🎯 两者结合（推荐！）

```python
# 简单任务用 SDK
simple_agent = ClaudeNativeAgent(..., use_sdk_execution=True)

# 复杂任务用 LangGraph
complex_agent = ClaudeNativeAgent(..., use_sdk_execution=False)
```

---

## 📁 新增文件

| 文件 | 功能 | 行数 |
|------|------|------|
| `utils/claude_client.py` | Claude SDK 客户端适配器 | 299 |
| `tools/mcp_adapter.py` | MCP 工具集成 | 369 |
| `core/claude_agent.py` | Claude 原生 Agent | 382 |
| `orchestration/hooks.py` | Hooks 管理器 | 398 |
| `examples/claude_sdk_integration_example.py` | 完整示例 | 525 |

**总计**: ~2000 行代码 + 完整文档

---

## 📚 文档导航

| 文档 | 内容 | 适合人群 |
|------|------|---------|
| **本文件** | 快速参考 | 快速了解 |
| [完整集成指南](./docs/claude_sdk_integration.md) | 详细文档（600+ 行） | 深入学习 |
| [集成总结](./docs/CLAUDE_SDK_INTEGRATION_SUMMARY.md) | 架构对比 | 决策参考 |
| [集成示例](./examples/claude_sdk_integration_example.py) | 5 个示例 | 上手实践 |

---

## 🎁 主要优势

### 1. 无缝兼容
```python
# 现有代码无需修改
agent = BaseAgent(..., llm_client=UnifiedLLMClient())

# 可选升级
agent = BaseAgent(..., llm_client=ClaudeSDKClient())
```

### 2. 渐进式集成
```
Level 1 (SDK客户端) → Level 2 (MCP工具) → Level 3 (Hooks) → Level 4 (完整)
```

### 3. 两个生态
```python
# agent_framework 工具
@tool(...)
def framework_tool(...): pass

# MCP 工具
@mcp_tool(...)
def mcp_tool(...): pass

# 都可用！
```

### 4. 灵活执行
```python
ClaudeNativeAgent(
    ...,
    use_sdk_execution=True   # SDK 原生（简洁快速）
    # use_sdk_execution=False  # LangGraph（复杂强大）
)
```

---

## 🔥 核心特性

### 1. ClaudeSDKClient - SDK 客户端适配器

```python
from utils.claude_client import ClaudeSDKClient

client = ClaudeSDKClient(
    model_name="claude-sonnet-4-20250514",
    mcp_servers={"calculator": ...},  # MCP 服务器
    hooks={"PreToolUse": [...]},      # Hooks
)

# 与 UnifiedLLMClient 接口完全兼容
response = await client.ainvoke("问题")
```

**特点**：
- ✅ 兼容 UnifiedLLMClient 接口
- ✅ 原生 MCP 支持
- ✅ Hooks 机制
- ✅ 流式响应

### 2. MCPToolAdapter - MCP 工具适配器

```python
from tools import ToolRegistry, MCPToolAdapter

adapter = MCPToolAdapter(tool_registry)

# 方式1: 装饰器快速注册
@mcp_tool(...)
async def my_tool(...): pass

# 方式2: 注册 SDK 服务器
adapter.register_sdk_server("calc", calculator_server)

# 方式3: 导入外部 MCP 服务器
await adapter.import_from_mcp_server("fs", fs_config)
```

**特点**：
- ✅ 打通 MCP 生态
- ✅ 与 ToolRegistry 双向互通
- ✅ 三种注册方式
- ✅ 自动转换格式

### 3. ClaudeNativeAgent - Claude 原生执行器

```python
from core.claude_agent import ClaudeNativeAgent

agent = ClaudeNativeAgent(
    definition=agent_def,
    workspace=workspace,
    tool_registry=tool_registry,
    mcp_servers=mcp_config,
    hooks=hooks_config,
    use_sdk_execution=True  # 关键参数
)
```

**特点**：
- ✅ 替代 LangGraph 执行（可选）
- ✅ 更简洁的执行流程
- ✅ 保留工作空间追踪
- ✅ 支持验证机制

### 4. HooksManager - Hooks 管理器

```python
from orchestration.hooks import HooksManager, HookEvent

hooks_mgr = HooksManager()

@hooks_mgr.register_hook(HookEvent.PRE_TOOL_USE, "bash")
async def check_command(input_data, tool_use_id, context):
    if "rm -rf" in command:
        return {"permissionDecision": "deny"}
    return {}
```

**特点**：
- ✅ 细粒度执行控制
- ✅ 预定义安全 Hooks
- ✅ 装饰器注册
- ✅ 与验证层集成

---

## 💻 完整示例

### 场景：金融分析 Agent

```python
from core.claude_agent import ClaudeNativeAgent
from definitions import AgentDefinition
from workspace import AgentWorkspace, WorkspaceConfig
from tools import ToolRegistry, MCPToolAdapter
from tools.mcp_adapter import mcp_tool
from orchestration.hooks import HooksManager, HookEvent
from definitions import ToolCategory

# 1. 定义工具
tool_registry = ToolRegistry()
mcp_adapter = MCPToolAdapter(tool_registry)

@mcp_tool(
    tool_id="analyze_stock",
    name="股票分析",
    description="分析股票数据",
    input_schema={"type": "object", "properties": {"ticker": {"type": "string"}}},
    category=ToolCategory.STOCK_DATA
)
async def analyze_stock(ticker: str):
    # 实际实现
    return {"ticker": ticker, "analysis": "...", "recommendation": "买入"}

# 2. 配置 Hooks
hooks_mgr = HooksManager()

@hooks_mgr.register_hook(HookEvent.PRE_TOOL_USE, "analyze_stock")
async def log_analysis(input_data, tool_use_id, context):
    print(f"分析股票: {input_data}")
    return {}

# 3. 创建 Agent
agent = ClaudeNativeAgent(
    definition=AgentDefinition.from_yaml_file("agents/financial_analyst.yaml"),
    workspace=AgentWorkspace(WorkspaceConfig(
        base_path="./workspaces",
        task_id="task_001"
    )),
    tool_registry=tool_registry,
    mcp_servers=mcp_adapter.get_mcp_server_config(),
    hooks=hooks_mgr.get_hooks_config(),
    use_sdk_execution=True
)

# 4. 运行
result = await agent.run(
    task_description="分析贵州茅台的投资价值",
    input_data={"ticker": "600519.SH"}
)

print(f"成功: {result['success']}")
print(f"结果: {result['result']}")
```

---

## 🎓 学习路径

### 初学者（5 分钟）
1. 阅读本文件（快速了解）
2. 运行 `examples/claude_sdk_integration_example.py` 中的示例 1

### 进阶（30 分钟）
1. 阅读[完整集成指南](./docs/claude_sdk_integration.md)
2. 尝试示例 2-5

### 专家（1 小时）
1. 阅读[集成总结](./docs/CLAUDE_SDK_INTEGRATION_SUMMARY.md)
2. 查看源码实现
3. 自定义 Hooks 和工具

---

## ❓ 常见问题

### Q: 必须安装 Claude SDK 吗？
**A**: 不必须。如果未安装，会自动回退到 UnifiedLLMClient。

### Q: 会破坏现有代码吗？
**A**: 不会。完全向后兼容，现有代码无需修改。

### Q: 性能如何？
**A**: SDK 原生执行通常更快（启动更快，IPC 更少），但 LangGraph 在复杂场景下更强大。

### Q: 如何选择执行模式？
**A**: 
- 简单任务 → SDK 执行 (`use_sdk_execution=True`)
- 复杂任务 → LangGraph 执行 (`use_sdk_execution=False`)

### Q: 可以混用吗？
**A**: 可以！不同 Agent 可以选择不同执行模式。

---

## 🔗 相关链接

- [Claude Agent SDK GitHub](https://github.com/anthropics/claude-agent-sdk-python)
- [MCP 协议](https://modelcontextprotocol.io/)
- [LangGraph 文档](https://langchain-ai.github.io/langgraph/)
- [agent_framework 核心文档](./docs/00_overview.md)

---

## 📈 下一步

### 现在就试试！

```bash
# 1. 安装依赖
pip install claude-agent-sdk

# 2. 设置 API Key
export ANTHROPIC_API_KEY=your_key

# 3. 运行示例
python examples/claude_sdk_integration_example.py
```

### 或者

查看[完整文档](./docs/claude_sdk_integration.md)了解更多细节。

---

**版本**: v1.0.0  
**更新**: 2025-01-XX  
**状态**: ✅ 生产就绪

---

<div align="center">

### 🎉 欢迎使用 agent_framework + Claude SDK 集成！

**企业级架构 × Claude 强大能力 = 无限可能**

</div>

