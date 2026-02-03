# QVerisGen
Automatic multi-agent workflow generation, fully integrated with QVeris unified data and tool layer

基于 LangGraph 的多智能体框架，支持声明式配置、工作空间管理、三层验证机制和智能演化能力。

## 核心特性

- **文件系统优先** - 所有交互通过文件系统，便于调试和追踪
- **标准核心循环** - `gather_context` → `take_action` → `verify_work` → `repeat`
- **声明式配置** - 使用 YAML/JSON 定义 Agent、工具、工作流
- **智能演化** - 支持动态创建、编辑、优化
- **三层验证** - 规则验证 + LLM 评判 + 组合验证
- **LangGraph 集成** - 基于 LangGraph 的状态管理和持久化

## 架构概览

```
┌─────────────────────────────────────────────────────────────┐
│                         应用层                               │
│                    (业务 Agent 实现)                         │
├─────────────────────────────────────────────────────────────┤
│                         编排层                               │
│              SmartRouter | WorkflowEngine                   │
├─────────────────────────────────────────────────────────────┤
│                         核心层                               │
│        BaseAgent | AgentGraph | Verification                │
├─────────────────────────────────────────────────────────────┤
│                         定义层                               │
│   AgentDefinition | ToolDefinition | WorkflowDefinition     │
├─────────────────────────────────────────────────────────────┤
│                      基础设施层                              │
│        PostgreSQL | Redis | OSS | LangGraph                │
└─────────────────────────────────────────────────────────────┘
```

## 快速开始

### 1. 安装依赖

```bash
pip install langgraph langchain-core pydantic pyyaml
```

可选依赖：
```bash
# OSS 支持
pip install minio  # MinIO
pip install oss2   # 阿里云 OSS

# 数据库支持
pip install sqlalchemy asyncpg psycopg2-binary

# Redis 支持
pip install redis
```

### 2. 创建一个简单的 Agent

```python
from etf_common.agent_framework import (
    AgentDefinition,
    BaseAgent,
    AgentWorkspace,
    WorkspaceConfig,
)

# 创建 Agent 定义
agent_def = AgentDefinition(
    agent_id="my_agent",
    name="我的第一个 Agent",
    description="一个简单的示例 Agent",
    # ... 其他配置
)

# 创建工作空间
workspace = AgentWorkspace(WorkspaceConfig(
    base_path="./workspaces",
    task_id="task_001"
))

# 创建并运行 Agent
agent = BaseAgent(
    definition=agent_def,
    workspace=workspace,
    llm_client=llm_client  # UnifiedLLMClient 实例
)

result = await agent.run(
    task_description="分析股票价格",
    input_data={"ticker": "600519.SH"}
)
```

### 3. 注册工具

```python
from etf_common.agent_framework import tool, ToolCategory

@tool(
    tool_id="stock_price",
    name="股票价格查询",
    alias="股票价格",
    description="查询股票实时价格",
    category=ToolCategory.STOCK_DATA,
    input_schema={"type": "object", "properties": {...}},
    output_schema={"type": "object", "properties": {...}}
)
async def get_stock_price(ticker: str) -> dict:
    # 实现工具逻辑
    return {"ticker": ticker, "price": 1850.0}
```

### 4. 使用 YAML 定义 Agent

```yaml
# agents/financial_analyst.yaml
agent_id: financial_analyst
name: 金融分析师
description: 专业的金融分析 Agent
version: 1.0.0

execution_type: reasoning_executor
domain_type: financial_analysis

background_instruction:
  role_description: 你是一位资深金融分析师
  core_capability: 分析股票价格数据并给出投资建议
  task_context: 基于提供的信息进行专业分析

output_instruction:
  format_type: json
  format_requirements:
    - 输出格式为 JSON
    - 包含必要字段

user_instruction:
  task_description: 请分析股票并给出建议
  tool_references:
    - "@股票价格"
    - "@财务数据"

model_config:
  model_name: deepseek/deepseek-v3
  temperature: 0.3
  max_tokens: 2048
  max_iterations: 5
```

加载并使用：

```python
from etf_common.agent_framework import AgentDefinition, BaseAgent

# 从 YAML 加载
agent_def = AgentDefinition.from_yaml_file("agents/financial_analyst.yaml")

# 创建 Agent
agent = BaseAgent.from_yaml(
    yaml_path="agents/financial_analyst.yaml",
    workspace_config=workspace_config,
    llm_client=llm_client
)
```

## 核心组件

### 1. 定义层 (Definitions)

- **AgentDefinition** - Agent 的完整定义
- **ToolDefinition** - 工具定义
- **WorkflowDefinition** - 工作流定义
- **Prompt 三层结构** - Background/Output/User Instructions

