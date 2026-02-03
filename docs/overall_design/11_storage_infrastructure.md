# 存储基础设施与定义持久化设计

## 1. 存储介质选型

### 1.1 整体架构

```
┌─────────────────────────────────────────────────────────────────────────┐
│                          应用层 (Agent Framework)                        │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                    ┌───────────────┼───────────────┐
                    ▼               ▼               ▼
┌──────────────────────┐ ┌──────────────────┐ ┌──────────────────────────┐
│   PostgreSQL         │ │      Redis       │ │         OSS              │
│   (结构化数据)        │ │    (缓存/队列)    │ │     (文件存储)           │
├──────────────────────┤ ├──────────────────┤ ├──────────────────────────┤
│ • Agent 定义         │ │ • 会话缓存       │ │ • 工作空间文件           │
│ • Tool 定义          │ │ • LLM 响应缓存   │ │ • 草稿文件               │
│ • Workflow 定义      │ │ • 工具结果缓存   │ │ • 输出文件/报告          │
│ • 任务元数据         │ │ • 分布式锁       │ │ • 上下文文件             │
│ • 执行追踪           │ │ • 任务队列       │ │ • 归档包 (.tar.gz)       │
│ • 用户/权限          │ │                  │ │ • 共享资源/模板          │
└──────────────────────┘ └──────────────────┘ └──────────────────────────┘
```

### 1.2 存储职责划分

| 存储类型 | 存储介质 | 数据类型 | 特点 |
|----------|----------|----------|------|
| **元数据存储** | PostgreSQL | Agent/Tool/Workflow 定义、任务元数据、执行追踪 | ACID、复杂查询、关系管理 |
| **缓存层** | Redis | LLM 响应缓存、会话状态、工具结果 | 高速读写、TTL 自动过期 |
| **文件存储** | OSS (MinIO/S3/阿里云OSS) | 工作空间文件、草稿、输出、归档 | 大容量、低成本、CDN加速 |

---

## 2. PostgreSQL 数据库设计

### 2.1 数据库 Schema

