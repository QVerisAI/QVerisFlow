"""Initial schema - Agent Framework tables

Revision ID: 0001
Revises:
Create Date: 2026-01-21

创建所有框架核心表：
- agent_definitions: Agent 定义
- workflow_definitions: 工作流定义
- workflow_executions: 工作流执行记录
- task_executions: 任务执行记录
- tool_call_logs: 工具调用日志
- feedbacks: 执行反馈
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers
revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 创建枚举类型（PostgreSQL）
    # 在 SQLite 中会自动降级为 VARCHAR

    agent_status = sa.Enum(
        "draft", "active", "inactive", "archived", name="agentstatus"
    )
    task_status = sa.Enum(
        "pending",
        "running",
        "completed",
        "failed",
        "cancelled",
        "paused",
        name="taskstatus",
    )
    workflow_status = sa.Enum(
        "pending",
        "running",
        "completed",
        "failed",
        "cancelled",
        "paused",
        name="workflowstatus",
    )

    # ==================== agent_definitions ====================
    op.create_table(
        "agent_definitions",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("agent_id", sa.String(128), nullable=False, index=True),
        sa.Column("version", sa.String(32), nullable=False, server_default="1.0.0"),
        sa.Column("name", sa.String(256), nullable=False),
        sa.Column("description", sa.Text),
        sa.Column("definition_json", sa.JSON, nullable=False),
        sa.Column("status", agent_status, server_default="draft"),
        sa.Column("model_name", sa.String(128)),
        sa.Column("max_iterations", sa.Integer),
        sa.Column("tags", sa.JSON, server_default="[]"),
        sa.Column("author", sa.String(128)),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
        sa.Column(
            "updated_at",
            sa.DateTime,
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
        ),
    )

    # 复合索引
    op.create_index("ix_agent_id_version", "agent_definitions", ["agent_id", "version"])
    op.create_index("ix_agent_status", "agent_definitions", ["status"])

    # ==================== workflow_definitions ====================
    op.create_table(
        "workflow_definitions",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("workflow_id", sa.String(128), nullable=False, index=True),
        sa.Column("version", sa.String(32), nullable=False, server_default="1.0.0"),
        sa.Column("name", sa.String(256), nullable=False),
        sa.Column("description", sa.Text),
        sa.Column("definition_json", sa.JSON, nullable=False),
        sa.Column("node_count", sa.Integer, server_default="0"),
        sa.Column("edge_count", sa.Integer, server_default="0"),
        sa.Column("is_active", sa.Boolean, server_default="true"),
        sa.Column("tags", sa.JSON, server_default="[]"),
        sa.Column("author", sa.String(128)),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
        sa.Column(
            "updated_at",
            sa.DateTime,
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
        ),
    )

    op.create_index(
        "ix_workflow_id_version", "workflow_definitions", ["workflow_id", "version"]
    )

    # ==================== workflow_executions ====================
    op.create_table(
        "workflow_executions",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column(
            "workflow_definition_id",
            sa.String(64),
            sa.ForeignKey("workflow_definitions.id"),
        ),
        sa.Column("status", workflow_status, server_default="pending"),
        sa.Column("initial_context", sa.JSON),
        sa.Column("final_output", sa.JSON),
        sa.Column("error", sa.Text),
        sa.Column("node_results", sa.JSON, server_default="{}"),
        sa.Column("total_duration_ms", sa.Float, server_default="0.0"),
        sa.Column("checkpoint_id", sa.String(128)),
        sa.Column("started_at", sa.DateTime),
        sa.Column("completed_at", sa.DateTime),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
    )

    op.create_index("ix_workflow_exec_status", "workflow_executions", ["status"])
    op.create_index("ix_workflow_exec_started", "workflow_executions", ["started_at"])

    # ==================== task_executions ====================
    op.create_table(
        "task_executions",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("task_id", sa.String(128), nullable=False, index=True),
        sa.Column(
            "agent_definition_id", sa.String(64), sa.ForeignKey("agent_definitions.id")
        ),
        sa.Column("task_description", sa.Text),
        sa.Column("input_data", sa.JSON),
        sa.Column("status", task_status, server_default="pending"),
        sa.Column("result", sa.JSON),
        sa.Column("error", sa.Text),
        sa.Column("duration_ms", sa.Float, server_default="0.0"),
        sa.Column("iterations", sa.Integer, server_default="0"),
        sa.Column("token_usage", sa.Integer, server_default="0"),
        sa.Column("verification_passed", sa.Boolean),
        sa.Column("verification_score", sa.Float),
        sa.Column("verification_feedback", sa.Text),
        sa.Column("workspace_path", sa.String(512)),
        sa.Column("output_files", sa.JSON, server_default="[]"),
        sa.Column("started_at", sa.DateTime),
        sa.Column("completed_at", sa.DateTime),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
    )

    op.create_index("ix_task_exec_status", "task_executions", ["status"])
    op.create_index("ix_task_exec_started", "task_executions", ["started_at"])

    # ==================== tool_call_logs ====================
    op.create_table(
        "tool_call_logs",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column(
            "task_execution_id", sa.String(64), sa.ForeignKey("task_executions.id")
        ),
        sa.Column("tool_id", sa.String(128), nullable=False, index=True),
        sa.Column("tool_name", sa.String(256)),
        sa.Column("input_params", sa.JSON),
        sa.Column("output", sa.JSON),
        sa.Column("error", sa.Text),
        sa.Column("phase", sa.String(32)),
        sa.Column("duration_ms", sa.Float, server_default="0.0"),
        sa.Column("timestamp", sa.DateTime, server_default=sa.func.now()),
    )

    op.create_index("ix_tool_call_tool_id", "tool_call_logs", ["tool_id"])
    op.create_index("ix_tool_call_timestamp", "tool_call_logs", ["timestamp"])

    # ==================== feedbacks ====================
    op.create_table(
        "feedbacks",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("agent_id", sa.String(128), nullable=False, index=True),
        sa.Column("task_id", sa.String(128), index=True),
        sa.Column(
            "task_execution_id",
            sa.String(64),
            sa.ForeignKey("task_executions.id"),
            nullable=True,
        ),
        sa.Column("task_description", sa.Text),
        sa.Column("success", sa.Boolean, nullable=False),
        sa.Column("result_summary", sa.Text),
        sa.Column("error", sa.Text),
        sa.Column("duration_ms", sa.Float, server_default="0.0"),
        sa.Column("iterations", sa.Integer, server_default="0"),
        sa.Column("token_usage", sa.Integer, server_default="0"),
        sa.Column("user_rating", sa.Float),
        sa.Column("user_feedback", sa.Text),
        sa.Column("automated_score", sa.Float),
        sa.Column("metadata", sa.JSON, server_default="{}"),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
    )

    op.create_index(
        "ix_feedback_agent_created", "feedbacks", ["agent_id", "created_at"]
    )
    op.create_index("ix_feedback_success", "feedbacks", ["success"])


def downgrade() -> None:
    # 按依赖顺序反向删除表
    op.drop_table("feedbacks")
    op.drop_table("tool_call_logs")
    op.drop_table("task_executions")
    op.drop_table("workflow_executions")
    op.drop_table("workflow_definitions")
    op.drop_table("agent_definitions")

    # 删除枚举类型（仅 PostgreSQL）
    # SQLite 不需要
    try:
        op.execute("DROP TYPE IF EXISTS agentstatus")
        op.execute("DROP TYPE IF EXISTS taskstatus")
        op.execute("DROP TYPE IF EXISTS workflowstatus")
    except Exception:
        pass  # 忽略 SQLite 等不支持的数据库
