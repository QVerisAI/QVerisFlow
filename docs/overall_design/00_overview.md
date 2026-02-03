# 智能 Agent 框架综合设计方案

## 概述

本设计方案整合了两个版本的多智能体系统设计的核心优势：

- **方案一**：多智能体框架设计深度评审与优化方案 —— 强调声明式配置、工具引用语法、智能路由
- **方案二**：基于 Claude Agent SDK 最佳实践 —— 强调核心循环、文件系统交互、自我验证

最终目标是构建一个**既稳定可控、又灵活智能**的 Agent 框架，支持：

1. 📁 **文件系统优先** - 所有交互通过文件系统，确保可恢复、可追溯
2. 🔄 **核心循环** - gather → action → verify → repeat 的标准 Agent 循环
3. 📝 **声明式配置** - YAML/JSON 定义 Agent、工具、工作流
4. 🧠 **智能演化** - 支持动态创建、编辑、优化 Agent 和工作流
5. ✅ **三层验证** - 规则验证 + 视觉验证 + LLM 评判

---

## 核心设计哲学

### 1. Anthropic Agent SDK 核心原则

> "The key design principle behind the Claude Agent SDK is to give your agents a computer, allowing them to work like humans do."

| 原则 | 含义 | 实现方式 |
|------|------|----------|
| 给 Agent 一台计算机 | Agent 需要与程序员相同的工具 | 文件系统 + Bash + 代码执行 |
| 文件系统是交互总线 | 所有数据通过文件传递 | 读/写/编辑文件作为核心操作 |
| Coding Agent 是基础 | 广义的 Coding = 结构化内容生成 | 文件的读写和编辑是核心能力 |

### 2. 声明式配置原则

| 原则 | 含义 | 实现方式 |
|------|------|----------|
| 配置即代码 | Agent/工具/工作流都是可配置的 | YAML/JSON 声明式定义 |
| 关注点分离 | Prompt/工具/执行策略分离 | 三层 Prompt 结构 |
| 引用解析 | 工具和上下文通过符号引用 | @工具名 和 #上下文名 语法 |

### 3. 智能演化原则

| 原则 | 含义 | 实现方式 |
|------|------|----------|
| 持续优化 | Agent 在使用中不断改进 | 反馈学习 + Prompt 自动调优 |
| 智能生成 | 支持 LLM 生成新 Agent/工作流 | Meta-Agent 设计 |
| 版本管理 | 配置变更可追溯 | Git-like 版本控制 |

---