```sql
-- ============================================================================
-- Agent 相关表
-- ============================================================================

-- Agent 定义主表
CREATE TABLE agent_definitions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_id VARCHAR(128) UNIQUE NOT NULL,
    name VARCHAR(256) NOT NULL,
    description TEXT,
    version VARCHAR(32) DEFAULT '1.0.0',
    
    -- 类型
    execution_type VARCHAR(64) NOT NULL,  -- reasoning_executor, executor, deep_search, etc.
    domain_type VARCHAR(64) NOT NULL,     -- financial_analysis, data_verification, etc.
    
    -- Prompt 配置 (JSON)
    background_instruction JSONB NOT NULL,
    output_instruction JSONB NOT NULL,
    user_instruction JSONB NOT NULL,
    
    -- 模型配置 (JSON)
    model_config JSONB NOT NULL DEFAULT '{
        "model_name": "deepseek/deepseek-v3",
        "temperature": 0.3,
        "max_tokens": 4096,
        "max_iterations": 10
    }',
    
    -- 工具引用 (JSON Array)
    tool_references JSONB DEFAULT '[]',
    
    -- 输入输出 Schema (JSON Schema)
    input_schema JSONB,
    output_schema JSONB,
    
    -- 文件操作配置
    file_operations JSONB,
    
    -- 元数据
    tags TEXT[] DEFAULT '{}',
    author VARCHAR(128) DEFAULT 'system',
    is_active BOOLEAN DEFAULT true,
    is_system BOOLEAN DEFAULT false,  -- 系统内置 vs 用户自定义
    
    -- 时间戳
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    
    -- 索引
    CONSTRAINT valid_execution_type CHECK (execution_type IN (
        'reasoning_executor', 'executor', 'deep_search', 
        'flow_agent', 'html_generator', 'markdown_generator'
    )),
    CONSTRAINT valid_domain_type CHECK (domain_type IN (
        'financial_analysis', 'data_verification', 'risk_assessment',
        'signal_detection', 'report_generation', 'general'
    ))
);

-- Agent 版本历史
CREATE TABLE agent_versions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_id VARCHAR(128) NOT NULL REFERENCES agent_definitions(agent_id) ON DELETE CASCADE,
    version VARCHAR(32) NOT NULL,
    definition_snapshot JSONB NOT NULL,  -- 完整定义快照
    change_log TEXT,
    created_by VARCHAR(128),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    
    UNIQUE(agent_id, version)
);

-- Agent 统计
CREATE TABLE agent_statistics (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_id VARCHAR(128) NOT NULL REFERENCES agent_definitions(agent_id) ON DELETE CASCADE,
    date DATE NOT NULL,
    
    -- 执行统计
    total_executions INTEGER DEFAULT 0,
    successful_executions INTEGER DEFAULT 0,
    failed_executions INTEGER DEFAULT 0,
    
    -- 性能统计
    avg_duration_ms INTEGER,
    avg_iterations FLOAT,
    avg_llm_calls INTEGER,
    avg_tool_calls INTEGER,
    
    -- Token 统计
    total_tokens BIGINT DEFAULT 0,
    total_cost_usd DECIMAL(10, 6) DEFAULT 0,
    
    -- 验证统计
    avg_verification_score FLOAT,
    
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    
    UNIQUE(agent_id, date)
);

-- ============================================================================
-- Tool 相关表
-- ============================================================================

-- Tool 定义主表
CREATE TABLE tool_definitions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tool_id VARCHAR(128) UNIQUE NOT NULL,
    name VARCHAR(256) NOT NULL,
    alias VARCHAR(64) NOT NULL,  -- @引用名
    description TEXT NOT NULL,
    
    -- 分类
    category VARCHAR(64) NOT NULL,
    
    -- Schema
    input_schema JSONB NOT NULL,
    output_schema JSONB NOT NULL,
    
    -- 执行配置
    is_async BOOLEAN DEFAULT true,
    timeout_seconds INTEGER DEFAULT 30,
    retry_count INTEGER DEFAULT 3,
    
    -- 权限
    requires_auth BOOLEAN DEFAULT false,
    rate_limit_per_minute INTEGER,
    
    -- 成本估算
    cost_estimate DECIMAL(10, 6) DEFAULT 0,
    
    -- 实现
    implementation_type VARCHAR(32) NOT NULL,  -- builtin, custom, mcp, external_api
    implementation_config JSONB,  -- MCP server info, API endpoint, etc.
    
    -- 示例 (JSON Array)
    examples JSONB DEFAULT '[]',
    
    -- 元数据
    tags TEXT[] DEFAULT '{}',
    is_active BOOLEAN DEFAULT true,
    is_system BOOLEAN DEFAULT false,
    
    -- 时间戳
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    
    CONSTRAINT valid_category CHECK (category IN (
        'file_system', 'bash', 'code_execution',
        'agentic_search', 'semantic_search', 'web_search',
        'stock_data', 'financial_data', 'news_data', 'research_data', 'announcement_data',
        'technical_analysis', 'fundamental_analysis', 'risk_analysis',
        'report_generation', 'chart_generation',
        'mcp', 'sub_agent'
    )),
    CONSTRAINT valid_implementation_type CHECK (implementation_type IN (
        'builtin', 'custom', 'mcp', 'external_api'
    ))
);

-- Tool 版本历史
CREATE TABLE tool_versions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tool_id VARCHAR(128) NOT NULL REFERENCES tool_definitions(tool_id) ON DELETE CASCADE,
    version VARCHAR(32) NOT NULL,
    definition_snapshot JSONB NOT NULL,
    change_log TEXT,
    created_by VARCHAR(128),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    
    UNIQUE(tool_id, version)
);

-- Tool 依赖关系
CREATE TABLE tool_dependencies (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tool_id VARCHAR(128) NOT NULL REFERENCES tool_definitions(tool_id) ON DELETE CASCADE,
    depends_on_tool_id VARCHAR(128) NOT NULL REFERENCES tool_definitions(tool_id),
    dependency_type VARCHAR(32) DEFAULT 'required',  -- required, optional
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    
    UNIQUE(tool_id, depends_on_tool_id)
);

-- ============================================================================
-- Workflow 相关表
-- ============================================================================

-- Workflow 定义主表
CREATE TABLE workflow_definitions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workflow_id VARCHAR(128) UNIQUE NOT NULL,
    name VARCHAR(256) NOT NULL,
    description TEXT,
    version VARCHAR(32) DEFAULT '1.0.0',
    
    -- 节点和边 (JSON)
    nodes JSONB NOT NULL,  -- WorkflowNode[]
    edges JSONB NOT NULL,  -- WorkflowEdge[]
    
    -- 入口出口
    entry_node VARCHAR(128) NOT NULL,
    exit_nodes TEXT[] NOT NULL,
    
    -- 全局配置
    global_context JSONB DEFAULT '{}',
    global_tools TEXT[] DEFAULT '{}',
    
    -- 文件系统配置
    workspace_path VARCHAR(512),
    output_path VARCHAR(512),
    
    -- 元数据
    tags TEXT[] DEFAULT '{}',
    author VARCHAR(128) DEFAULT 'system',
    is_active BOOLEAN DEFAULT true,
    is_system BOOLEAN DEFAULT false,
    
    -- 时间戳
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Workflow 版本历史
CREATE TABLE workflow_versions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workflow_id VARCHAR(128) NOT NULL REFERENCES workflow_definitions(workflow_id) ON DELETE CASCADE,
    version VARCHAR(32) NOT NULL,
    definition_snapshot JSONB NOT NULL,
    change_log TEXT,
    created_by VARCHAR(128),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    
    UNIQUE(workflow_id, version)
);

-- Workflow 与 Agent 的关联
CREATE TABLE workflow_agent_mappings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workflow_id VARCHAR(128) NOT NULL REFERENCES workflow_definitions(workflow_id) ON DELETE CASCADE,
    node_id VARCHAR(128) NOT NULL,
    agent_id VARCHAR(128) NOT NULL REFERENCES agent_definitions(agent_id),
    
    -- 覆盖配置 (JSON)
    config_overrides JSONB,
    
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    
    UNIQUE(workflow_id, node_id)
);

-- ============================================================================
-- 任务相关表
-- ============================================================================

-- 任务主表
CREATE TABLE tasks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    task_id VARCHAR(128) UNIQUE NOT NULL,
    name VARCHAR(256) NOT NULL,
    description TEXT,
    
    -- 状态
    status VARCHAR(32) NOT NULL DEFAULT 'pending',
    priority VARCHAR(16) DEFAULT 'normal',
    
    -- 关联
    agent_id VARCHAR(128) REFERENCES agent_definitions(agent_id),
    workflow_id VARCHAR(128) REFERENCES workflow_definitions(workflow_id),
    parent_task_id VARCHAR(128) REFERENCES tasks(task_id),
    
    -- 输入输出
    input_data JSONB DEFAULT '{}',
    output_summary JSONB DEFAULT '{}',
    
    -- 执行统计
    execution_summary JSONB DEFAULT '{}',
    
    -- 文件统计
    files_summary JSONB DEFAULT '{}',
    
    -- 工作空间 (OSS 路径)
    workspace_oss_path VARCHAR(512),
    
    -- 追踪
    trace_id VARCHAR(128),
    
    -- 保留策略
    retention_policy VARCHAR(32) DEFAULT 'standard',
    expires_at TIMESTAMP WITH TIME ZONE,
    
    -- 元数据
    tags TEXT[] DEFAULT '{}',
    labels JSONB DEFAULT '{}',
    
    -- 时间戳
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    started_at TIMESTAMP WITH TIME ZONE,
    completed_at TIMESTAMP WITH TIME ZONE,
    archived_at TIMESTAMP WITH TIME ZONE,
    
    CONSTRAINT valid_status CHECK (status IN (
        'pending', 'running', 'completed', 'failed', 'cancelled', 'archived'
    )),
    CONSTRAINT valid_priority CHECK (priority IN ('low', 'normal', 'high', 'critical')),
    CONSTRAINT valid_retention CHECK (retention_policy IN (
        'transient', 'standard', 'important', 'permanent'
    ))
);

-- 任务子任务关联
CREATE TABLE task_sub_tasks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    parent_task_id VARCHAR(128) NOT NULL REFERENCES tasks(task_id) ON DELETE CASCADE,
    sub_task_id VARCHAR(128) NOT NULL REFERENCES tasks(task_id) ON DELETE CASCADE,
    execution_order INTEGER,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    
    UNIQUE(parent_task_id, sub_task_id)
);

-- ============================================================================
-- 执行追踪相关表
-- ============================================================================

-- 执行追踪主表
CREATE TABLE execution_traces (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    trace_id VARCHAR(128) UNIQUE NOT NULL,
    
    -- 关联
    task_id VARCHAR(128) NOT NULL REFERENCES tasks(task_id),
    agent_id VARCHAR(128) REFERENCES agent_definitions(agent_id),
    workflow_id VARCHAR(128) REFERENCES workflow_definitions(workflow_id),
    parent_trace_id VARCHAR(128) REFERENCES execution_traces(trace_id),
    
    -- 输入输出
    input_data JSONB DEFAULT '{}',
    task_description TEXT,
    output_data JSONB,
    output_files TEXT[] DEFAULT '{}',
    
    -- 状态
    status VARCHAR(32) NOT NULL DEFAULT 'pending',
    
    -- 时间
    started_at TIMESTAMP WITH TIME ZONE,
    completed_at TIMESTAMP WITH TIME ZONE,
    duration_ms INTEGER,
    
    -- 汇总统计
    summary JSONB DEFAULT '{}',
    
    -- 错误信息
    error TEXT,
    error_stack TEXT,
    
    -- 工作空间
    workspace_oss_path VARCHAR(512),
    
    -- 元数据
    tags TEXT[] DEFAULT '{}',
    metadata JSONB DEFAULT '{}',
    
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    
    CONSTRAINT valid_trace_status CHECK (status IN (
        'pending', 'running', 'completed', 'failed', 'cancelled'
    ))
);

-- 执行跨度 (Spans)
CREATE TABLE trace_spans (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    span_id VARCHAR(64) NOT NULL,
    trace_id VARCHAR(128) NOT NULL REFERENCES execution_traces(trace_id) ON DELETE CASCADE,
    parent_span_id VARCHAR(64),
    
    name VARCHAR(256) NOT NULL,
    span_type VARCHAR(32) NOT NULL,
    
    started_at TIMESTAMP WITH TIME ZONE NOT NULL,
    ended_at TIMESTAMP WITH TIME ZONE,
    duration_ms INTEGER,
    
    status VARCHAR(32) DEFAULT 'running',
    error TEXT,
    
    attributes JSONB DEFAULT '{}',
    events JSONB DEFAULT '[]',
    
    CONSTRAINT valid_span_type CHECK (span_type IN (
        'agent', 'phase', 'llm_call', 'tool_call', 'sub_agent', 'verification', 'custom'
    ))
);

-- LLM 调用记录
CREATE TABLE trace_llm_calls (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    call_id VARCHAR(64) NOT NULL,
    trace_id VARCHAR(128) NOT NULL REFERENCES execution_traces(trace_id) ON DELETE CASCADE,
    span_id VARCHAR(64),
    
    -- 模型信息
    provider VARCHAR(64) NOT NULL,
    model VARCHAR(128) NOT NULL,
    
    -- 输入 (存 OSS 路径，避免大字段)
    messages_oss_path VARCHAR(512),  -- 消息内容存 OSS
    system_prompt_hash VARCHAR(64),  -- 用于缓存查找
    temperature DECIMAL(3, 2),
    max_tokens INTEGER,
    
    -- 输出
    response_oss_path VARCHAR(512),  -- 响应内容存 OSS
    tool_calls JSONB DEFAULT '[]',
    finish_reason VARCHAR(32),
    
    -- Token 统计
    prompt_tokens INTEGER DEFAULT 0,
    completion_tokens INTEGER DEFAULT 0,
    total_tokens INTEGER DEFAULT 0,
    
    -- 成本
    cost_usd DECIMAL(10, 6) DEFAULT 0,
    
    -- 性能
    latency_ms INTEGER DEFAULT 0,
    
    -- 状态
    success BOOLEAN DEFAULT true,
    error TEXT,
    cache_hit BOOLEAN DEFAULT false,
    
    timestamp TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 工具调用记录
CREATE TABLE trace_tool_calls (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    call_id VARCHAR(64) NOT NULL,
    trace_id VARCHAR(128) NOT NULL REFERENCES execution_traces(trace_id) ON DELETE CASCADE,
    span_id VARCHAR(64),
    
    -- 工具信息
    tool_id VARCHAR(128) NOT NULL,
    tool_name VARCHAR(256) NOT NULL,
    tool_category VARCHAR(64) NOT NULL,
    
    -- 输入输出 (大内容存 OSS)
    input_params JSONB NOT NULL,
    output_oss_path VARCHAR(512),  -- 输出存 OSS
    output_truncated BOOLEAN DEFAULT false,
    
    -- 性能
    latency_ms INTEGER DEFAULT 0,
    
    -- 状态
    success BOOLEAN DEFAULT true,
    error TEXT,
    retry_count INTEGER DEFAULT 0,
    
    timestamp TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 检查点
CREATE TABLE trace_checkpoints (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    checkpoint_id VARCHAR(64) NOT NULL,
    trace_id VARCHAR(128) NOT NULL REFERENCES execution_traces(trace_id) ON DELETE CASCADE,
    
    iteration INTEGER NOT NULL,
    phase VARCHAR(64) NOT NULL,
    node_id VARCHAR(128),
    
    -- 状态快照 (存 OSS)
    agent_state_oss_path VARCHAR(512),
    workflow_state_oss_path VARCHAR(512),
    
    -- LangGraph 检查点
    langgraph_checkpoint VARCHAR(256),
    
    recoverable BOOLEAN DEFAULT true,
    recovery_instructions TEXT,
    
    timestamp TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 验证记录
CREATE TABLE trace_verifications (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    record_id VARCHAR(64) NOT NULL,
    trace_id VARCHAR(128) NOT NULL REFERENCES execution_traces(trace_id) ON DELETE CASCADE,
    span_id VARCHAR(64),
    
    iteration INTEGER NOT NULL,
    
    passed BOOLEAN NOT NULL,
    score DECIMAL(3, 2) NOT NULL,
    feedback TEXT,
    
    rule_results JSONB DEFAULT '[]',
    llm_judge_result JSONB,
    
    -- 被验证的输出 (存 OSS)
    output_verified_oss_path VARCHAR(512),
    
    timestamp TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- ============================================================================
-- 索引
-- ============================================================================

-- Agent 索引
CREATE INDEX idx_agent_execution_type ON agent_definitions(execution_type);
CREATE INDEX idx_agent_domain_type ON agent_definitions(domain_type);
CREATE INDEX idx_agent_tags ON agent_definitions USING GIN(tags);
CREATE INDEX idx_agent_active ON agent_definitions(is_active);

-- Tool 索引
CREATE INDEX idx_tool_category ON tool_definitions(category);
CREATE INDEX idx_tool_alias ON tool_definitions(alias);
CREATE INDEX idx_tool_active ON tool_definitions(is_active);

-- Workflow 索引
CREATE INDEX idx_workflow_tags ON workflow_definitions USING GIN(tags);
CREATE INDEX idx_workflow_active ON workflow_definitions(is_active);

-- Task 索引
CREATE INDEX idx_task_status ON tasks(status);
CREATE INDEX idx_task_agent ON tasks(agent_id);
CREATE INDEX idx_task_workflow ON tasks(workflow_id);
CREATE INDEX idx_task_tags ON tasks USING GIN(tags);
CREATE INDEX idx_task_created ON tasks(created_at DESC);
CREATE INDEX idx_task_retention ON tasks(retention_policy, expires_at);

-- Trace 索引
CREATE INDEX idx_trace_task ON execution_traces(task_id);
CREATE INDEX idx_trace_agent ON execution_traces(agent_id);
CREATE INDEX idx_trace_status ON execution_traces(status);
CREATE INDEX idx_trace_created ON execution_traces(created_at DESC);

CREATE INDEX idx_span_trace ON trace_spans(trace_id);
CREATE INDEX idx_llm_call_trace ON trace_llm_calls(trace_id);
CREATE INDEX idx_tool_call_trace ON trace_tool_calls(trace_id);

-- ============================================================================
-- 触发器：自动更新 updated_at
-- ============================================================================

CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ language 'plpgsql';

CREATE TRIGGER update_agent_updated_at
    BEFORE UPDATE ON agent_definitions
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_tool_updated_at
    BEFORE UPDATE ON tool_definitions
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_workflow_updated_at
    BEFORE UPDATE ON workflow_definitions
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
```

