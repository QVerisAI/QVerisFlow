# QVerisGen

基于 LangGraph 的多智能体框架，支持对话式工作流构建、可视化画布编辑、智能 Agent 生成和实时执行监控。

## 核心特性

- **对话式工作流构建** - 通过自然语言对话创建、修改、迭代工作流
- **可视化 Web UI** - 现代化的 React 界面，支持画布拖拽、节点编辑、实时状态展示
- **智能 Agent 生成** - Meta Agent 自动分析任务并生成最优 Agent 定义
- **多模型支持** - 灵活配置多种 LLM（Qwen、DeepSeek、GPT、GLM 等）
- **实时执行监控** - WebSocket 实时推送执行进度，支持暂停、恢复、干预
- **QVeris 集成** - 无缝对接 QVeris 统一数据和工具层
- **三层验证机制** - 规则验证 + LLM 评判 + 组合验证

## 架构概览

```
┌─────────────────────────────────────────────────────────────┐
│                       Web UI 层                              │
│          React + ReactFlow + WebSocket + Zustand            │
├─────────────────────────────────────────────────────────────┤
│                       Web API 层                             │
│              FastAPI + WebSocket Handlers                   │
├─────────────────────────────────────────────────────────────┤
│                       演化层 (Evolution)                     │
│  DialogueAgent | MetaAgent | ConversationalBuilder          │
├─────────────────────────────────────────────────────────────┤
│                       编排层 (Orchestration)                 │
│              SmartRouter | WorkflowEngine                   │
├─────────────────────────────────────────────────────────────┤
│                       核心层 (Core)                          │
│        BaseAgent | AgentGraph | Verification                │
├─────────────────────────────────────────────────────────────┤
│                       定义层 (Definitions)                   │
│   AgentDefinition | ToolDefinition | WorkflowDefinition     │
├─────────────────────────────────────────────────────────────┤
│                      基础设施层                              │
│     PostgreSQL | Redis | QVeris API | Multi-LLM             │
└─────────────────────────────────────────────────────────────┘
```

## 快速开始

### 1. 安装依赖

```bash
# 使用 uv（推荐）
uv sync

# 或使用 pip
pip install -e ".[web,dev]"
```

### 2. 配置模型

编辑 `config/app_config.yaml` 配置 LLM：

```yaml
models:
  qwen-plus:
    api_key: "your-api-key"
    base_url: "https://dashscope.aliyuncs.com/compatible-mode/v1"
    model_name: "qwen-plus"
    max_tokens: 8000
    temperature: 0.3

model_selection:
  default: "qwen-plus"
```

### 3. 启动 Web UI

```bash
# 启动后端服务
uv run python -m src.web

# 启动前端（新终端）
cd web-ui && npm install && npm run dev
```

访问 http://localhost:5173 开始构建工作流。

## 使用方式

### 方式一：Web UI 对话式构建（推荐）

1. 打开 Web UI
2. 在对话框中描述你的需求，例如：
   - "帮我创建一个分析英伟达股票的工作流"
   - "我需要一个多维度的投资分析系统"
3. 系统会自动生成工作流规划
4. 确认后自动生成 Agent 定义
5. 在画布上查看和编辑工作流
6. 点击执行，实时监控进度

### 方式二：命令行交互式构建

```bash
uv run python examples/interactive_builder_test.py
```

### 方式三：代码定义

```python
from src.definitions import AgentDefinition, WorkflowDefinition
from src.orchestration import WorkflowEngine

# 定义 Agent
agent_def = AgentDefinition(
    agent_id="data_collector",
    name="数据收集器",
    display_name="市场数据采集",
    description="收集和整理市场数据",
    # ... 其他配置
)

# 执行工作流
engine = WorkflowEngine()
result = await engine.execute(workflow_definition)
```

### 方式四：YAML 配置

```yaml
# agents/financial_analyst.yaml
agent_id: financial_analyst
name: 金融分析师
display_name: 专业金融分析师
description: 分析股票并给出投资建议

background_instruction:
  role_description: 你是一位资深金融分析师
  core_capability: 分析市场数据并给出专业建议

llm_config:
  model_name: qwen-plus
  temperature: 0.3
  max_tokens: 4000

tool_references:
  - tool_id: qveris_search_tools
  - tool_id: qveris_execute_tool
```