## 架构总览

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        智能 Agent 框架 (etf_common/agent_framework)      │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │                        应用层 (Applications)                     │   │
│  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐  │   │
│  │  │ 金融分析 Agent│  │ 研报生成 Agent│  │ 自定义领域 Agent     │  │   │
│  │  └──────────────┘  └──────────────┘  └──────────────────────┘  │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│                                    │                                    │
│                                    ▼                                    │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │                      编排层 (Orchestration)                      │   │
│  │  ┌─────────────┐  ┌─────────────┐  ┌────────────────────────┐  │   │
│  │  │ 工作流引擎   │  │ 智能路由器   │  │ 子 Agent 管理器        │  │   │
│  │  │ WorkflowEng │  │ SmartRouter │  │ SubAgentManager        │  │   │
│  │  └─────────────┘  └─────────────┘  └────────────────────────┘  │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│                                    │                                    │
│                                    ▼                                    │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │                       核心层 (Core)                              │   │
│  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐  │   │
│  │  │ Agent 基类    │  │ 执行循环     │  │ 验证器               │  │   │
│  │  │ BaseAgent    │  │ CoreLoop     │  │ Verifier            │  │   │
│  │  └──────────────┘  └──────────────┘  └──────────────────────┘  │   │
│  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐  │   │
│  │  │ 工作空间      │  │ 状态管理     │  │ 上下文压缩           │  │   │
│  │  │ Workspace    │  │ StateManager │  │ Compaction          │  │   │
│  │  └──────────────┘  └──────────────┘  └──────────────────────┘  │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│                                    │                                    │
│                                    ▼                                    │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │                     定义层 (Definitions)                         │   │
│  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐  │   │
│  │  │ Agent 定义    │  │ 工具定义     │  │ 工作流定义           │  │   │
│  │  │ AgentDef     │  │ ToolDef      │  │ WorkflowDef         │  │   │
│  │  └──────────────┘  └──────────────┘  └──────────────────────┘  │   │
│  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐  │   │
│  │  │ Prompt 构建   │  │ 引用解析器   │  │ Schema 定义          │  │   │
│  │  │ PromptBuilder│  │ RefResolver  │  │ SchemaValidator     │  │   │
│  │  └──────────────┘  └──────────────┘  └──────────────────────┘  │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│                                    │                                    │
│                                    ▼                                    │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │                      工具层 (Tools)                              │   │
│  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐  │   │
│  │  │ 文件系统工具  │  │ Bash 执行    │  │ 业务工具             │  │   │
│  │  │ FileTools    │  │ BashTools    │  │ BusinessTools       │  │   │
│  │  └──────────────┘  └──────────────┘  └──────────────────────┘  │   │
│  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐  │   │
│  │  │ 工具注册表    │  │ 工具分类     │  │ MCP 工具             │  │   │
│  │  │ ToolRegistry │  │ Categories   │  │ MCPTools            │  │   │
│  │  └──────────────┘  └──────────────┘  └──────────────────────┘  │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│                                    │                                    │
│                                    ▼                                    │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │                     智能演化层 (Evolution)                       │   │
│  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐  │   │
│  │  │ Meta Agent   │  │ 反馈学习     │  │ 版本管理             │  │   │
│  │  │ AgentCreator │  │ FeedbackLoop │  │ VersionControl      │  │   │
│  │  └──────────────┘  └──────────────┘  └──────────────────────┘  │   │
│  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐  │   │
│  │  │ Prompt 优化   │  │ A/B 测试     │  │ 性能监控             │  │   │
│  │  │ PromptOptim  │  │ ABTesting    │  │ Monitoring          │  │   │
│  │  └──────────────┘  └──────────────┘  └──────────────────────┘  │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│                                                                         │
├─────────────────────────────────────────────────────────────────────────┤
│                        基础设施层 (Infrastructure)                       │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────────────┐  │
│  │ LLM 客户端    │  │ 链路追踪     │  │ 日志/指标                    │  │
│  │ UnifiedLLM   │  │ Tracing      │  │ Logging/Metrics             │  │
│  └──────────────┘  └──────────────┘  └──────────────────────────────┘  │
├─────────────────────────────────────────────────────────────────────────┤
│                          存储层 (Storage)                                │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────────────┐  │
│  │ PostgreSQL   │  │    OSS       │  │        Redis                 │  │
│  │ 结构化数据    │  │  文件存储    │  │       缓存层                  │  │
│  │ Agent/Tool   │  │  Workspace   │  │    LLM 响应缓存               │  │
│  │ Workflow 定义 │  │  归档/共享    │  │    会话状态                  │  │
│  └──────────────┘  └──────────────┘  └──────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 目录结构

```
etf_common/agent_framework/
├── __init__.py
│
├── core/                           # 核心层
│   ├── __init__.py
│   ├── base_agent.py              # Agent 基类（核心循环实现）
│   ├── agent_loop.py              # 核心循环：gather → action → verify → repeat
│   ├── agent_state.py             # Agent 状态管理
│   ├── context_manager.py         # 上下文管理（支持 Compaction）
│   └── error_recovery.py          # 错误恢复机制
│
├── definitions/                    # 定义层
│   ├── __init__.py
│   ├── agent_definition.py        # Agent 定义模型
│   ├── tool_definition.py         # 工具定义模型
│   ├── workflow_definition.py     # 工作流定义模型
│   ├── prompt_structure.py        # 三层 Prompt 结构
│   ├── schema_validator.py        # Schema 验证器
│   └── reference_resolver.py      # @工具名 和 #上下文名 解析器
│
├── workspace/                      # 工作空间（文件系统交互）
│   ├── __init__.py
│   ├── workspace.py               # 工作空间管理
│   ├── file_manager.py            # 文件管理器
│   ├── draft_manager.py           # 草稿迭代管理
│   └── artifact_store.py          # 产出物存储
│
├── verification/                   # 验证层
│   ├── __init__.py
│   ├── verifier.py                # 验证器基类
│   ├── rule_verifier.py           # 规则验证器
│   ├── llm_judge.py               # LLM 评判验证器
│   ├── visual_verifier.py         # 视觉验证器
│   └── composite_verifier.py      # 组合验证器
│
├── tools/                          # 工具层
│   ├── __init__.py
│   ├── tool_registry.py           # 工具注册表
│   ├── tool_categories.py         # 工具分类
│   ├── file_tools.py              # 文件系统工具
│   ├── bash_tools.py              # Bash 执行工具
│   ├── builtin/                   # 内置业务工具
│   │   ├── search_tools.py
│   │   ├── financial_tools.py
│   │   └── mcp_tools.py
│   └── tool_decorator.py          # 工具装饰器
│
├── orchestration/                  # 编排层
│   ├── __init__.py
│   ├── workflow_engine.py         # 工作流引擎
│   ├── smart_router.py            # 智能路由器
│   ├── sub_agent_manager.py       # 子 Agent 管理器
│   ├── parallel_executor.py       # 并行执行器
│   └── data_pipeline.py           # 数据管道
│
├── registry/                       # 注册表
│   ├── __init__.py
│   ├── agent_registry.py          # Agent 注册表
│   ├── workflow_registry.py       # 工作流注册表
│   └── yaml_loader.py             # YAML 配置加载器
│
├── evolution/                      # 智能演化层
│   ├── __init__.py
│   ├── meta_agent.py              # Meta Agent（创建/优化 Agent）
│   ├── feedback_loop.py           # 反馈学习
│   ├── prompt_optimizer.py        # Prompt 自动优化
│   ├── version_control.py         # 版本控制
│   └── ab_testing.py              # A/B 测试
│
├── observability/                  # 可观测性
│   ├── __init__.py
│   ├── tracing.py                 # 链路追踪
│   ├── metrics.py                 # 性能指标
│   └── logging.py                 # 日志增强
│
├── storage/                        # 存储层
│   ├── __init__.py
│   ├── storage_service.py         # 统一存储服务
│   ├── oss_client.py              # OSS 客户端抽象 (MinIO/阿里云)
│   ├── models/
│   │   └── db_models.py           # SQLAlchemy ORM 模型
│   ├── repositories/              # CRUD Repository
│   │   ├── base.py
│   │   ├── agent_repository.py    # Agent 定义 CRUD
│   │   ├── tool_repository.py     # Tool 定义 CRUD
│   │   ├── workflow_repository.py # Workflow 定义 CRUD
│   │   ├── task_repository.py     # Task CRUD
│   │   └── trace_repository.py    # Trace CRUD
│   └── migrations/                 # Alembic 数据库迁移
│
├── persistence/                    # 数据持久化
│   ├── __init__.py
│   ├── models.py                  # 追踪数据模型
│   ├── trace_collector.py         # 追踪收集器
│   ├── trace_storage.py           # 追踪存储
│   └── langgraph_integration.py   # LangGraph 检查点集成
│
└── config/                         # 配置
    ├── __init__.py
    ├── framework_config.py        # 框架配置
    └── defaults.py                # 默认值
```