---

## 3. OSS 文件存储设计

### 3.1 OSS 存储结构

```
{bucket}/
├── workspaces/                           # 工作空间文件
│   └── {task_id}/
│       ├── input/
│       │   ├── task.md
│       │   └── data.json
│       ├── output/
│       │   ├── result.json
│       │   └── report.md
│       ├── scratch/
│       │   ├── draft_v1.md
│       │   └── draft_v2.md
│       ├── context/
│       │   └── gathered.md
│       ├── logs/
│       │   ├── actions.jsonl
│       │   └── errors.jsonl
│       └── state/
│           └── checkpoint_001.json
│
├── traces/                               # 追踪数据（大字段）
│   └── {trace_id}/
│       ├── llm_calls/
│       │   ├── {call_id}_messages.json
│       │   └── {call_id}_response.json
│       ├── tool_calls/
│       │   └── {call_id}_output.json
│       ├── checkpoints/
│       │   └── {checkpoint_id}_state.json
│       └── verifications/
│           └── {record_id}_output.json
│
├── shared/                               # 共享资源
│   ├── templates/
│   │   ├── prompts/
│   │   ├── reports/
│   │   └── workflows/
│   └── knowledge/
│       ├── domain/
│       └── reference/
│
├── archives/                             # 归档存储
│   └── {year}/{quarter}/
│       └── {task_id}.tar.gz
│
└── exports/                              # 导出文件
    └── {export_id}/
        └── data.csv
```

### 3.2 OSS 客户端抽象

```python
# etf_common/agent_framework/storage/oss_client.py

from abc import ABC, abstractmethod
from typing import BinaryIO, Optional, List, Dict, Any
from pathlib import Path
from dataclasses import dataclass
from datetime import datetime, timedelta
import json


@dataclass
class OSSObject:
    """OSS 对象信息"""
    key: str
    size: int
    last_modified: datetime
    content_type: str
    metadata: Dict[str, str]


class OSSClient(ABC):
    """OSS 客户端抽象基类"""
    
    @abstractmethod
    async def put_object(
        self,
        key: str,
        data: bytes | BinaryIO,
        content_type: str = "application/octet-stream",
        metadata: Dict[str, str] = None
    ) -> str:
        """上传对象，返回完整路径"""
        pass
    
    @abstractmethod
    async def get_object(self, key: str) -> bytes:
        """获取对象内容"""
        pass
    
    @abstractmethod
    async def delete_object(self, key: str) -> bool:
        """删除对象"""
        pass
    
    @abstractmethod
    async def list_objects(
        self,
        prefix: str,
        max_keys: int = 1000,
        marker: str = None
    ) -> List[OSSObject]:
        """列出对象"""
        pass
    
    @abstractmethod
    async def copy_object(self, src_key: str, dst_key: str) -> str:
        """复制对象"""
        pass
    
    @abstractmethod
    async def object_exists(self, key: str) -> bool:
        """检查对象是否存在"""
        pass
    
    @abstractmethod
    async def get_presigned_url(
        self,
        key: str,
        expires_in: int = 3600,
        method: str = "GET"
    ) -> str:
        """获取预签名 URL"""
        pass
    
    # ========== 便捷方法 ==========
    
    async def put_json(self, key: str, data: Any, metadata: Dict[str, str] = None) -> str:
        """上传 JSON 数据"""
        json_bytes = json.dumps(data, ensure_ascii=False, indent=2, default=str).encode('utf-8')
        return await self.put_object(key, json_bytes, "application/json", metadata)
    
    async def get_json(self, key: str) -> Any:
        """获取 JSON 数据"""
        data = await self.get_object(key)
        return json.loads(data.decode('utf-8'))
    
    async def put_text(self, key: str, text: str, metadata: Dict[str, str] = None) -> str:
        """上传文本"""
        return await self.put_object(key, text.encode('utf-8'), "text/plain", metadata)
    
    async def get_text(self, key: str) -> str:
        """获取文本"""
        data = await self.get_object(key)
        return data.decode('utf-8')


class AliyunOSSClient(OSSClient):
    """阿里云 OSS 客户端"""
    
    def __init__(
        self,
        access_key_id: str,
        access_key_secret: str,
        endpoint: str,
        bucket_name: str
    ):
        import oss2
        
        self.auth = oss2.Auth(access_key_id, access_key_secret)
        self.bucket = oss2.Bucket(self.auth, endpoint, bucket_name)
        self.bucket_name = bucket_name
        self.endpoint = endpoint
    
    async def put_object(
        self,
        key: str,
        data: bytes | BinaryIO,
        content_type: str = "application/octet-stream",
        metadata: Dict[str, str] = None
    ) -> str:
        headers = {"Content-Type": content_type}
        if metadata:
            for k, v in metadata.items():
                headers[f"x-oss-meta-{k}"] = v
        
        self.bucket.put_object(key, data, headers=headers)
        return f"oss://{self.bucket_name}/{key}"
    
    async def get_object(self, key: str) -> bytes:
        result = self.bucket.get_object(key)
        return result.read()
    
    async def delete_object(self, key: str) -> bool:
        self.bucket.delete_object(key)
        return True
    
    async def list_objects(
        self,
        prefix: str,
        max_keys: int = 1000,
        marker: str = None
    ) -> List[OSSObject]:
        objects = []
        for obj in oss2.ObjectIterator(self.bucket, prefix=prefix, marker=marker, max_keys=max_keys):
            objects.append(OSSObject(
                key=obj.key,
                size=obj.size,
                last_modified=datetime.fromtimestamp(obj.last_modified),
                content_type=obj.content_type or "application/octet-stream",
                metadata={}
            ))
        return objects
    
    async def copy_object(self, src_key: str, dst_key: str) -> str:
        self.bucket.copy_object(self.bucket_name, src_key, dst_key)
        return f"oss://{self.bucket_name}/{dst_key}"
    
    async def object_exists(self, key: str) -> bool:
        return self.bucket.object_exists(key)
    
    async def get_presigned_url(
        self,
        key: str,
        expires_in: int = 3600,
        method: str = "GET"
    ) -> str:
        return self.bucket.sign_url(method, key, expires_in)


class MinIOClient(OSSClient):
    """MinIO 客户端（S3 兼容）"""
    
    def __init__(
        self,
        endpoint: str,
        access_key: str,
        secret_key: str,
        bucket_name: str,
        secure: bool = True
    ):
        from minio import Minio
        
        self.client = Minio(
            endpoint,
            access_key=access_key,
            secret_key=secret_key,
            secure=secure
        )
        self.bucket_name = bucket_name
        
        # 确保 bucket 存在
        if not self.client.bucket_exists(bucket_name):
            self.client.make_bucket(bucket_name)
    
    async def put_object(
        self,
        key: str,
        data: bytes | BinaryIO,
        content_type: str = "application/octet-stream",
        metadata: Dict[str, str] = None
    ) -> str:
        from io import BytesIO
        
        if isinstance(data, bytes):
            data = BytesIO(data)
            length = len(data.getvalue())
        else:
            data.seek(0, 2)
            length = data.tell()
            data.seek(0)
        
        self.client.put_object(
            self.bucket_name,
            key,
            data,
            length,
            content_type=content_type,
            metadata=metadata
        )
        return f"s3://{self.bucket_name}/{key}"
    
    async def get_object(self, key: str) -> bytes:
        response = self.client.get_object(self.bucket_name, key)
        try:
            return response.read()
        finally:
            response.close()
            response.release_conn()
    
    async def delete_object(self, key: str) -> bool:
        self.client.remove_object(self.bucket_name, key)
        return True
    
    async def list_objects(
        self,
        prefix: str,
        max_keys: int = 1000,
        marker: str = None
    ) -> List[OSSObject]:
        objects = []
        for obj in self.client.list_objects(self.bucket_name, prefix=prefix):
            objects.append(OSSObject(
                key=obj.object_name,
                size=obj.size,
                last_modified=obj.last_modified,
                content_type=obj.content_type or "application/octet-stream",
                metadata={}
            ))
            if len(objects) >= max_keys:
                break
        return objects
    
    async def copy_object(self, src_key: str, dst_key: str) -> str:
        from minio.commonconfig import CopySource
        
        self.client.copy_object(
            self.bucket_name,
            dst_key,
            CopySource(self.bucket_name, src_key)
        )
        return f"s3://{self.bucket_name}/{dst_key}"
    
    async def object_exists(self, key: str) -> bool:
        try:
            self.client.stat_object(self.bucket_name, key)
            return True
        except:
            return False
    
    async def get_presigned_url(
        self,
        key: str,
        expires_in: int = 3600,
        method: str = "GET"
    ) -> str:
        return self.client.presigned_get_object(
            self.bucket_name,
            key,
            expires=timedelta(seconds=expires_in)
        )
```