## 核心模块

### 演化层 (Evolution)

| 模块 | 说明 |
|------|------|
| `DialogueAgent` | 对话代理，理解用户意图并执行工作流操作 |
| `MetaAgent` | 元代理，自动生成 Agent 定义和工作流 |
| `ConversationalBuilder` | 对话式工作流构建器，管理构建状态 |
| `WorkflowOperationTools` | 工作流操作工具集（创建、迭代、执行等）|

### 编排层 (Orchestration)

| 模块 | 说明 |
|------|------|
| `WorkflowEngine` | 工作流执行引擎，支持流式执行和实时事件 |
| `SmartRouter` | 智能路由，根据任务选择最佳 Agent |

### 核心层 (Core)

| 模块 | 说明 |
|------|------|
| `BaseAgent` | Agent 基类，封装 LangGraph 状态图 |
| `AgentGraph` | Agent 执行图构建器 |
| `ContextManager` | 上下文管理，自动收集和整理信息 |

### Web 层

| 模块 | 说明 |
|------|------|
| `WebSocketHandler` | WebSocket 消息处理和会话管理 |
| `SessionManager` | 用户会话和状态持久化 |

## 配置说明

### 多模型配置

支持同时配置多个 LLM 提供商：

```yaml
models:
  qwen-plus:           # 通义千问
  deepseek-v3:         # DeepSeek
  gpt-5.2:             # OpenAI (via OpenRouter)
  glm-4.7:             # 智谱 GLM
  kimi-k2.5:           # Moonshot

model_selection:
  default: "qwen-plus"
  complexity_mapping:
    simple: "qwen-plus"
    medium: "deepseek-v3"
    complex: "deepseek-r1"
```

### QVeris 集成

```yaml
qveris:
  enabled: true
  api_key: ${QVERIS_API_KEY}
  base_url: "https://qveris.ai/api/v1"
```

## 项目结构

```
agent_framework/
├── config/              # 配置文件
│   └── app_config.yaml  # 主配置（模型、QVeris等）
├── src/
│   ├── core/           # 核心 Agent 实现
│   ├── definitions/    # 定义模型
│   ├── evolution/      # 智能演化（对话构建、Meta Agent）
│   ├── orchestration/  # 工作流编排
│   ├── tools/          # 工具系统
│   ├── verification/   # 验证层
│   ├── web/            # Web API 和 WebSocket
│   └── workspace/      # 工作空间管理
├── web-ui/             # React 前端
│   ├── src/
│   │   ├── components/ # UI 组件
│   │   ├── hooks/      # React Hooks
│   │   ├── stores/     # Zustand 状态管理
│   │   └── services/   # WebSocket 服务
│   └── package.json
├── examples/           # 示例代码
├── tests/              # 测试用例
└── docs/               # 文档
```

## 示例

### 运行已有工作流

```bash
uv run python examples/run_workflow.py \
  workspaces/demo/workflow.json \
  workspaces/demo/checkpoint.json
```

### Meta Agent 自动生成

```bash
uv run python examples/meta_agent_full_test.py
```

### Web UI 测试

```bash
uv run python examples/web_ui_test.py
```

## 文档

详细文档位于 `docs/` 目录：

- `overall_design/00_overview.md` - 框架概览
- `overall_design/01_core_agent.md` - 核心 Agent 设计
- `overall_design/07_evolution.md` - 智能演化机制
- `AGENT_FRAMEWORK_IMPLEMENTATION_SUMMARY.md` - 实现总结

## 开发

```bash
# 安装开发依赖
uv sync --extra dev --extra test

# 运行测试
uv run pytest

# 代码格式化
uv run black src/ tests/
uv run ruff check src/ tests/ --fix
```

## 技术栈

**后端**
- Python 3.11+
- LangGraph / LangChain
- FastAPI + WebSocket
- SQLAlchemy + PostgreSQL
- Pydantic v2

**前端**
- React 18 + TypeScript
- ReactFlow（工作流画布）
- Zustand（状态管理）
- Tailwind CSS
- WebSocket 实时通信

## 许可证
Apache License 2.0

