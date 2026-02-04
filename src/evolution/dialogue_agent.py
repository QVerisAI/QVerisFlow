"""
对话 Agent

使用 LLM 进行工具调用的智能对话 Agent，用于工作流构建
"""

from dataclasses import dataclass, field
from typing import Dict, Any, Optional, List, Callable, Awaitable
from datetime import datetime
import json
import re

from src.utils.logger import get_logger
from .workflow_operations import WorkflowOperationTools, OperationResult

logger = get_logger()


@dataclass
class DialogueResponse:
    """对话响应"""

    message: str
    data: Optional[Dict[str, Any]] = None
    workflow_changed: bool = False
    tool_calls: List[Dict[str, Any]] = field(default_factory=list)
    suggested_actions: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "message": self.message,
            "data": self.data,
            "workflow_changed": self.workflow_changed,
            "tool_calls": self.tool_calls,
            "suggested_actions": self.suggested_actions,
        }


class DialogueAgent:
    """
    LLM 驱动的对话 Agent

    通过工具调用实现智能工作流构建对话
    """

    # 工具定义
    TOOL_DEFINITIONS = [
        {
            "type": "function",
            "function": {
                "name": "create_workflow_plan",
                "description": "创建新的工作流规划。当用户想要创建新的工作流或描述一个新任务时调用此函数。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "task_description": {
                            "type": "string",
                            "description": "工作流的任务描述，详细说明要完成什么",
                        }
                    },
                    "required": ["task_description"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "add_agent_to_plan",
                "description": "向工作流规划中添加新的 Agent 节点",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "name": {
                            "type": "string",
                            "description": "Agent 的技术名称（英文 CamelCase），如 DataCollectorAgent、TrendAnalyzer 等",
                        },
                        "display_name": {
                            "type": "string",
                            "description": "Agent 的用户友好显示名称（中文），如 '数据收集器'、'趋势分析师' 等，必须提供",
                        },
                        "task": {"type": "string", "description": "Agent 的任务描述"},
                        "dependencies": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "此 Agent 依赖的其他 Agent 名称列表（这些 Agent 必须先执行完成）",
                        },
                        "tools": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Agent 使用的工具列表，如 qveris_search_tools, qveris_execute_tool, file_read 等",
                        },
                        "position": {
                            "type": "string",
                            "description": "位置：'auto'（自动）, 'start'（开始）, 'end'（结束）, 'after:AgentName'（在某Agent之后）, 'before:AgentName'（在某Agent之前）",
                        },
                    },
                    "required": ["name", "display_name", "task"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "remove_agent_from_plan",
                "description": "从工作流规划中移除一个 Agent",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "agent_name": {
                            "type": "string",
                            "description": "要移除的 Agent 名称",
                        }
                    },
                    "required": ["agent_name"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "modify_agent_spec",
                "description": "修改 Agent 的规格（名称、任务、依赖、工具等）",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "agent_name": {
                            "type": "string",
                            "description": "要修改的 Agent 技术名称",
                        },
                        "new_name": {
                            "type": "string",
                            "description": "新的 Agent 技术名称（可选）",
                        },
                        "new_display_name": {
                            "type": "string",
                            "description": "新的 Agent 显示名称/中文名（可选）",
                        },
                        "new_task": {
                            "type": "string",
                            "description": "新的任务描述（可选）",
                        },
                        "add_dependencies": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "要添加的依赖（可选）",
                        },
                        "remove_dependencies": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "要移除的依赖（可选）",
                        },
                        "add_tools": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "要添加的工具（可选）",
                        },
                        "remove_tools": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "要移除的工具（可选）",
                        },
                    },
                    "required": ["agent_name"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "modify_dependencies",
                "description": "修改 Agent 的依赖关系，设置它应该在哪些 Agent 之后执行",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "agent_name": {
                            "type": "string",
                            "description": "要修改的 Agent 名称",
                        },
                        "depends_on": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "此 Agent 应该依赖的 Agent 名称列表（完全替换现有依赖）",
                        },
                    },
                    "required": ["agent_name", "depends_on"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "set_parallel_agents",
                "description": "设置多个 Agent 并行执行（移除它们之间的依赖关系）",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "agent_names": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "要并行执行的 Agent 名称列表",
                        }
                    },
                    "required": ["agent_names"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "reorder_workflow",
                "description": "重新排列工作流的执行顺序",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "new_order": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "新的执行顺序（Agent 名称列表）",
                        }
                    },
                    "required": ["new_order"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "regenerate_plan",
                "description": "根据反馈重新生成工作流规划",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "feedback": {"type": "string", "description": "用户的反馈意见"}
                    },
                    "required": [],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "approve_current_state",
                "description": "批准当前状态，进入下一阶段。规划阶段批准后会生成 Agents，Agent 阶段批准后会组装工作流。",
                "parameters": {"type": "object", "properties": {}, "required": []},
            },
        },
        {
            "type": "function",
            "function": {
                "name": "rollback_to_checkpoint",
                "description": "回滚到之前的检查点",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "checkpoint_id": {
                            "type": "string",
                            "description": "检查点 ID（可选，不指定则回滚到上一个）",
                        }
                    },
                    "required": [],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "save_workflow",
                "description": "保存当前工作流到数据库（优先）和本地文件（备份）",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "name": {
                            "type": "string",
                            "description": "工作流名称（可选，默认使用任务描述）",
                        },
                        "description": {
                            "type": "string",
                            "description": "工作流描述（可选）",
                        },
                        "tags": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "标签列表（可选）",
                        },
                        "path": {
                            "type": "string",
                            "description": "本地备份路径（可选）",
                        },
                    },
                    "required": [],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "execute_workflow",
                "description": "执行当前工作流",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "params": {"type": "object", "description": "执行参数（可选）"}
                    },
                    "required": [],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_workflow_status",
                "description": "获取当前工作流状态（用于回答用户关于当前状态的问题）",
                "parameters": {"type": "object", "properties": {}, "required": []},
            },
        },
        {
            "type": "function",
            "function": {
                "name": "optimize_agent_prompt",
                "description": "使用 LLM 优化 Agent 的 Prompt 配置字段（如角色描述、核心能力、任务上下文等）",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "agent_name": {
                            "type": "string",
                            "description": "要优化的 Agent 名称",
                        },
                        "field": {
                            "type": "string",
                            "description": "要优化的字段，如 'role_description', 'core_capability', 'task_context', 'description'",
                        },
                        "current_value": {
                            "type": "string",
                            "description": "字段当前的值",
                        },
                        "optimization_goal": {
                            "type": "string",
                            "description": "优化目标描述（可选，如 '使其更专业' 或 '增加金融领域特点'）",
                        },
                    },
                    "required": ["agent_name", "field", "current_value"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "update_agent_definition",
                "description": "更新 Agent 的配置（适用于批量更新多个字段）",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "agent_name": {
                            "type": "string",
                            "description": "要更新的 Agent 名称",
                        },
                        "updates": {
                            "type": "object",
                            "description": "要更新的字段和值的字典，支持嵌套字段如 'background_instruction.role_description'",
                        },
                    },
                    "required": ["agent_name", "updates"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_agent_definition",
                "description": "获取 Agent 的完整配置定义",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "agent_name": {"type": "string", "description": "Agent 名称"}
                    },
                    "required": ["agent_name"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "regenerate_agent",
                "description": "重新生成指定的 Agent（用于生成失败或用户不满意时）。支持传入 'failed' 重新生成所有失败的 Agent。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "agent_name": {
                            "type": "string",
                            "description": "要重新生成的 Agent 名称，或 'failed' 表示所有失败的 Agent",
                        },
                        "feedback": {
                            "type": "string",
                            "description": "重新生成的原因或改进建议（可选，用于指导 LLM 生成更好的结果）",
                        },
                    },
                    "required": ["agent_name"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "iterate_plan",
                "description": "智能迭代规划。基于用户的反馈和要求，结合历史规划上下文，让 LLM 深度理解并生成新的完整规划。适用于：整合多个规划、根据反馈修改、添加/删除特定 Agent、参考之前规划的 Agent 等场景。当用户说'整合'、'合并'、'把上一版的XXX加入'、'修改规划'、'根据反馈调整'等时调用此工具。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "user_request": {
                            "type": "string",
                            "description": "用户的自然语言请求，完整描述希望如何修改/迭代规划。例如：'把上一版规划的数据收集器和分析师加入当前规划'、'整合两次规划取各自优点'、'在当前规划基础上增加一个数据验证环节'",
                        },
                        "include_history": {
                            "type": "boolean",
                            "description": "是否参考历史规划（默认 true）。设为 false 则只基于当前规划修改",
                            "default": True,
                        },
                    },
                    "required": ["user_request"],
                },
            },
        },
    ]

    def __init__(
        self,
        llm_client: Any,
        operations: WorkflowOperationTools,
        system_prompt: Optional[str] = None,
    ):
        """
        初始化对话 Agent

        Args:
            llm_client: LLM 客户端
            operations: 工作流操作工具
            system_prompt: 系统提示词（可选）
        """
        self.llm = llm_client
        self.ops = operations
        self.conversation_history: List[Dict[str, str]] = []
        self.system_prompt = system_prompt or self._default_system_prompt()
        self.tool_call_history: List[Dict[str, Any]] = []  # 工具调用历史

        # 工具名称到方法的映射
        self._tool_handlers = {
            "create_workflow_plan": self._handle_create_workflow_plan,
            "add_agent_to_plan": self._handle_add_agent_to_plan,
            "remove_agent_from_plan": self._handle_remove_agent_from_plan,
            "modify_agent_spec": self._handle_modify_agent_spec,
            "modify_dependencies": self._handle_modify_dependencies,
            "set_parallel_agents": self._handle_set_parallel_agents,
            "reorder_workflow": self._handle_reorder_workflow,
            "regenerate_plan": self._handle_regenerate_plan,
            "approve_current_state": self._handle_approve_current_state,
            "rollback_to_checkpoint": self._handle_rollback_to_checkpoint,
            "save_workflow": self._handle_save_workflow,
            "execute_workflow": self._handle_execute_workflow,
            "get_workflow_status": self._handle_get_workflow_status,
            "optimize_agent_prompt": self._handle_optimize_agent_prompt,
            "update_agent_definition": self._handle_update_agent_definition,
            "get_agent_definition": self._handle_get_agent_definition,
            "regenerate_agent": self._handle_regenerate_agent,
            "iterate_plan": self._handle_iterate_plan,
        }

    def _default_system_prompt(self) -> str:
        """默认系统提示词"""
        return """你是一个智能工作流构建助手。你帮助用户通过自然对话创建、修改和管理 AI Agent 工作流。

## 你的能力
你可以通过调用相应的工具来执行以下操作：
- 创建新的工作流规划（create_workflow_plan）
- **智能迭代规划（iterate_plan）** - 用于整合、修改、根据反馈更新规划（最常用）
- 添加、移除或修改工作流中的 Agent（add_agent_to_plan, remove_agent_from_plan, modify_agent_spec）
- 调整 Agent 之间的依赖关系（modify_dependencies）
- 设置 Agent 并行执行（set_parallel_agents）
- 重新排列工作流执行顺序（reorder_workflow）
- 批准当前状态进入下一阶段（approve_current_state）
- 回滚到之前的检查点（rollback_to_checkpoint）
- 保存工作流（save_workflow）
- 执行工作流（execute_workflow）

## 工作流构建流程
1. 规划阶段：用户描述任务，系统生成工作流规划（包含多个 Agent 规格）
2. 用户可以修改规划：添加/删除/修改 Agent，调整依赖关系等
3. 批准规划后，系统生成实际的 Agent 定义
4. 批准 Agent 后，系统组装工作流
5. 批准工作流后，可以执行或保存

## 规划迭代理解（非常重要！）
当用户请求修改、整合、迭代规划时，**必须使用 iterate_plan 工具**：

**适用场景：**
- 用户说"把上一版规划的 XXX 加入当前规划"
- 用户说"整合两次规划"、"合并"、"融合"
- 用户说"修改规划，增加 XXX"
- 用户说"根据反馈重新设计"
- 用户提到"之前的"、"上一个"、"刚才的"规划或 Agent

**使用方法：**
1. 将用户的**完整请求**作为 user_request 参数传递
2. 不要尝试分解用户请求为多个小操作
3. iterate_plan 会自动获取历史规划上下文，让 LLM 深度理解用户意图并生成新的完整规划

**示例：**
- 用户说"把上一版规划的上游产业链识别器加入当前规划" 
  → iterate_plan(user_request="把上一版规划的上游产业链识别器加入当前规划，互相之间以及跟已有节点需建立合适的依赖关系")
- 用户说"整合两次规划" 
  → iterate_plan(user_request="整合两次规划，取各自的优点")
- 用户说"修改当前规划，增加数据验证环节" 
  → iterate_plan(user_request="在当前规划基础上增加一个数据验证环节")

## 重要：批准/确认命令识别（必须遵守）
当用户说以下内容时，**必须立即调用 approve_current_state**，不要调用其他工具：
- "确认"、"确认规划"、"确认 Agents"、"确认工作流"
- "批准"、"批准规划"、"批准生成"
- "开始生成"、"生成 Agents"、"生成工作流"
- "OK"、"好的"、"可以"、"同意"、"通过"
- "看起来不错"、"就这样"、"就按这个来"
- 任何表示同意或确认当前状态的简短回复

**这是最高优先级的规则**：上述命令必须触发 approve_current_state，而不是其他修改操作。

## 执行规划的识别
当用户说"执行规划"、"执行"、"运行"时：
- 如果当前阶段是 `plan`，需要先批准规划（approve_current_state）
- 如果当前阶段是 `workflow`，直接执行（execute_workflow）

## Agent 命名规范（重要）
- **技术名称 (name)**：用于系统内部引用的英文标识，如 `DataCollectorAgent`、`TrendAnalyzer`
- **显示名称 (display_name)**：用于与用户交流的中文友好名称，如 "数据收集器"、"趋势分析师"
- **在与用户对话时，必须始终使用显示名称（display_name）来指代 Agent**
- **添加新 Agent 时，必须同时提供技术名称和显示名称**

## 指导原则
1. 理解用户的意图，调用合适的工具
2. **对于规划修改请求，优先使用 iterate_plan**，它能更好地理解用户意图
3. 如果请求不明确，询问用户澄清
4. 操作完成后，简洁地总结所做的更改（使用 Agent 的显示名称）
5. 主动提供有用的建议
6. 始终保持工作流处于有效状态
7. **与用户交流时，总是使用 Agent 的显示名称（中文名），而不是技术名称**

## 响应风格
- 简洁但信息丰富
- 使用中文显示名称来指代 Agent
- 用用户友好的术语解释更改
- 在适当时主动建议下一步操作
"""

    async def process_message(self, user_message: str) -> DialogueResponse:
        """
        处理用户消息

        Args:
            user_message: 用户输入

        Returns:
            对话响应
        """
        try:
            # 0. 预处理：直接处理关键命令，绕过 LLM 解释
            direct_result = await self._handle_direct_command(user_message)
            if direct_result is not None:
                return direct_result

            # 1. 构建消息
            messages = self._build_messages(user_message)

            # 2. 调用 LLM（带工具）
            response = await self._call_llm_with_tools(messages)

            # 3. 处理响应
            return await self._process_llm_response(response, user_message)

        except Exception as e:
            logger.error(f"处理消息失败: {e}")
            return DialogueResponse(
                message=f"处理请求时出错: {str(e)}",
                workflow_changed=False,
            )

    async def _handle_direct_command(
        self, user_message: str
    ) -> Optional[DialogueResponse]:
        """
        直接处理关键命令，绕过 LLM 解释

        对于批准/确认等关键操作，直接调用对应工具，确保可靠执行

        Returns:
            如果是直接命令则返回 DialogueResponse，否则返回 None
        """
        msg = user_message.strip().lower()

        # 批准/确认命令 - 直接调用 approve_current_state
        approval_keywords = [
            "确认",
            "确认规划",
            "确认agents",
            "确认 agents",
            "确认工作流",
            "批准",
            "批准规划",
            "批准生成",
            "开始生成",
            "生成agents",
            "生成 agents",
            "ok",
            "好的",
            "可以",
            "同意",
            "通过",
            "是的",
            "对",
            "行",
        ]

        if msg in approval_keywords:
            logger.info(f"直接处理批准命令: {user_message}")
            result = await self.ops.approve_current_state()

            # 添加到对话历史
            self.conversation_history.append({"role": "user", "content": user_message})
            self.conversation_history.append(
                {"role": "assistant", "content": result.message}
            )

            return DialogueResponse(
                message=result.message,
                workflow_changed=result.workflow_changed,
                suggested_actions=self._get_suggested_actions_for_stage(),
            )

        # 执行命令
        execution_keywords = ["执行", "执行工作流", "运行", "运行工作流", "开始执行"]
        if msg in execution_keywords:
            logger.info(f"直接处理执行命令: {user_message}")
            result = await self.ops.execute_workflow()

            self.conversation_history.append({"role": "user", "content": user_message})
            self.conversation_history.append(
                {"role": "assistant", "content": result.message}
            )

            return DialogueResponse(
                message=result.message,
                workflow_changed=result.workflow_changed,
                suggested_actions=["暂停", "停止"] if result.success else [],
            )

        # 保存命令
        save_keywords = ["保存", "保存工作流"]
        if msg in save_keywords:
            logger.info(f"直接处理保存命令: {user_message}")
            result = await self.ops.save_workflow()

            self.conversation_history.append({"role": "user", "content": user_message})
            self.conversation_history.append(
                {"role": "assistant", "content": result.message}
            )

            return DialogueResponse(
                message=result.message,
                workflow_changed=result.workflow_changed,
            )

        # 回滚命令
        rollback_keywords = ["回滚", "撤销", "撤回"]
        if msg in rollback_keywords:
            logger.info(f"直接处理回滚命令: {user_message}")
            result = await self.ops.rollback_to_checkpoint()

            self.conversation_history.append({"role": "user", "content": user_message})
            self.conversation_history.append(
                {"role": "assistant", "content": result.message}
            )

            return DialogueResponse(
                message=result.message,
                workflow_changed=result.workflow_changed,
                suggested_actions=self._get_suggested_actions_for_stage(),
            )

        # 重新生成失败的 Agent 命令
        failed_agent_keywords = [
            "重新生成失败的",
            "重新生成失败的agent",
            "重新生成失败的 agent",
            "重新生成失败",
            "重试失败的",
            "重试失败的agent",
            "重试失败的 agent",
        ]
        if msg in failed_agent_keywords:
            logger.info(f"直接处理重新生成失败Agent命令: {user_message}")
            result = await self.ops.regenerate_agent("failed")

            self.conversation_history.append({"role": "user", "content": user_message})
            self.conversation_history.append(
                {"role": "assistant", "content": result.message}
            )

            return DialogueResponse(
                message=result.message,
                workflow_changed=result.workflow_changed,
                suggested_actions=self._get_suggested_actions_for_stage(),
            )

        # 重新生成特定 Agent 命令（模式匹配）
        regenerate_agent_patterns = [
            ("重新生成", ""),
            ("重试", ""),
            ("重做", ""),
        ]
        for prefix, _ in regenerate_agent_patterns:
            if msg.startswith(prefix) and len(msg) > len(prefix):
                agent_name = msg[len(prefix) :].strip()
                # 排除掉 "规划" 等词（这些应该走规划重新生成）
                if agent_name and agent_name not in [
                    "规划",
                    "工作流",
                    "plan",
                    "workflow",
                ]:
                    logger.info(
                        f"直接处理重新生成Agent命令: {user_message}, agent_name={agent_name}"
                    )
                    result = await self.ops.regenerate_agent(agent_name)

                    self.conversation_history.append(
                        {"role": "user", "content": user_message}
                    )
                    self.conversation_history.append(
                        {"role": "assistant", "content": result.message}
                    )

                    return DialogueResponse(
                        message=result.message,
                        workflow_changed=result.workflow_changed,
                        suggested_actions=self._get_suggested_actions_for_stage(),
                    )

        # 重新生成规划命令
        regenerate_plan_keywords = [
            "重新生成",
            "重新规划",
            "重做",
            "重新生成规划",
            "重新生成工作流",
        ]
        if msg in regenerate_plan_keywords:
            logger.info(f"直接处理重新生成规划命令: {user_message}")
            result = await self.ops.regenerate_plan()

            self.conversation_history.append({"role": "user", "content": user_message})
            self.conversation_history.append(
                {"role": "assistant", "content": result.message}
            )

            return DialogueResponse(
                message=result.message,
                workflow_changed=result.workflow_changed,
                suggested_actions=self._get_suggested_actions_for_stage(),
            )

        # 不是直接命令，返回 None 继续 LLM 处理
        return None

    def _get_suggested_actions_for_stage(self) -> List[str]:
        """根据当前阶段返回建议操作"""
        stage = self.ops.get_current_stage()

        if stage == "plan":
            return ["确认规划", "修改规划", "添加 Agent", "重新生成"]
        elif stage == "agent":
            return ["确认 Agents", "修改 Agent", "重新生成", "回滚"]
        elif stage == "workflow":
            return ["执行工作流", "保存工作流", "修改", "回滚"]
        else:
            return []

    def _build_messages(self, user_message: str) -> List[Dict[str, str]]:
        """构建消息列表"""
        # 构建上下文
        context = self._build_context()

        messages = [
            {"role": "system", "content": self.system_prompt},
        ]

        # 添加当前状态上下文
        if context:
            messages.append(
                {"role": "system", "content": f"当前工作流状态:\n{context}"}
            )

        # 添加对话历史（最近 10 轮）
        messages.extend(self.conversation_history[-20:])  # 每轮2条消息

        # 添加当前用户消息
        messages.append({"role": "user", "content": user_message})

        return messages

    def _build_context(self) -> str:
        """构建丰富的上下文信息，包含完整规划详情、Agent 信息和检查点历史"""
        parts = []

        # 1. 当前阶段
        stage = self.ops.get_current_stage()
        parts.append(f"## 当前阶段: {stage}")

        # 2. 完整规划信息（不截断）
        plan = self.ops.get_current_plan()
        if plan:
            parts.append(f"\n## 当前规划")
            task_desc = plan.get("task_description", "N/A")
            if task_desc:
                parts.append(f"任务描述: {task_desc}")
            workflow_structure = plan.get("workflow_structure", "")
            if workflow_structure:
                parts.append(f"工作流结构: {workflow_structure}")

            # 完整的 Agent 列表（不截断任务描述）
            agents = plan.get("agents", [])
            if agents:
                agent_lines = []
                for a in agents:
                    name = a.get("name", "Unknown")
                    display_name = a.get("display_name", name)
                    task = a.get("task", "")  # 不截断
                    deps = a.get("dependencies", [])
                    tools = a.get("tools", [])
                    agent_lines.append(
                        f"  - {display_name} ({name}):\n"
                        f"    任务: {task}\n"
                        f"    依赖: {', '.join(deps) if deps else '无'}\n"
                        f"    工具: {', '.join(tools) if tools else '无'}"
                    )
                parts.append(f"\nAgents ({len(agents)}):\n" + "\n".join(agent_lines))
        else:
            # 如果没有完整规划，尝试获取当前 agents
            agents = self.ops.get_current_agents()
            if agents:
                agent_lines = []
                for a in agents:
                    name = a.get("name", "Unknown")
                    display_name = a.get("display_name", name)
                    task = a.get("task", "")
                    deps = a.get("dependencies", [])
                    agent_lines.append(
                        f"  - {display_name} ({name}): {task}"
                        + (f" [依赖: {', '.join(deps)}]" if deps else "")
                    )
                parts.append(f"\nAgents ({len(agents)}):\n" + "\n".join(agent_lines))

        # 3. 检查点详情（最近5个，包含标签和时间）
        checkpoints = self.ops.get_checkpoints()
        if checkpoints:
            recent_count = min(5, len(checkpoints))
            parts.append(
                f"\n## 检查点历史 (共 {len(checkpoints)} 个，显示最近 {recent_count} 个)"
            )
            for ckpt in checkpoints[-5:]:
                label = ckpt.get("label", "unknown")
                timestamp = ckpt.get("timestamp", "")
                if timestamp and len(timestamp) > 19:
                    timestamp = timestamp[:19]  # 截取日期时间部分
                ckpt_stage = ckpt.get("stage", "")
                ckpt_id = (
                    ckpt.get("checkpoint_id", "")[:8]
                    if ckpt.get("checkpoint_id")
                    else ""
                )
                # 尝试获取检查点中的 agent 数量
                state = ckpt.get("state", {})
                plan_in_ckpt = state.get("plan", {})
                agents_in_ckpt = plan_in_ckpt.get("agents", []) if plan_in_ckpt else []
                agent_names = [
                    a.get("display_name", a.get("name", "")) for a in agents_in_ckpt
                ]
                agents_summary = (
                    f", Agents: {', '.join(agent_names)}" if agent_names else ""
                )
                parts.append(
                    f"  - [{ckpt_id}] {label} ({timestamp}, 阶段: {ckpt_stage}{agents_summary})"
                )

        # 4. 执行状态
        status = self.ops.get_execution_status()
        if status.get("is_executing"):
            parts.append("\n## 状态: 正在执行工作流")
        elif status.get("has_workflow"):
            parts.append("\n## 状态: 工作流已就绪，可执行")

        # 5. 工具调用历史（如果有）
        if hasattr(self, "tool_call_history") and self.tool_call_history:
            recent_calls = self.tool_call_history[-5:]
            if recent_calls:
                parts.append(f"\n## 最近工具调用 ({len(recent_calls)} 个)")
                for tc in recent_calls:
                    name = tc.get("name", "unknown")
                    success = tc.get("result", {}).get("success", False)
                    status_str = "✓" if success else "✗"
                    parts.append(f"  - {status_str} {name}")

        return "\n".join(parts) if parts else "尚未创建工作流"

    async def _call_llm_with_tools(self, messages: List[Dict]) -> Dict[str, Any]:
        """调用 LLM 并支持工具调用"""
        try:
            # 尝试使用带工具的调用
            if hasattr(self.llm, "call_with_tools"):
                return await self.llm.call_with_tools(
                    messages=messages,
                    tools=self.TOOL_DEFINITIONS,
                )
            elif hasattr(self.llm, "call"):
                # 使用标准 call，将工具信息嵌入提示词
                tool_prompt = self._build_tool_prompt()
                enhanced_messages = messages.copy()
                enhanced_messages[0] = {
                    "role": "system",
                    "content": messages[0]["content"] + "\n\n" + tool_prompt,
                }

                response = await self.llm.call(enhanced_messages)

                # 解析响应中的工具调用
                return self._parse_tool_calls_from_response(response)
            else:
                raise ValueError("LLM 客户端不支持 call 方法")

        except Exception as e:
            logger.error(f"调用 LLM 失败: {e}")
            raise

    def _build_tool_prompt(self) -> str:
        """构建工具使用提示词"""
        tool_descriptions = []
        for tool in self.TOOL_DEFINITIONS:
            func = tool["function"]
            params = func.get("parameters", {}).get("properties", {})
            param_desc = ", ".join(
                [f"{k}: {v.get('description', '')}" for k, v in params.items()]
            )
            tool_descriptions.append(
                f"- {func['name']}: {func['description']}\n  参数: {param_desc or '无'}"
            )

        return f"""## 可用工具
当需要执行操作时，**必须严格**按以下格式调用工具：

<tool_call>
{{"name": "工具名称", "arguments": {{"参数名": "参数值"}}}}
</tool_call>

**格式要求（必须遵守）**：
1. 工具调用必须放在 <tool_call> 和 </tool_call> 标签之间
2. **绝对不要**直接输出裸 JSON，必须使用标签包裹
3. 每次只调用一个工具
4. 调用工具后，不要添加多余的解释文字

**正确示例** - 用户说"好的"/"looks good"/"就这样吧"/"确认"时：
<tool_call>
{{"name": "approve_current_state", "arguments": {{}}}}
</tool_call>

**错误示例**（绝对不要这样做）：
{{"name": "approve_current_state", "arguments": {{}}}}

可用工具列表：
{chr(10).join(tool_descriptions)}

重要规则：
1. 如果用户的请求需要执行操作，必须调用相应的工具
2. 如果只是闲聊或询问，可以直接回复
3. 调用工具时，不要添加"正在为您..."、"让我..."等临时性提示语
4. 工具执行完成后，系统会自动返回执行结果给用户
"""

    def _parse_tool_calls_from_response(self, response: Any) -> Dict[str, Any]:
        """从响应中解析工具调用（支持多种格式）"""
        # 获取响应内容
        if hasattr(response, "content"):
            content = response.content
        elif isinstance(response, dict) and "content" in response:
            content = response["content"]
        elif isinstance(response, str):
            content = response
        else:
            content = str(response)

        # 多格式解析工具调用
        tool_calls = []

        # 1. 首先尝试 <tool_call> 标签（优先）
        tool_calls = self._parse_tool_call_tags(content)

        # 2. 如果没找到，尝试解析纯 JSON 工具调用
        if not tool_calls:
            tool_calls = self._parse_plain_json_tool_call(content)

        # 3. 如果没找到，尝试解析 markdown 代码块中的 JSON
        if not tool_calls:
            tool_calls = self._parse_markdown_json_tool_call(content)

        # 清理内容（移除已解析的工具调用）
        clean_content = self._clean_tool_call_content(content, tool_calls)

        return {
            "content": clean_content,
            "tool_calls": tool_calls if tool_calls else None,
        }

    def _repair_json_string(self, json_str: str) -> str:
        """
        尝试修复常见的 JSON 格式问题

        处理的问题：
        1. 未终止的字符串（截断）
        2. 中文引号替换
        3. 缺少结束括号
        """
        # 替换中文引号为英文引号
        json_str = json_str.replace('"', '"').replace('"', '"')
        json_str = json_str.replace(""", "'").replace(""", "'")

        # 检查是否有未闭合的字符串
        # 计算引号数量
        quote_count = json_str.count('"') - json_str.count('\\"')
        if quote_count % 2 == 1:
            # 奇数个引号，说明有未闭合的字符串
            # 找到最后一个非转义引号的位置，然后截断到那里并补全
            last_quote = json_str.rfind('"')
            if last_quote > 0 and json_str[last_quote - 1] != "\\":
                # 这是一个开始引号，需要补全结束引号
                json_str = json_str + '"'

        # 检查括号是否闭合
        open_braces = json_str.count("{") - json_str.count("}")
        open_brackets = json_str.count("[") - json_str.count("]")

        # 补全缺少的结束括号
        json_str = json_str + "]" * open_brackets + "}" * open_braces

        return json_str

    def _parse_tool_call_tags(self, content: str) -> List[Dict]:
        """解析 <tool_call> 标签格式的工具调用"""
        tool_calls = []
        start_tag = "<tool_call>"
        end_tag = "</tool_call>"

        search_start = 0
        while True:
            start_idx = content.find(start_tag, search_start)
            if start_idx == -1:
                break

            end_idx = content.find(end_tag, start_idx)
            if end_idx == -1:
                # 如果没有找到结束标签，尝试解析到内容末尾
                json_str = content[start_idx + len(start_tag) :].strip()
                # 尝试修复并解析
                json_str = self._repair_json_string(json_str)
                try:
                    tool_call = json.loads(json_str)
                    if tool_call.get("name"):
                        tool_calls.append(
                            {
                                "id": f"call_{len(tool_calls)}",
                                "type": "function",
                                "function": {
                                    "name": tool_call.get("name"),
                                    "arguments": json.dumps(
                                        tool_call.get("arguments", {}),
                                        ensure_ascii=False,
                                    ),
                                },
                            }
                        )
                        logger.info(
                            f"修复并解析了截断的工具调用: {tool_call.get('name')}"
                        )
                except json.JSONDecodeError as e:
                    logger.warning(f"无法解析截断的工具调用 JSON: {e}")
                break

            json_str = content[start_idx + len(start_tag) : end_idx].strip()

            try:
                tool_call = json.loads(json_str)
                tool_calls.append(
                    {
                        "id": f"call_{len(tool_calls)}",
                        "type": "function",
                        "function": {
                            "name": tool_call.get("name"),
                            "arguments": json.dumps(
                                tool_call.get("arguments", {}), ensure_ascii=False
                            ),
                        },
                    }
                )
            except json.JSONDecodeError as e:
                # 尝试修复 JSON
                repaired_json = self._repair_json_string(json_str)
                try:
                    tool_call = json.loads(repaired_json)
                    if tool_call.get("name"):
                        tool_calls.append(
                            {
                                "id": f"call_{len(tool_calls)}",
                                "type": "function",
                                "function": {
                                    "name": tool_call.get("name"),
                                    "arguments": json.dumps(
                                        tool_call.get("arguments", {}),
                                        ensure_ascii=False,
                                    ),
                                },
                            }
                        )
                        logger.info(f"修复并解析了工具调用: {tool_call.get('name')}")
                except json.JSONDecodeError:
                    logger.warning(
                        f"无法解析 <tool_call> 标签中的 JSON: {e}, 内容: {json_str[:100]}..."
                    )

            search_start = end_idx + len(end_tag)

        return tool_calls

    def _parse_plain_json_tool_call(self, content: str) -> List[Dict]:
        """解析纯 JSON 格式的工具调用"""
        content = content.strip()
        # 检查是否整个内容是一个工具调用 JSON
        if content.startswith("{"):
            # 尝试直接解析
            try:
                data = json.loads(content)
            except json.JSONDecodeError:
                # 尝试修复后解析
                repaired = self._repair_json_string(content)
                try:
                    data = json.loads(repaired)
                    logger.info("修复了纯 JSON 工具调用格式")
                except json.JSONDecodeError:
                    return []

            # 验证是否是有效的工具调用格式
            if "name" in data and isinstance(data.get("arguments"), (dict, type(None))):
                # 验证工具名称是否在已知工具列表中
                valid_tools = {t["function"]["name"] for t in self.TOOL_DEFINITIONS}
                if data["name"] in valid_tools:
                    logger.info(f"从纯 JSON 解析到工具调用: {data['name']}")
                    return [
                        {
                            "id": "call_0",
                            "type": "function",
                            "function": {
                                "name": data["name"],
                                "arguments": json.dumps(
                                    data.get("arguments", {}), ensure_ascii=False
                                ),
                            },
                        }
                    ]
        return []

    def _parse_markdown_json_tool_call(self, content: str) -> List[Dict]:
        """解析 Markdown 代码块中的工具调用"""
        # 匹配 ```json ... ``` 或 ``` ... ``` 格式
        pattern = r"```(?:json)?\s*\n?(\{[^`]+\})\s*\n?```"
        matches = re.findall(pattern, content, re.DOTALL)

        tool_calls = []
        valid_tools = {t["function"]["name"] for t in self.TOOL_DEFINITIONS}

        for match in matches:
            try:
                data = json.loads(match)
            except json.JSONDecodeError:
                # 尝试修复后解析
                repaired = self._repair_json_string(match)
                try:
                    data = json.loads(repaired)
                    logger.info("修复了 Markdown 代码块中的 JSON 格式")
                except json.JSONDecodeError:
                    continue

            if "name" in data and isinstance(data.get("arguments"), (dict, type(None))):
                if data["name"] in valid_tools:
                    logger.info(f"从 Markdown 代码块解析到工具调用: {data['name']}")
                    tool_calls.append(
                        {
                            "id": f"call_{len(tool_calls)}",
                            "type": "function",
                            "function": {
                                "name": data["name"],
                                "arguments": json.dumps(
                                    data.get("arguments", {}), ensure_ascii=False
                                ),
                            },
                        }
                    )

        return tool_calls

    def _clean_tool_call_content(self, content: str, tool_calls: List[Dict]) -> str:
        """清理内容，移除已解析的工具调用"""
        clean_content = content

        # 移除 <tool_call>...</tool_call> 标记
        start_tag = "<tool_call>"
        end_tag = "</tool_call>"
        while True:
            start_idx = clean_content.find(start_tag)
            if start_idx == -1:
                break
            end_idx = clean_content.find(end_tag, start_idx)
            if end_idx == -1:
                break
            clean_content = (
                clean_content[:start_idx] + clean_content[end_idx + len(end_tag) :]
            )

        # 如果有工具调用被解析，移除 markdown 代码块中的工具调用
        if tool_calls:
            pattern = r'```(?:json)?\s*\n?\{[^`]*"name"[^`]*\}\s*\n?```'
            clean_content = re.sub(pattern, "", clean_content, flags=re.DOTALL)

            # 如果整个内容是纯 JSON 工具调用，清空内容
            stripped = clean_content.strip()
            if stripped.startswith("{") and stripped.endswith("}"):
                try:
                    data = json.loads(stripped)
                    if "name" in data and "arguments" in data:
                        clean_content = ""
                except json.JSONDecodeError:
                    pass

        # 清理多余的空行和空格
        clean_content = re.sub(r"\n{3,}", "\n\n", clean_content).strip()

        return clean_content

    async def _process_llm_response(
        self, response: Dict[str, Any], user_message: str
    ) -> DialogueResponse:
        """处理 LLM 响应"""
        content = response.get("content", "")
        tool_calls = response.get("tool_calls")

        workflow_changed = False
        tool_results = []
        tool_call_records = []

        # 处理工具调用
        if tool_calls:
            for tool_call in tool_calls:
                func_name = tool_call.get("function", {}).get("name")
                args_str = tool_call.get("function", {}).get("arguments", "{}")

                try:
                    args = (
                        json.loads(args_str) if isinstance(args_str, str) else args_str
                    )
                except json.JSONDecodeError:
                    args = {}

                logger.info(f"执行工具调用: {func_name}({list(args.keys())})")

                # 执行工具
                result = await self._execute_tool(func_name, args)
                tool_results.append(result)

                # 记录工具调用
                tool_record = {
                    "name": func_name,
                    "arguments": args,
                    "result": result.to_dict(),
                }
                tool_call_records.append(tool_record)

                # 添加到工具调用历史（用于上下文构建）
                self.tool_call_history.append(tool_record)
                # 保持历史记录在合理范围内（最多保留20条）
                if len(self.tool_call_history) > 20:
                    self.tool_call_history = self.tool_call_history[-20:]

                if result.workflow_changed:
                    workflow_changed = True

        # 构建最终响应消息 - 优先使用工具执行结果
        final_message = ""

        if tool_results:
            # 有工具调用时，优先使用工具结果消息（更准确、更用户友好）
            result_messages = [r.message for r in tool_results if r.message]
            if result_messages:
                final_message = "\n\n".join(result_messages)

            # 如果工具结果没有消息但 LLM 有输出，使用 LLM 的输出
            if not final_message and content:
                # 过滤掉一些临时性的提示语
                filtered_content = self._filter_interim_messages(content)
                if filtered_content:
                    final_message = filtered_content
        else:
            # 没有工具调用时，验证并清理 LLM 的输出
            final_message = self._validate_and_clean_response(content)

        if not final_message:
            final_message = "操作完成。"

        # 更新对话历史
        self.conversation_history.append({"role": "user", "content": user_message})
        self.conversation_history.append(
            {"role": "assistant", "content": final_message}
        )

        # 构建响应数据
        data = None
        if tool_results:
            # 合并所有工具结果的数据
            data = {}
            for result in tool_results:
                if result.data:
                    data.update(result.data)

        return DialogueResponse(
            message=final_message,
            data=data,
            workflow_changed=workflow_changed,
            tool_calls=tool_call_records,
        )

    def _filter_interim_messages(self, content: str) -> str:
        """过滤掉临时性的提示消息"""
        # 移除类似 "正在为您..." "让我..." 等临时性提示
        lines = content.split("\n")
        filtered_lines = []

        skip_patterns = [
            r"^正在为您",
            r"^让我",
            r"^我来",
            r"^好的，",
            r"^现在",
            r"^\s*$",  # 空行
        ]

        for line in lines:
            should_skip = False
            for pattern in skip_patterns:
                if re.match(pattern, line.strip()):
                    should_skip = True
                    break
            if not should_skip:
                filtered_lines.append(line)

        return "\n".join(filtered_lines).strip()

    def _validate_and_clean_response(self, content: str) -> str:
        """验证响应内容，过滤不应显示给用户的内容"""
        content = content.strip()

        # 检测是否是未解析的工具调用 JSON
        if content.startswith("{") and content.endswith("}"):
            try:
                data = json.loads(content)
                if "name" in data and "arguments" in data:
                    # 这是一个未被执行的工具调用，不应该显示给用户
                    tool_name = data.get("name", "unknown")
                    logger.warning(
                        f"检测到未执行的工具调用 JSON: {tool_name}，将过滤掉"
                    )
                    return ""  # 返回空，让默认消息生效
            except json.JSONDecodeError:
                pass

        # 检测是否包含看起来像工具调用的 JSON 片段
        # 例如: 一些文本 {"name": "xxx", "arguments": {...}} 更多文本
        tool_call_pattern = r'\{\s*"name"\s*:\s*"[^"]+"\s*,\s*"arguments"\s*:'
        if re.search(tool_call_pattern, content):
            # 尝试移除 JSON 部分，保留其他文本
            # 匹配完整的 JSON 对象
            json_pattern = (
                r'\{[^{}]*"name"[^{}]*"arguments"[^{}]*(?:\{[^{}]*\})?[^{}]*\}'
            )
            cleaned = re.sub(json_pattern, "", content)
            cleaned = re.sub(r"\n{2,}", "\n", cleaned).strip()
            if cleaned:
                return cleaned
            else:
                logger.warning("响应内容仅包含工具调用 JSON，将过滤掉")
                return ""

        return content

    async def _execute_tool(
        self, tool_name: str, args: Dict[str, Any]
    ) -> OperationResult:
        """执行工具"""
        handler = self._tool_handlers.get(tool_name)
        if not handler:
            return OperationResult(success=False, message=f"未知工具: {tool_name}")

        try:
            return await handler(args)
        except Exception as e:
            logger.error(f"执行工具 {tool_name} 失败: {e}")
            return OperationResult(success=False, message=f"执行失败: {str(e)}")

    # ========== 工具处理器 ==========

    async def _handle_create_workflow_plan(
        self, args: Dict[str, Any]
    ) -> OperationResult:
        return await self.ops.create_workflow_plan(
            task_description=args.get("task_description", "")
        )

    async def _handle_add_agent_to_plan(self, args: Dict[str, Any]) -> OperationResult:
        return await self.ops.add_agent_to_plan(
            name=args.get("name", ""),
            task=args.get("task", ""),
            display_name=args.get("display_name"),
            dependencies=args.get("dependencies"),
            tools=args.get("tools"),
            position=args.get("position", "auto"),
        )

    async def _handle_remove_agent_from_plan(
        self, args: Dict[str, Any]
    ) -> OperationResult:
        return await self.ops.remove_agent_from_plan(
            agent_name=args.get("agent_name", "")
        )

    async def _handle_modify_agent_spec(self, args: Dict[str, Any]) -> OperationResult:
        return await self.ops.modify_agent_spec(
            agent_name=args.get("agent_name", ""),
            new_name=args.get("new_name"),
            new_display_name=args.get("new_display_name"),
            new_task=args.get("new_task"),
            add_dependencies=args.get("add_dependencies"),
            remove_dependencies=args.get("remove_dependencies"),
            add_tools=args.get("add_tools"),
            remove_tools=args.get("remove_tools"),
        )

    async def _handle_modify_dependencies(
        self, args: Dict[str, Any]
    ) -> OperationResult:
        return await self.ops.modify_dependencies(
            agent_name=args.get("agent_name", ""),
            depends_on=args.get("depends_on", []),
        )

    async def _handle_set_parallel_agents(
        self, args: Dict[str, Any]
    ) -> OperationResult:
        return await self.ops.set_parallel_agents(
            agent_names=args.get("agent_names", [])
        )

    async def _handle_reorder_workflow(self, args: Dict[str, Any]) -> OperationResult:
        return await self.ops.reorder_workflow(new_order=args.get("new_order", []))

    async def _handle_regenerate_plan(self, args: Dict[str, Any]) -> OperationResult:
        return await self.ops.regenerate_plan(
            feedback=args.get("feedback"),
            constraints=args.get("constraints"),
        )

    async def _handle_approve_current_state(
        self, args: Dict[str, Any]
    ) -> OperationResult:
        return await self.ops.approve_current_state()

    async def _handle_rollback_to_checkpoint(
        self, args: Dict[str, Any]
    ) -> OperationResult:
        return await self.ops.rollback_to_checkpoint(
            checkpoint_id=args.get("checkpoint_id")
        )

    async def _handle_save_workflow(self, args: Dict[str, Any]) -> OperationResult:
        return await self.ops.save_workflow(
            path=args.get("path"),
            name=args.get("name"),
            description=args.get("description"),
            tags=args.get("tags"),
            author=args.get("author", "user"),
        )

    async def _handle_execute_workflow(self, args: Dict[str, Any]) -> OperationResult:
        return await self.ops.execute_workflow(params=args.get("params"))

    async def _handle_get_workflow_status(
        self, args: Dict[str, Any]
    ) -> OperationResult:
        """获取工作流状态"""
        plan = self.ops.get_current_plan()
        agents = self.ops.get_current_agents()
        workflow = self.ops.get_current_workflow()
        status = self.ops.get_execution_status()
        stage = self.ops.get_current_stage()
        checkpoints = self.ops.get_checkpoints()

        status_parts = [f"当前阶段: {stage}"]

        if agents:
            status_parts.append(f"Agent 数量: {len(agents)}")
            for a in agents:
                deps = a.get("dependencies", [])
                status_parts.append(
                    f"  - {a.get('name')}: {a.get('task', '')[:50]}..."
                    + (f" [依赖: {', '.join(deps)}]" if deps else "")
                )

        if workflow:
            status_parts.append(
                f"工作流已组装: {workflow.get('workflow_id', 'unknown')}"
            )

        status_parts.append(f"检查点数量: {len(checkpoints)}")
        status_parts.append(
            f"执行状态: {'执行中' if status.get('is_executing') else '未执行'}"
        )

        return OperationResult(
            success=True,
            message="\n".join(status_parts),
            data={
                "stage": stage,
                "agents": agents,
                "workflow": workflow,
                "checkpoints_count": len(checkpoints),
                "is_executing": status.get("is_executing", False),
            },
        )

    async def _handle_optimize_agent_prompt(
        self, args: Dict[str, Any]
    ) -> OperationResult:
        """优化 Agent 的 Prompt 配置"""
        return await self.ops.optimize_agent_prompt(
            agent_name=args.get("agent_name", ""),
            field=args.get("field", ""),
            current_value=args.get("current_value", ""),
            optimization_goal=args.get("optimization_goal"),
        )

    async def _handle_update_agent_definition(
        self, args: Dict[str, Any]
    ) -> OperationResult:
        """更新 Agent 定义"""
        return await self.ops.update_agent_definition(
            agent_name=args.get("agent_name", ""),
            updates=args.get("updates", {}),
        )

    async def _handle_get_agent_definition(
        self, args: Dict[str, Any]
    ) -> OperationResult:
        """获取 Agent 定义"""
        return await self.ops.get_agent_definition(
            agent_name=args.get("agent_name", ""),
        )

    async def _handle_regenerate_agent(self, args: Dict[str, Any]) -> OperationResult:
        """重新生成 Agent"""
        return await self.ops.regenerate_agent(
            agent_name=args.get("agent_name", ""),
            feedback=args.get("feedback"),
        )

    async def _handle_iterate_plan(self, args: Dict[str, Any]) -> OperationResult:
        """智能迭代规划"""
        return await self.ops.iterate_plan(
            user_request=args.get("user_request", ""),
            include_history=args.get("include_history", True),
        )

    def clear_history(self) -> None:
        """清除对话历史"""
        self.conversation_history.clear()

    def get_conversation_history(self) -> List[Dict[str, str]]:
        """获取对话历史"""
        return self.conversation_history.copy()