---

## 4. Agent/Tool/Workflow CRUD 服务

### 4.1 Repository 模式

```python
# etf_common/agent_framework/storage/repositories/base.py

from abc import ABC, abstractmethod
from typing import Generic, TypeVar, Optional, List, Dict, Any
from pydantic import BaseModel


T = TypeVar('T', bound=BaseModel)


class BaseRepository(ABC, Generic[T]):
    """Repository 基类"""
    
    @abstractmethod
    async def create(self, entity: T) -> T:
        pass
    
    @abstractmethod
    async def get(self, id: str) -> Optional[T]:
        pass
    
    @abstractmethod
    async def update(self, id: str, entity: T) -> T:
        pass
    
    @abstractmethod
    async def delete(self, id: str) -> bool:
        pass
    
    @abstractmethod
    async def list(
        self,
        filters: Dict[str, Any] = None,
        limit: int = 100,
        offset: int = 0
    ) -> List[T]:
        pass
    
    @abstractmethod
    async def count(self, filters: Dict[str, Any] = None) -> int:
        pass
```

### 4.2 Agent Repository

```python
# etf_common/agent_framework/storage/repositories/agent_repository.py

from typing import Optional, List, Dict, Any
from datetime import datetime
import json

from sqlalchemy import select, update, delete, func
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.db_models import AgentDefinitionDB, AgentVersionDB, AgentStatisticsDB
from ...definitions import AgentDefinition, AgentExecutionType, AgentDomainType
from .base import BaseRepository


class AgentRepository(BaseRepository[AgentDefinition]):
    """Agent 定义 Repository"""
    
    def __init__(self, session: AsyncSession):
        self.session = session
    
    async def create(self, agent: AgentDefinition) -> AgentDefinition:
        """创建 Agent 定义"""
        db_agent = AgentDefinitionDB(
            agent_id=agent.agent_id,
            name=agent.name,
            description=agent.description,
            version=agent.version,
            execution_type=agent.execution_type.value,
            domain_type=agent.domain_type.value,
            background_instruction=agent.background_instruction.model_dump(),
            output_instruction=agent.output_instruction.model_dump(),
            user_instruction=agent.user_instruction.model_dump(),
            model_config=agent.model_config.model_dump(),
            tool_references=[t.model_dump() for t in agent.tool_references],
            input_schema=agent.input_schema,
            output_schema=agent.output_schema,
            file_operations=agent.file_operations,
            tags=agent.tags,
            author=agent.author,
            is_active=True,
            is_system=False
        )
        
        self.session.add(db_agent)
        await self.session.commit()
        await self.session.refresh(db_agent)
        
        # 创建初始版本
        await self._create_version(agent.agent_id, agent, "Initial version")
        
        return agent
    
    async def get(self, agent_id: str) -> Optional[AgentDefinition]:
        """获取 Agent 定义"""
        result = await self.session.execute(
            select(AgentDefinitionDB).where(AgentDefinitionDB.agent_id == agent_id)
        )
        db_agent = result.scalar_one_or_none()
        
        if db_agent is None:
            return None
        
        return self._to_domain(db_agent)
    
    async def update(self, agent_id: str, agent: AgentDefinition, change_log: str = None) -> AgentDefinition:
        """更新 Agent 定义"""
        # 获取当前版本
        current = await self.get(agent_id)
        if current is None:
            raise ValueError(f"Agent 不存在: {agent_id}")
        
        # 更新数据库
        await self.session.execute(
            update(AgentDefinitionDB)
            .where(AgentDefinitionDB.agent_id == agent_id)
            .values(
                name=agent.name,
                description=agent.description,
                version=agent.version,
                execution_type=agent.execution_type.value,
                domain_type=agent.domain_type.value,
                background_instruction=agent.background_instruction.model_dump(),
                output_instruction=agent.output_instruction.model_dump(),
                user_instruction=agent.user_instruction.model_dump(),
                model_config=agent.model_config.model_dump(),
                tool_references=[t.model_dump() for t in agent.tool_references],
                input_schema=agent.input_schema,
                output_schema=agent.output_schema,
                file_operations=agent.file_operations,
                tags=agent.tags
            )
        )
        await self.session.commit()
        
        # 创建新版本
        await self._create_version(agent_id, agent, change_log or "Updated")
        
        return agent
    
    async def delete(self, agent_id: str) -> bool:
        """删除 Agent 定义（软删除）"""
        result = await self.session.execute(
            update(AgentDefinitionDB)
            .where(AgentDefinitionDB.agent_id == agent_id)
            .values(is_active=False)
        )
        await self.session.commit()
        return result.rowcount > 0
    
    async def hard_delete(self, agent_id: str) -> bool:
        """硬删除 Agent 定义"""
        result = await self.session.execute(
            delete(AgentDefinitionDB).where(AgentDefinitionDB.agent_id == agent_id)
        )
        await self.session.commit()
        return result.rowcount > 0
    
    async def list(
        self,
        filters: Dict[str, Any] = None,
        limit: int = 100,
        offset: int = 0
    ) -> List[AgentDefinition]:
        """列出 Agent 定义"""
        query = select(AgentDefinitionDB).where(AgentDefinitionDB.is_active == True)
        
        if filters:
            if "execution_type" in filters:
                query = query.where(AgentDefinitionDB.execution_type == filters["execution_type"])
            if "domain_type" in filters:
                query = query.where(AgentDefinitionDB.domain_type == filters["domain_type"])
            if "tags" in filters:
                query = query.where(AgentDefinitionDB.tags.contains(filters["tags"]))
            if "is_system" in filters:
                query = query.where(AgentDefinitionDB.is_system == filters["is_system"])
        
        query = query.order_by(AgentDefinitionDB.created_at.desc())
        query = query.limit(limit).offset(offset)
        
        result = await self.session.execute(query)
        return [self._to_domain(db_agent) for db_agent in result.scalars()]
    
    async def count(self, filters: Dict[str, Any] = None) -> int:
        """计数"""
        query = select(func.count(AgentDefinitionDB.id)).where(AgentDefinitionDB.is_active == True)
        
        if filters:
            if "execution_type" in filters:
                query = query.where(AgentDefinitionDB.execution_type == filters["execution_type"])
            if "domain_type" in filters:
                query = query.where(AgentDefinitionDB.domain_type == filters["domain_type"])
        
        result = await self.session.execute(query)
        return result.scalar()
    
    # ========== 版本管理 ==========
    
    async def _create_version(
        self,
        agent_id: str,
        agent: AgentDefinition,
        change_log: str
    ):
        """创建版本记录"""
        version = AgentVersionDB(
            agent_id=agent_id,
            version=agent.version,
            definition_snapshot=agent.model_dump(),
            change_log=change_log,
            created_by=agent.author
        )
        self.session.add(version)
        await self.session.commit()
    
    async def get_version(self, agent_id: str, version: str) -> Optional[AgentDefinition]:
        """获取特定版本"""
        result = await self.session.execute(
            select(AgentVersionDB)
            .where(AgentVersionDB.agent_id == agent_id)
            .where(AgentVersionDB.version == version)
        )
        db_version = result.scalar_one_or_none()
        
        if db_version is None:
            return None
        
        return AgentDefinition(**db_version.definition_snapshot)
    
    async def list_versions(self, agent_id: str) -> List[Dict[str, Any]]:
        """列出所有版本"""
        result = await self.session.execute(
            select(AgentVersionDB)
            .where(AgentVersionDB.agent_id == agent_id)
            .order_by(AgentVersionDB.created_at.desc())
        )
        
        return [
            {
                "version": v.version,
                "change_log": v.change_log,
                "created_by": v.created_by,
                "created_at": v.created_at.isoformat()
            }
            for v in result.scalars()
        ]
    
    async def rollback_to_version(self, agent_id: str, version: str) -> AgentDefinition:
        """回滚到特定版本"""
        old_version = await self.get_version(agent_id, version)
        if old_version is None:
            raise ValueError(f"版本不存在: {agent_id}@{version}")
        
        # 更新版本号
        old_version.version = self._increment_version(old_version.version)
        
        return await self.update(
            agent_id,
            old_version,
            f"Rollback to version {version}"
        )
    
    # ========== 搜索 ==========
    
    async def search(self, query: str, limit: int = 20) -> List[AgentDefinition]:
        """搜索 Agent"""
        result = await self.session.execute(
            select(AgentDefinitionDB)
            .where(AgentDefinitionDB.is_active == True)
            .where(
                (AgentDefinitionDB.name.ilike(f"%{query}%")) |
                (AgentDefinitionDB.description.ilike(f"%{query}%"))
            )
            .limit(limit)
        )
        return [self._to_domain(db_agent) for db_agent in result.scalars()]
    
    # ========== 辅助方法 ==========
    
    def _to_domain(self, db_agent: AgentDefinitionDB) -> AgentDefinition:
        """转换为领域模型"""
        from ...definitions import (
            BackgroundInstruction, OutputInstruction, UserInstruction,
            ModelConfig, ToolReference
        )
        
        return AgentDefinition(
            agent_id=db_agent.agent_id,
            name=db_agent.name,
            description=db_agent.description,
            version=db_agent.version,
            execution_type=AgentExecutionType(db_agent.execution_type),
            domain_type=AgentDomainType(db_agent.domain_type),
            background_instruction=BackgroundInstruction(**db_agent.background_instruction),
            output_instruction=OutputInstruction(**db_agent.output_instruction),
            user_instruction=UserInstruction(**db_agent.user_instruction),
            model_config=ModelConfig(**db_agent.model_config),
            tool_references=[ToolReference(**t) for t in db_agent.tool_references],
            input_schema=db_agent.input_schema,
            output_schema=db_agent.output_schema,
            file_operations=db_agent.file_operations,
            tags=db_agent.tags,
            author=db_agent.author
        )
    
    def _increment_version(self, version: str) -> str:
        """递增版本号"""
        parts = version.split('.')
        parts[-1] = str(int(parts[-1]) + 1)
        return '.'.join(parts)
```

