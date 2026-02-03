"""
Agent 状态定义

使用 TypedDict 定义 LangGraph 兼容的 Agent 状态模型。
"""

from typing import Dict, Any, Optional, List, Annotated
from typing_extensions import TypedDict
from datetime import datetime
from src.utils.logger import get_logger

logger = get_logger()

def add_messages(left: List[Dict[str, Any]], right: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """合并消息列表的辅助函数"""
    return left + right


class AgentState(TypedDict):
    """
    Agent 状态定义（LangGraph 兼容）
    
    使用 TypedDict 以便 LangGraph 进行状态管理
    """
    
    # === 基本信息 ===
    agent_id: str
    task_id: str
    
    # === 消息历史（LangGraph 标准）===
    messages: Annotated[List[Dict[str, Any]], add_messages]
    
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
    """
    创建初始状态
    
    Args:
        agent_id: Agent ID
        task_id: 任务 ID
        workspace_path: 工作空间路径
        max_iterations: 最大迭代次数
    
    Returns:
        初始化的 AgentState
    """
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