### 2. 核心层 (Core)

- **BaseAgent** - Agent 基类，封装 LangGraph 图
- **AgentGraphBuilder** - 构建 LangGraph 状态图
- **AgentState** - LangGraph 兼容的状态定义

### 3. 工作空间 (Workspace)

文件系统结构：
```
workspaces/
└── task_001/
    ├── input/          # 输入文件
    │   ├── task.md     # 任务描述
    │   └── input.json  # 输入数据
    ├── output/         # 输出文件
    │   └── result.json # 执行结果
    ├── scratch/        # 草稿和临时文件
    │   ├── draft_v1.md
    │   └── draft_v2.md
    ├── context/        # 收集的上下文
    │   └── gathered_context.md
    ├── logs/           # 日志文件
    │   ├── actions.jsonl
    │   └── errors.jsonl
    └── state/          # 状态快照
        └── checkpoint_*.json
```

### 4. 验证层 (Verification)

```python
from etf_common.agent_framework import (
    RuleBasedVerifier,
    JSONFormatRule,
    RequiredFieldsRule,
    CompositeVerifier
)

# 规则验证
verifier = RuleBasedVerifier([
    JSONFormatRule(),
    RequiredFieldsRule(["company", "analysis"]),
])

# 组合验证
composite = CompositeVerifier(
    verifiers=[rule_verifier, llm_judge_verifier],
    strategy="all"  # all, any, weighted
)
```

### 5. 工具系统 (Tools)

```python
from etf_common.agent_framework import ToolRegistry

# 获取工具注册表
registry = ToolRegistry()

# 列出所有工具
tools = registry.list_all()

# 执行工具
result = await registry.execute(
    "stock_price",
    {"ticker": "600519.SH"}
)
```

### 6. 注册表 (Registry)

```python
from etf_common.agent_framework import AgentRegistry

# 获取注册表
registry = AgentRegistry()

# 注册 Agent 定义
registry.register_definition(agent_def)

# 从 YAML 目录批量注册
registry.register_from_yaml("agents/")

# 查找 Agent
agents = registry.find_by_domain(AgentDomainType.FINANCIAL_ANALYSIS)
```

### 7. 智能路由 (Smart Router)

```python
from etf_common.agent_framework import SmartRouter, RoutingStrategy

router = SmartRouter(
    agent_registry=agent_registry,
    tool_registry=tool_registry
)

# 智能路由
selected_agents = await router.route(
    task_description="分析股票价格并给出投资建议",
    domain=AgentDomainType.FINANCIAL_ANALYSIS,
    strategy=RoutingStrategy.CAPABILITY_MATCH
)
```

## 示例

完整示例请参见：
- `examples/agent_framework/simple_example.py` - 简单示例
- `docs/agent_framework/08_examples.md` - 详细示例文档

## 文档

详细文档位于 `docs/agent_framework/` 目录：

- `00_overview.md` - 框架概览
- `01_core_agent.md` - 核心 Agent 设计
- `02_definitions.md` - 定义模型
- `03_workspace.md` - 工作空间
- `04_verification.md` - 验证机制
- `05_tools.md` - 工具系统
- `06_orchestration.md` - 工作流编排
- `07_evolution.md` - 智能演化
- `08_examples.md` - 使用示例
- `09_data_persistence.md` - 数据持久化
- `10_file_storage.md` - 文件存储
- `11_storage_infrastructure.md` - 存储基础设施

## 配置

### LLM 配置

```python
from etf_common.llm import UnifiedLLMClient

llm_client = UnifiedLLMClient(
    provider="openrouter",
    model_name="deepseek/deepseek-v3",
    client_type="langchain"
)
```

### 存储配置

```python
from etf_common.agent_framework import StorageConfig

storage_config = StorageConfig(
    postgres=PostgreSQLConfig(
        host="localhost",
        port=5432,
        database="etf_agent_framework"
    ),
    oss=OSSConfig(
        provider="minio",
        endpoint="localhost:9000",
        bucket_name="agent-framework"
    ),
    enable_postgres=True,
    enable_oss=True
)
```

## 最佳实践

1. **使用 YAML 定义 Agent** - 便于版本控制和动态加载
2. **充分利用工作空间** - 所有中间结果都保存在文件系统中
3. **实现验证器** - 确保输出质量
4. **使用工具装饰器** - 简化工具注册
5. **启用检查点** - 支持错误恢复

## 开发计划

详细开发计划请参见：`.cursor/plans/agent_framework_implementation_*.plan.md`

## 许可证

内部项目，未对外开源。