### 4.3 Tool Repository

```python
# etf_common/agent_framework/storage/repositories/tool_repository.py

from typing import Optional, List, Dict, Any

from sqlalchemy import select, update, delete, func
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.db_models import ToolDefinitionDB, ToolVersionDB, ToolDependencyDB
from ...tools import ToolDefinition, ToolCategory
from .base import BaseRepository


class ToolRepository(BaseRepository[ToolDefinition]):
    """Tool 定义 Repository"""
    
    def __init__(self, session: AsyncSession):
        self.session = session
    
    async def create(self, tool: ToolDefinition) -> ToolDefinition:
        """创建 Tool 定义"""
        db_tool = ToolDefinitionDB(
            tool_id=tool.tool_id,
            name=tool.name,
            alias=tool.alias,
            description=tool.description,
            category=tool.category.value,
            input_schema=tool.input_schema,
            output_schema=tool.output_schema,
            is_async=tool.is_async,
            timeout_seconds=tool.timeout,
            retry_count=tool.retry_count,
            requires_auth=tool.requires_auth,
            rate_limit_per_minute=tool.rate_limit,
            cost_estimate=tool.cost_estimate,
            implementation_type="custom",
            examples=tool.examples,
            tags=[],
            is_active=True,
            is_system=False
        )
        
        self.session.add(db_tool)
        await self.session.commit()
        await self.session.refresh(db_tool)
        
        return tool
    
    async def get(self, tool_id: str) -> Optional[ToolDefinition]:
        """获取 Tool 定义"""
        result = await self.session.execute(
            select(ToolDefinitionDB).where(ToolDefinitionDB.tool_id == tool_id)
        )
        db_tool = result.scalar_one_or_none()
        
        if db_tool is None:
            return None
        
        return self._to_domain(db_tool)
    
    async def get_by_alias(self, alias: str) -> Optional[ToolDefinition]:
        """通过别名获取 Tool"""
        result = await self.session.execute(
            select(ToolDefinitionDB).where(ToolDefinitionDB.alias == alias)
        )
        db_tool = result.scalar_one_or_none()
        
        if db_tool is None:
            return None
        
        return self._to_domain(db_tool)
    
    async def update(self, tool_id: str, tool: ToolDefinition, change_log: str = None) -> ToolDefinition:
        """更新 Tool 定义"""
        await self.session.execute(
            update(ToolDefinitionDB)
            .where(ToolDefinitionDB.tool_id == tool_id)
            .values(
                name=tool.name,
                alias=tool.alias,
                description=tool.description,
                category=tool.category.value,
                input_schema=tool.input_schema,
                output_schema=tool.output_schema,
                is_async=tool.is_async,
                timeout_seconds=tool.timeout,
                retry_count=tool.retry_count,
                requires_auth=tool.requires_auth,
                rate_limit_per_minute=tool.rate_limit,
                cost_estimate=tool.cost_estimate,
                examples=tool.examples
            )
        )
        await self.session.commit()
        
        return tool
    
    async def delete(self, tool_id: str) -> bool:
        """删除 Tool 定义（软删除）"""
        result = await self.session.execute(
            update(ToolDefinitionDB)
            .where(ToolDefinitionDB.tool_id == tool_id)
            .values(is_active=False)
        )
        await self.session.commit()
        return result.rowcount > 0
    
    async def list(
        self,
        filters: Dict[str, Any] = None,
        limit: int = 100,
        offset: int = 0
    ) -> List[ToolDefinition]:
        """列出 Tool 定义"""
        query = select(ToolDefinitionDB).where(ToolDefinitionDB.is_active == True)
        
        if filters:
            if "category" in filters:
                query = query.where(ToolDefinitionDB.category == filters["category"])
            if "is_system" in filters:
                query = query.where(ToolDefinitionDB.is_system == filters["is_system"])
        
        query = query.order_by(ToolDefinitionDB.created_at.desc())
        query = query.limit(limit).offset(offset)
        
        result = await self.session.execute(query)
        return [self._to_domain(db_tool) for db_tool in result.scalars()]
    
    async def list_by_category(self, category: ToolCategory) -> List[ToolDefinition]:
        """按分类列出 Tool"""
        return await self.list(filters={"category": category.value})
    
    async def count(self, filters: Dict[str, Any] = None) -> int:
        """计数"""
        query = select(func.count(ToolDefinitionDB.id)).where(ToolDefinitionDB.is_active == True)
        
        if filters and "category" in filters:
            query = query.where(ToolDefinitionDB.category == filters["category"])
        
        result = await self.session.execute(query)
        return result.scalar()
    
    # ========== 依赖管理 ==========
    
    async def add_dependency(
        self,
        tool_id: str,
        depends_on: str,
        dependency_type: str = "required"
    ):
        """添加依赖关系"""
        dep = ToolDependencyDB(
            tool_id=tool_id,
            depends_on_tool_id=depends_on,
            dependency_type=dependency_type
        )
        self.session.add(dep)
        await self.session.commit()
    
    async def get_dependencies(self, tool_id: str) -> List[str]:
        """获取依赖列表"""
        result = await self.session.execute(
            select(ToolDependencyDB.depends_on_tool_id)
            .where(ToolDependencyDB.tool_id == tool_id)
        )
        return [row[0] for row in result]
    
    async def get_dependents(self, tool_id: str) -> List[str]:
        """获取被依赖列表"""
        result = await self.session.execute(
            select(ToolDependencyDB.tool_id)
            .where(ToolDependencyDB.depends_on_tool_id == tool_id)
        )
        return [row[0] for row in result]
    
    def _to_domain(self, db_tool: ToolDefinitionDB) -> ToolDefinition:
        """转换为领域模型"""
        return ToolDefinition(
            tool_id=db_tool.tool_id,
            name=db_tool.name,
            alias=db_tool.alias,
            description=db_tool.description,
            category=ToolCategory(db_tool.category),
            input_schema=db_tool.input_schema,
            output_schema=db_tool.output_schema,
            is_async=db_tool.is_async,
            timeout=db_tool.timeout_seconds,
            retry_count=db_tool.retry_count,
            requires_auth=db_tool.requires_auth,
            rate_limit=db_tool.rate_limit_per_minute,
            cost_estimate=float(db_tool.cost_estimate) if db_tool.cost_estimate else 0.0,
            examples=db_tool.examples or []
        )
```