---

## 文档索引

| 文档 | 描述 |
|------|------|
| [01_core_agent.md](./01_core_agent.md) | Agent 核心循环与基类设计（基于 LangGraph） |
| [02_definitions.md](./02_definitions.md) | Agent、工具、工作流定义模型 |
| [03_workspace.md](./03_workspace.md) | 工作空间与文件系统交互 |
| [04_verification.md](./04_verification.md) | 三层验证机制 |
| [05_tools.md](./05_tools.md) | 工具系统设计 |
| [06_orchestration.md](./06_orchestration.md) | 工作流编排与智能路由 |
| [07_evolution.md](./07_evolution.md) | 智能演化与持续优化 |
| [08_examples.md](./08_examples.md) | 完整使用示例 |
| [09_data_persistence.md](./09_data_persistence.md) | 全流程数据持久化（执行追踪） |
| [10_file_storage.md](./10_file_storage.md) | 任务文件持久化存储 |
| [11_storage_infrastructure.md](./11_storage_infrastructure.md) | 存储基础设施（PostgreSQL + OSS + Redis） |
| [12_claude_sdk_integration.md](./12_claude_sdk_integration.md) | **Claude Agent SDK 深度集成方案** |

---

## 关键改进总结

| 维度 | 方案一 | 方案二 | 整合方案 |
|------|--------|--------|----------|
| 核心循环 | 无明确循环 | gather → action → verify | ✅ 标准化核心循环 |
| 交互总线 | Tool Call 输出 | 文件系统 | ✅ 文件系统优先 |
| Prompt 结构 | 三层结构 | 无分层 | ✅ 三层结构 + 引用解析 |
| 工具引用 | @工具名 语法 | 无特殊语法 | ✅ @工具名 + 工具分类 |
| 验证机制 | 无 | 规则 + LLM | ✅ 规则 + LLM 三层（视觉验证后续迭代） |
| 配置方式 | YAML 声明式 | 代码定义 | ✅ YAML + 代码混合 |
| 智能演化 | 无 | 无 | ✅ Meta Agent + 反馈学习 + 性能监控 |
| 子 Agent | 简单调用 | 并行 + 隔离 | ✅ 完整子 Agent 支持（含隔离级别） |
| 错误恢复 | 无 | 文件持久化 | ✅ 完整错误恢复（含外部检查点存储） |
| 上下文管理 | 无 | Compaction | ✅ 自动压缩 + 摘要 |
| 工具可靠性 | 无 | 无 | ✅ 重试机制 + 熔断器模式 |
| Claude SDK | 无 | 原生集成 | ✅ 双模式支持（LangGraph + Claude 原生）|

