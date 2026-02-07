"""智能演化 - Meta Agent、反馈学习、Prompt 优化、版本控制、A/B 测试与性能监控"""

from .meta_agent import MetaAgent
from .feedback_loop import (
    ExecutionFeedback,
    FeedbackAnalysis,
    FeedbackCollector,
)
from .prompt_optimizer import (
    PromptOptimizer,
    PromptVariant,
    ExecutionLog,
    OptimizationType,
)
from .version_control import (
    VersionControl,
    AgentVersion,
    VersionStatus,
    VersionDiff,
)
from .ab_testing import (
    ABTestingFramework,
    Experiment,
    ExperimentStatus,
    VariantResult,
)
from .performance_monitor import (
    AgentPerformanceMonitor,
    AgentMetrics,
    AlertRule,
    Alert,
    AlertSeverity,
    PerformanceReport,
    NotificationChannel,
    LogNotificationChannel,
    WebhookNotificationChannel,
)
from .interactive_builder import (
    InteractiveWorkflowBuilder,
    CLIInteractionCallback,
    IterationManager,
    UserInteractionCallback,
    UserFeedback,
    UserAction,
    InteractionStage,
    InteractionLevel,
    ArtifactStatus,
    ApproveAction,
    BuilderStateMachine,
    AgentSpec,
    WorkflowPlan,
    IterationRecord,
    Checkpoint,
    BuilderState,
)
from .nl_intent_processor import (
    NLIntentProcessor,
    UserIntent,
    ParsedIntent,
    BuilderContext,
)
from .workflow_operations import (
    WorkflowOperationTools,
    OperationResult,
)
from .dialogue_agent import (
    DialogueAgent,
    DialogueResponse,
)
from .conversational_builder import (
    ConversationalWorkflowBuilder,
    SessionMode,
    Message,
    ConversationResponse,
)
from .result_extractor import (
    IntermediateResultExtractor,
    ExecutionEvent,
    ExecutionEventType,
    FormattedMessage,
)

__all__ = [
    # Meta Agent
    "MetaAgent",
    # 反馈收集
    "ExecutionFeedback",
    "FeedbackAnalysis",
    "FeedbackCollector",
    # Prompt 优化
    "PromptOptimizer",
    "PromptVariant",
    "ExecutionLog",
    "OptimizationType",
    # 版本控制
    "VersionControl",
    "AgentVersion",
    "VersionStatus",
    "VersionDiff",
    # A/B 测试
    "ABTestingFramework",
    "Experiment",
    "ExperimentStatus",
    "VariantResult",
    # 性能监控
    "AgentPerformanceMonitor",
    "AgentMetrics",
    "AlertRule",
    "Alert",
    "AlertSeverity",
    "PerformanceReport",
    "NotificationChannel",
    "LogNotificationChannel",
    "WebhookNotificationChannel",
    # 交互式构建器
    "InteractiveWorkflowBuilder",
    "CLIInteractionCallback",
    "IterationManager",
    "UserInteractionCallback",
    "UserFeedback",
    "UserAction",
    "InteractionStage",
    "InteractionLevel",
    "AgentSpec",
    "WorkflowPlan",
    "IterationRecord",
    "Checkpoint",
    "BuilderState",
    # 自然语言意图处理（向后兼容）
    "NLIntentProcessor",
    "UserIntent",
    "ParsedIntent",
    "BuilderContext",
    # 工作流操作工具
    "WorkflowOperationTools",
    "OperationResult",
    # 对话 Agent
    "DialogueAgent",
    "DialogueResponse",
    # 对话式构建器
    "ConversationalWorkflowBuilder",
    "SessionMode",
    "Message",
    "ConversationResponse",
    # 中间结果提取器
    "IntermediateResultExtractor",
    "ExecutionEvent",
    "ExecutionEventType",
    "FormattedMessage",
]