### 4.4 Workflow Repository

```python
# etf_common/agent_framework/storage/repositories/workflow_repository.py

from typing import Optional, List, Dict, Any

from sqlalchemy import select, update, delete, func
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.db_models import WorkflowDefinitionDB, WorkflowVersionDB, WorkflowAgentMappingDB
from ...workflow import WorkflowDefinition, WorkflowNode, WorkflowEdge
from .base import BaseRepository


class WorkflowRepository(BaseRepository[WorkflowDefinition]):
    """Workflow 定义 Repository"""
    
    def __init__(self, session: AsyncSession):
        self.session = session
    
    async def create(self, workflow: WorkflowDefinition) -> WorkflowDefinition:
        """创建 Workflow 定义"""
        db_workflow = WorkflowDefinitionDB(
            workflow_id=workflow.workflow_id,
            name=workflow.name,
            description=workflow.description,
            version=workflow.version,
            nodes=[n.model_dump() for n in workflow.nodes],
            edges=[e.model_dump() for e in workflow.edges],
            entry_node=workflow.entry_node,
            exit_nodes=workflow.exit_nodes,
            global_context=workflow.global_context,
            global_tools=workflow.global_tools,
            workspace_path=workflow.workspace_path,
            output_path=workflow.output_path,
            tags=workflow.tags,
            author=workflow.author,
            is_active=True,
            is_system=False
        )
        
        self.session.add(db_workflow)
        await self.session.commit()
        await self.session.refresh(db_workflow)
        
        # 创建 Agent 映射
        await self._create_agent_mappings(workflow)
        
        # 创建初始版本
        await self._create_version(workflow.workflow_id, workflow, "Initial version")
        
        return workflow
    
    async def get(self, workflow_id: str) -> Optional[WorkflowDefinition]:
        """获取 Workflow 定义"""
        result = await self.session.execute(
            select(WorkflowDefinitionDB).where(WorkflowDefinitionDB.workflow_id == workflow_id)
        )
        db_workflow = result.scalar_one_or_none()
        
        if db_workflow is None:
            return None
        
        return self._to_domain(db_workflow)
    
    async def update(
        self,
        workflow_id: str,
        workflow: WorkflowDefinition,
        change_log: str = None
    ) -> WorkflowDefinition:
        """更新 Workflow 定义"""
        await self.session.execute(
            update(WorkflowDefinitionDB)
            .where(WorkflowDefinitionDB.workflow_id == workflow_id)
            .values(
                name=workflow.name,
                description=workflow.description,
                version=workflow.version,
                nodes=[n.model_dump() for n in workflow.nodes],
                edges=[e.model_dump() for e in workflow.edges],
                entry_node=workflow.entry_node,
                exit_nodes=workflow.exit_nodes,
                global_context=workflow.global_context,
                global_tools=workflow.global_tools,
                workspace_path=workflow.workspace_path,
                output_path=workflow.output_path,
                tags=workflow.tags
            )
        )
        
        # 更新 Agent 映射
        await self._delete_agent_mappings(workflow_id)
        await self._create_agent_mappings(workflow)
        
        await self.session.commit()
        
        # 创建新版本
        await self._create_version(workflow_id, workflow, change_log or "Updated")
        
        return workflow
    
    async def delete(self, workflow_id: str) -> bool:
        """删除 Workflow 定义（软删除）"""
        result = await self.session.execute(
            update(WorkflowDefinitionDB)
            .where(WorkflowDefinitionDB.workflow_id == workflow_id)
            .values(is_active=False)
        )
        await self.session.commit()
        return result.rowcount > 0
    
    async def list(
        self,
        filters: Dict[str, Any] = None,
        limit: int = 100,
        offset: int = 0
    ) -> List[WorkflowDefinition]:
        """列出 Workflow 定义"""
        query = select(WorkflowDefinitionDB).where(WorkflowDefinitionDB.is_active == True)
        
        if filters:
            if "tags" in filters:
                query = query.where(WorkflowDefinitionDB.tags.contains(filters["tags"]))
            if "is_system" in filters:
                query = query.where(WorkflowDefinitionDB.is_system == filters["is_system"])
        
        query = query.order_by(WorkflowDefinitionDB.created_at.desc())
        query = query.limit(limit).offset(offset)
        
        result = await self.session.execute(query)
        return [self._to_domain(db_wf) for db_wf in result.scalars()]
    
    async def count(self, filters: Dict[str, Any] = None) -> int:
        """计数"""
        query = select(func.count(WorkflowDefinitionDB.id)).where(WorkflowDefinitionDB.is_active == True)
        result = await self.session.execute(query)
        return result.scalar()
    
    # ========== Agent 映射管理 ==========
    
    async def _create_agent_mappings(self, workflow: WorkflowDefinition):
        """创建 Agent 映射"""
        for node in workflow.nodes:
            if node.agent_id:
                mapping = WorkflowAgentMappingDB(
                    workflow_id=workflow.workflow_id,
                    node_id=node.node_id,
                    agent_id=node.agent_id,
                    config_overrides={
                        "background_override": node.background_override,
                        "output_override": node.output_override,
                        "user_override": node.user_override,
                        "model_override": node.model_override
                    }
                )
                self.session.add(mapping)
        await self.session.commit()
    
    async def _delete_agent_mappings(self, workflow_id: str):
        """删除 Agent 映射"""
        await self.session.execute(
            delete(WorkflowAgentMappingDB)
            .where(WorkflowAgentMappingDB.workflow_id == workflow_id)
        )
    
    async def get_workflow_agents(self, workflow_id: str) -> List[str]:
        """获取工作流使用的所有 Agent"""
        result = await self.session.execute(
            select(WorkflowAgentMappingDB.agent_id)
            .where(WorkflowAgentMappingDB.workflow_id == workflow_id)
        )
        return list(set(row[0] for row in result))
    
    async def get_workflows_using_agent(self, agent_id: str) -> List[str]:
        """获取使用特定 Agent 的所有工作流"""
        result = await self.session.execute(
            select(WorkflowAgentMappingDB.workflow_id)
            .where(WorkflowAgentMappingDB.agent_id == agent_id)
        )
        return list(set(row[0] for row in result))
    
    # ========== 版本管理 ==========
    
    async def _create_version(
        self,
        workflow_id: str,
        workflow: WorkflowDefinition,
        change_log: str
    ):
        """创建版本记录"""
        version = WorkflowVersionDB(
            workflow_id=workflow_id,
            version=workflow.version,
            definition_snapshot=workflow.model_dump(),
            change_log=change_log,
            created_by=workflow.author
        )
        self.session.add(version)
        await self.session.commit()
    
    async def get_version(self, workflow_id: str, version: str) -> Optional[WorkflowDefinition]:
        """获取特定版本"""
        result = await self.session.execute(
            select(WorkflowVersionDB)
            .where(WorkflowVersionDB.workflow_id == workflow_id)
            .where(WorkflowVersionDB.version == version)
        )
        db_version = result.scalar_one_or_none()
        
        if db_version is None:
            return None
        
        return WorkflowDefinition(**db_version.definition_snapshot)
    
    async def list_versions(self, workflow_id: str) -> List[Dict[str, Any]]:
        """列出所有版本"""
        result = await self.session.execute(
            select(WorkflowVersionDB)
            .where(WorkflowVersionDB.workflow_id == workflow_id)
            .order_by(WorkflowVersionDB.created_at.desc())
        )
        
        return [
            {
                "version": v.version,
                "change_log": v.change_log,
                "created_by": v.created_by,
                "created_at": v.created_at.isoformat()
            }
            for v in result.scalars()
        ]
    
    def _to_domain(self, db_wf: WorkflowDefinitionDB) -> WorkflowDefinition:
        """转换为领域模型"""
        return WorkflowDefinition(
            workflow_id=db_wf.workflow_id,
            name=db_wf.name,
            description=db_wf.description,
            version=db_wf.version,
            nodes=[WorkflowNode(**n) for n in db_wf.nodes],
            edges=[WorkflowEdge(**e) for e in db_wf.edges],
            entry_node=db_wf.entry_node,
            exit_nodes=db_wf.exit_nodes,
            global_context=db_wf.global_context,
            global_tools=db_wf.global_tools,
            workspace_path=db_wf.workspace_path,
            output_path=db_wf.output_path,
            tags=db_wf.tags,
            author=db_wf.author
        )
```

