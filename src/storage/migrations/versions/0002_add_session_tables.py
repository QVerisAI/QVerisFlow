"""Add conversation session tables

Revision ID: 0002
Revises: 0001
Create Date: 2026-02-03 22:30:00

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from alembic.context import get_context

# revision identifiers, used by Alembic.
revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def is_postgresql():
    """检测当前是否为 PostgreSQL"""
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    # 仅在 PostgreSQL 中创建枚举类型
    if is_postgresql():
        op.execute(
            """
            DO $$ BEGIN
                CREATE TYPE sessionstatus AS ENUM (
                    'idle', 'planning', 'building', 'confirming', 'executing', 'completed'
                );
            EXCEPTION
                WHEN duplicate_object THEN null;
            END $$;
        """
        )
        status_column = sa.Column(
            "status",
            sa.Enum(
                "idle",
                "planning",
                "building",
                "confirming",
                "executing",
                "completed",
                name="sessionstatus",
                create_type=False,
            ),
            server_default="idle",
        )
    else:
        # SQLite 使用 VARCHAR
        status_column = sa.Column(
            "status",
            sa.String(32),
            server_default="idle",
        )

    # 创建对话会话表
    op.create_table(
        "conversation_sessions",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("session_id", sa.String(128), nullable=False, unique=True),
        status_column,
        sa.Column(
            "workflow_definition_id",
            sa.String(64),
            sa.ForeignKey("workflow_definitions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("task_description", sa.Text, nullable=True),
        sa.Column("message_count", sa.Integer, server_default="0"),
        sa.Column("metadata", sa.JSON, server_default="{}"),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
        sa.Column(
            "updated_at",
            sa.DateTime,
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
        ),
        sa.Column("last_activity_at", sa.DateTime, server_default=sa.func.now()),
    )

    # 创建会话表索引
    op.create_index(
        "ix_session_session_id", "conversation_sessions", ["session_id"], unique=True
    )
    op.create_index("ix_session_status", "conversation_sessions", ["status"])
    op.create_index(
        "ix_session_last_activity", "conversation_sessions", ["last_activity_at"]
    )

    # 创建对话消息表
    op.create_table(
        "conversation_messages",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column(
            "session_id",
            sa.String(64),
            sa.ForeignKey("conversation_sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("role", sa.String(32), nullable=False),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("message_type", sa.String(32), server_default="text"),
        sa.Column("sequence", sa.Integer, nullable=False),
        sa.Column("data", sa.JSON, server_default="{}"),
        sa.Column("timestamp", sa.DateTime, server_default=sa.func.now()),
    )

    # 创建消息表索引
    op.create_index(
        "ix_message_session_sequence",
        "conversation_messages",
        ["session_id", "sequence"],
    )
    op.create_index("ix_message_timestamp", "conversation_messages", ["timestamp"])


def downgrade() -> None:
    # 删除消息表
    op.drop_index("ix_message_timestamp", table_name="conversation_messages")
    op.drop_index("ix_message_session_sequence", table_name="conversation_messages")
    op.drop_table("conversation_messages")

    # 删除会话表
    op.drop_index("ix_session_last_activity", table_name="conversation_sessions")
    op.drop_index("ix_session_status", table_name="conversation_sessions")
    op.drop_index("ix_session_session_id", table_name="conversation_sessions")
    op.drop_table("conversation_sessions")

    # 仅在 PostgreSQL 中删除枚举类型
    if is_postgresql():
        op.execute("DROP TYPE IF EXISTS sessionstatus")