---

## 5. 统一存储服务

```python
# etf_common/agent_framework/storage/storage_service.py

from typing import Dict, Any, Optional
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

from .oss_client import OSSClient, AliyunOSSClient, MinIOClient
from .repositories.agent_repository import AgentRepository
from .repositories.tool_repository import ToolRepository
from .repositories.workflow_repository import WorkflowRepository
from .repositories.task_repository import TaskRepository
from .repositories.trace_repository import TraceRepository


@dataclass
class StorageConfig:
    """存储配置"""
    
    # PostgreSQL
    postgres_url: str
    postgres_pool_size: int = 10
    
    # OSS
    oss_provider: str = "minio"  # minio, aliyun
    oss_endpoint: str = "localhost:9000"
    oss_access_key: str = ""
    oss_secret_key: str = ""
    oss_bucket: str = "agent-framework"
    oss_secure: bool = False
    
    # Redis (可选)
    redis_url: Optional[str] = None


class StorageService:
    """
    统一存储服务
    
    提供所有存储操作的统一入口
    """
    
    def __init__(self, config: StorageConfig):
        self.config = config
        
        # 初始化 PostgreSQL
        self.engine = create_async_engine(
            config.postgres_url,
            pool_size=config.postgres_pool_size,
            echo=False
        )
        self.session_factory = async_sessionmaker(
            self.engine,
            class_=AsyncSession,
            expire_on_commit=False
        )
        
        # 初始化 OSS
        if config.oss_provider == "aliyun":
            self.oss = AliyunOSSClient(
                access_key_id=config.oss_access_key,
                access_key_secret=config.oss_secret_key,
                endpoint=config.oss_endpoint,
                bucket_name=config.oss_bucket
            )
        else:  # minio
            self.oss = MinIOClient(
                endpoint=config.oss_endpoint,
                access_key=config.oss_access_key,
                secret_key=config.oss_secret_key,
                bucket_name=config.oss_bucket,
                secure=config.oss_secure
            )
        
        # 初始化 Redis（如果配置）
        self.redis = None
        if config.redis_url:
            import redis.asyncio as redis
            self.redis = redis.from_url(config.redis_url)
    
    # ========== Repository 访问 ==========
    
    def get_session(self) -> AsyncSession:
        """获取数据库会话"""
        return self.session_factory()
    
    async def agents(self) -> AgentRepository:
        """获取 Agent Repository"""
        session = self.get_session()
        return AgentRepository(session)
    
    async def tools(self) -> ToolRepository:
        """获取 Tool Repository"""
        session = self.get_session()
        return ToolRepository(session)
    
    async def workflows(self) -> WorkflowRepository:
        """获取 Workflow Repository"""
        session = self.get_session()
        return WorkflowRepository(session)
    
    async def tasks(self) -> TaskRepository:
        """获取 Task Repository"""
        session = self.get_session()
        return TaskRepository(session)
    
    async def traces(self) -> TraceRepository:
        """获取 Trace Repository"""
        session = self.get_session()
        return TraceRepository(session)
    
    # ========== OSS 访问 ==========
    
    def get_oss(self) -> OSSClient:
        """获取 OSS 客户端"""
        return self.oss
    
    # ========== 便捷方法 ==========
    
    async def save_workspace_file(
        self,
        task_id: str,
        file_path: str,
        content: str | bytes
    ) -> str:
        """保存工作空间文件到 OSS"""
        oss_key = f"workspaces/{task_id}/{file_path}"
        
        if isinstance(content, str):
            return await self.oss.put_text(oss_key, content)
        else:
            return await self.oss.put_object(oss_key, content)
    
    async def get_workspace_file(self, task_id: str, file_path: str) -> str:
        """从 OSS 获取工作空间文件"""
        oss_key = f"workspaces/{task_id}/{file_path}"
        return await self.oss.get_text(oss_key)
    
    async def save_trace_data(
        self,
        trace_id: str,
        data_type: str,
        data_id: str,
        data: Any
    ) -> str:
        """保存追踪数据到 OSS"""
        oss_key = f"traces/{trace_id}/{data_type}/{data_id}.json"
        return await self.oss.put_json(oss_key, data)
    
    async def get_trace_data(
        self,
        trace_id: str,
        data_type: str,
        data_id: str
    ) -> Any:
        """从 OSS 获取追踪数据"""
        oss_key = f"traces/{trace_id}/{data_type}/{data_id}.json"
        return await self.oss.get_json(oss_key)
    
    # ========== 缓存操作（如果有 Redis）==========
    
    async def cache_get(self, key: str) -> Optional[str]:
        """获取缓存"""
        if self.redis is None:
            return None
        return await self.redis.get(key)
    
    async def cache_set(self, key: str, value: str, ttl: int = 3600):
        """设置缓存"""
        if self.redis is None:
            return
        await self.redis.set(key, value, ex=ttl)
    
    async def cache_delete(self, key: str):
        """删除缓存"""
        if self.redis is None:
            return
        await self.redis.delete(key)
    
    # ========== 健康检查 ==========
    
    async def health_check(self) -> Dict[str, Any]:
        """健康检查"""
        status = {"postgres": False, "oss": False, "redis": False}
        
        # 检查 PostgreSQL
        try:
            async with self.engine.connect() as conn:
                await conn.execute("SELECT 1")
            status["postgres"] = True
        except Exception as e:
            status["postgres_error"] = str(e)
        
        # 检查 OSS
        try:
            await self.oss.list_objects("", max_keys=1)
            status["oss"] = True
        except Exception as e:
            status["oss_error"] = str(e)
        
        # 检查 Redis
        if self.redis:
            try:
                await self.redis.ping()
                status["redis"] = True
            except Exception as e:
                status["redis_error"] = str(e)
        else:
            status["redis"] = None  # 未配置
        
        return status
    
    # ========== 清理 ==========
    
    async def close(self):
        """关闭连接"""
        await self.engine.dispose()
        if self.redis:
            await self.redis.close()
```

---

## 6. 使用示例

```python
# 示例：使用 StorageService

from etf_common.agent_framework.storage import StorageService, StorageConfig


async def main():
    # 1. 初始化存储服务
    storage = StorageService(StorageConfig(
        postgres_url="postgresql+asyncpg://user:pass@localhost/agent_framework",
        oss_provider="minio",
        oss_endpoint="localhost:9000",
        oss_access_key="minioadmin",
        oss_secret_key="minioadmin",
        oss_bucket="agent-framework",
        redis_url="redis://localhost:6379"
    ))
    
    # 2. 健康检查
    health = await storage.health_check()
    print(f"存储状态: {health}")
    
    # 3. Agent CRUD
    agent_repo = await storage.agents()
    
    # 创建 Agent
    from etf_common.agent_framework.definitions import AgentDefinition, ...
    
    agent = AgentDefinition(
        agent_id="financial_analyst_v1",
        name="金融分析师",
        description="专业的金融分析 Agent",
        execution_type=AgentExecutionType.REASONING_EXECUTOR,
        domain_type=AgentDomainType.FINANCIAL_ANALYSIS,
        # ... 其他配置
    )
    
    created_agent = await agent_repo.create(agent)
    print(f"创建 Agent: {created_agent.agent_id}")
    
    # 查询 Agent
    agents = await agent_repo.list(
        filters={"domain_type": "financial_analysis"},
        limit=10
    )
    print(f"找到 {len(agents)} 个金融分析 Agent")
    
    # 更新 Agent
    agent.description = "更新后的描述"
    agent.version = "1.1.0"
    updated = await agent_repo.update(agent.agent_id, agent, "更新描述")
    
    # 获取版本历史
    versions = await agent_repo.list_versions(agent.agent_id)
    print(f"版本历史: {versions}")
    
    # 4. Tool CRUD
    tool_repo = await storage.tools()
    
    tools = await tool_repo.list(
        filters={"category": "financial_data"},
        limit=10
    )
    print(f"找到 {len(tools)} 个金融数据工具")
    
    # 5. Workflow CRUD
    workflow_repo = await storage.workflows()
    
    # 查询使用特定 Agent 的工作流
    workflows = await workflow_repo.get_workflows_using_agent("financial_analyst_v1")
    print(f"使用该 Agent 的工作流: {workflows}")
    
    # 6. OSS 文件操作
    oss = storage.get_oss()
    
    # 保存文件
    await storage.save_workspace_file(
        task_id="task_001",
        file_path="output/report.md",
        content="# 分析报告\n..."
    )
    
    # 获取文件
    content = await storage.get_workspace_file(
        task_id="task_001",
        file_path="output/report.md"
    )
    
    # 7. 缓存操作
    await storage.cache_set("llm_cache:hash123", "cached_response", ttl=3600)
    cached = await storage.cache_get("llm_cache:hash123")
    
    # 8. 清理
    await storage.close()


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
```

---

## 7. 目录结构

```
etf_common/agent_framework/storage/
├── __init__.py
├── storage_service.py              # 统一存储服务
├── oss_client.py                   # OSS 客户端抽象
├── models/
│   ├── __init__.py
│   └── db_models.py                # SQLAlchemy ORM 模型
├── repositories/
│   ├── __init__.py
│   ├── base.py                     # Repository 基类
│   ├── agent_repository.py         # Agent CRUD
│   ├── tool_repository.py          # Tool CRUD
│   ├── workflow_repository.py      # Workflow CRUD
│   ├── task_repository.py          # Task CRUD
│   └── trace_repository.py         # Trace CRUD
├── migrations/                     # Alembic 数据库迁移
│   ├── env.py
│   ├── versions/
│   └── alembic.ini
└── scripts/
    ├── init_db.py                  # 初始化数据库
    └── seed_data.py                # 种子数据
```

---

## 8. LangGraph 检查点存储集成

### 8.1 检查点存储模块

检查点存储位于 `storage/checkpointers/` 模块，使用统一的数据库和 Redis 客户端：

```
storage/checkpointers/
├── __init__.py              # 导出所有检查点类
├── base.py                  # BaseCheckpointSaver 基类
├── memory_saver.py          # 内存检查点（开发/测试）
├── redis_saver.py           # Redis 检查点（分布式部署）
├── postgres_saver.py        # PostgreSQL 检查点（长期持久化）
├── file_saver.py            # 文件系统检查点（本地调试）
└── factory.py               # CheckpointerFactory 工厂类
```

### 8.2 统一配置管理

```python
# storage/config.py

class CheckpointerType(str, Enum):
    MEMORY = "memory"
    REDIS = "redis"
    POSTGRESQL = "postgresql"
    FILE = "file"

class CheckpointStorageConfig(BaseModel):
    type: CheckpointerType = CheckpointerType.MEMORY
    redis_prefix: str = "langgraph:checkpoint:"
    redis_ttl: Optional[int] = None
    postgres_table: str = "langgraph_checkpoints"
    file_path: str = "/tmp/langgraph_checkpoints"
    serializer: str = "json"

class StorageConfig(BaseModel):
    postgres: PostgreSQLConfig
    redis: RedisConfig
    oss: OSSConfig
    checkpoint: CheckpointStorageConfig  # 检查点配置
    trace: TraceStorageConfig            # 追踪存储配置
    
    @classmethod
    def from_env(cls) -> "StorageConfig":
        """从环境变量读取配置"""
        ...
```

### 8.3 检查点存储使用统一客户端

**Redis 检查点**使用注入的 `RedisClient`：

```python
# storage/checkpointers/redis_saver.py

class RedisCheckpointSaver(BaseCheckpointSaver):
    def __init__(self, redis_client: RedisClient, ...):
        self._client = redis_client  # 注入，不自己创建
        
    def put(self, config, checkpoint, metadata):
        # 使用同步客户端（LangGraph 要求）
        sync_client = self._client.sync_client
        pipe = sync_client.pipeline()
        # ...
```

**PostgreSQL 检查点**使用注入的 `AsyncDatabaseManager`：

```python
# storage/checkpointers/postgres_saver.py

class PostgresCheckpointSaver(BaseCheckpointSaver):
    def __init__(self, db_manager: AsyncDatabaseManager, ...):
        self.db_manager = db_manager  # 注入，不自己创建
        
    async def aput(self, config, checkpoint, metadata):
        # 使用原生 asyncpg 查询
        await self.db_manager.execute_raw(upsert_sql, ...)
```

### 8.4 导入方式

检查点存储直接从 `storage/checkpointers/` 导入：

```python
# 从 storage 模块导入
from storage.checkpointers import (
    BaseCheckpointSaver,
    RedisCheckpointSaver,
    PostgresCheckpointSaver,
    FileCheckpointSaver,
    SimpleMemoryCheckpointSaver,
    CheckpointerFactory,
)
from storage.config import CheckpointerType, CheckpointStorageConfig

# 或者从 core 模块导入（重新导出）
from core import (
    CheckpointerType,
    CheckpointerConfig,  # 别名 CheckpointStorageConfig
    BaseCheckpointSaver,
    CheckpointerFactory,
)
```

---

## 9. 总结

### 9.1 存储职责分工

| 数据类型 | 存储位置 | 说明 |
|----------|----------|------|
| Agent/Tool/Workflow 定义 | PostgreSQL | 结构化数据、版本管理、关系查询 |
| Task 元数据 | PostgreSQL | 任务状态、索引查询 |
| 执行追踪元数据 | PostgreSQL | Trace 概要、Span 信息 |
| LLM/Tool 调用详情 | PostgreSQL + OSS | 元数据在 PG，大内容在 OSS |
| 工作空间文件 | OSS | 输入/输出/草稿/上下文 |
| 归档文件 | OSS (Cold Storage) | tar.gz 压缩包 |
| LLM 响应缓存 | Redis | TTL 自动过期 |
| LangGraph 检查点 | Redis / PostgreSQL / File | 可配置，支持分布式 |

### 9.2 关键改进

1. **明确存储介质**：PostgreSQL + OSS + Redis 三层架构
2. **完整 CRUD**：Agent/Tool/Workflow 的完整增删改查
3. **版本管理**：所有定义都支持版本历史和回滚
4. **关系管理**：Workflow-Agent 映射、Tool 依赖关系
5. **大数据分离**：元数据在 PG，大内容在 OSS
6. **统一服务**：StorageService 提供统一入口
7. **统一客户端**：`AsyncDatabaseManager` 和 `RedisClient` 是唯一的客户端实现
8. **检查点集成**：LangGraph 检查点使用统一客户端，支持多种存储后端
9. **配置驱动**：通过 `StorageConfig` 和环境变量统一管理所有存储配置

### 9.3 架构图

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           Storage 模块架构                                   │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │                         storage/config.py                           │    │
│  │  StorageConfig, PostgreSQLConfig, RedisConfig, CheckpointStorageConfig   │
│  └─────────────────────────────────────────────────────────────────────┘    │
│                                    │                                         │
│          ┌─────────────────────────┼─────────────────────────┐              │
│          │                         │                         │              │
│          ▼                         ▼                         ▼              │
│  ┌───────────────┐       ┌───────────────┐       ┌───────────────┐         │
│  │AsyncDatabase  │       │  RedisClient  │       │  OSSClient    │         │
│  │Manager        │       │ (async+sync)  │       │               │         │
│  └───────────────┘       └───────────────┘       └───────────────┘         │
│          │                         │                         │              │
│          │                         │                         │              │
│          ▼                         ▼                         ▼              │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │                      storage/checkpointers/                         │    │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌──────────┐   │    │
│  │  │PostgresSaver│  │ RedisSaver  │  │ FileSaver   │  │MemorySaver│  │    │
│  │  └─────────────┘  └─────────────┘  └─────────────┘  └──────────┘   │    │
│  │                              │                                      │    │
│  │                    CheckpointerFactory                              │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

