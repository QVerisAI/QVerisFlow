"""
自然语言意图处理器

解析用户自然语言输入，提取意图和实体，用于对话式工作流构建
"""

from enum import Enum
from dataclasses import dataclass, field
from typing import Dict, Any, Optional, List
from datetime import datetime
import json
import re

from src.utils.logger import get_logger

logger = get_logger()


class UserIntent(Enum):
    """用户意图类型"""
    
    # === 构建相关 ===
    CREATE = "create"           # 创建新工作流
    MODIFY = "modify"           # 修改现有内容
    ADD_NODE = "add_node"       # 添加节点
    REMOVE_NODE = "remove_node" # 删除节点
    MODIFY_NODE = "modify_node" # 修改节点
    ADD_EDGE = "add_edge"       # 添加边
    APPROVE = "approve"         # 批准当前状态
    ROLLBACK = "rollback"       # 回滚
    SAVE = "save"               # 保存工作流
    LOAD = "load"               # 加载工作流
    
    # === 执行相关 ===
    EXECUTE = "execute"                     # 执行工作流
    EXECUTE_WITH_PARAMS = "execute_with_params"  # 带参数执行
    PAUSE = "pause"                         # 暂停执行
    RESUME = "resume"                       # 恢复执行
    STOP = "stop"                           # 停止执行
    INTERVENE = "intervene"                 # 干预当前节点
    SKIP_NODE = "skip_node"                 # 跳过节点
    INJECT_CONTEXT = "inject_context"       # 注入上下文
    
    # === 通用 ===
    QUESTION = "question"       # 提问/澄清
    HELP = "help"               # 帮助
    STATUS = "status"           # 查询状态
    LIST = "list"               # 列出内容
    UNKNOWN = "unknown"         # 未知意图


@dataclass
class ParsedIntent:
    """解析后的意图"""
    intent: UserIntent
    confidence: float
    entities: Dict[str, Any] = field(default_factory=dict)
    original_text: str = ""
    suggested_action: Optional[str] = None
    reasoning: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "intent": self.intent.value,
            "confidence": self.confidence,
            "entities": self.entities,
            "original_text": self.original_text,
            "suggested_action": self.suggested_action,
            "reasoning": self.reasoning,
        }


@dataclass
class BuilderContext:
    """构建器上下文，用于意图解析"""
    stage: str = "idle"  # idle, planning, generating, workflow, executing
    agents: List[Dict[str, Any]] = field(default_factory=list)
    workflow_nodes: List[Dict[str, Any]] = field(default_factory=list)
    workflow_edges: List[Dict[str, Any]] = field(default_factory=list)
    checkpoints: List[str] = field(default_factory=list)
    is_executing: bool = False
    current_node: Optional[str] = None
    conversation_history: List[Dict[str, str]] = field(default_factory=list)


class NLIntentProcessor:
    """
    自然语言意图处理器
    
    使用 LLM 解析用户自然语言输入，提取意图和实体
    """
    
    # 意图关键词映射（用于快速匹配）
    INTENT_KEYWORDS = {
        UserIntent.CREATE: [
            "创建", "新建", "生成", "建立", "做一个", "帮我做", "帮我创建",
            "create", "new", "make", "build", "generate"
        ],
        UserIntent.EXECUTE: [
            "执行", "运行", "跑一下", "测试", "启动", "开始执行", "run", "execute", "start"
        ],
        UserIntent.PAUSE: [
            "暂停", "等一下", "停一下", "pause", "wait", "hold"
        ],
        UserIntent.RESUME: [
            "继续", "恢复", "接着", "resume", "continue"
        ],
        UserIntent.STOP: [
            "停止", "终止", "取消", "stop", "cancel", "abort", "terminate"
        ],
        UserIntent.APPROVE: [
            "确认", "批准", "同意", "可以", "好的", "就这样", "没问题", "ok", "yes",
            "approve", "confirm", "accept", "looks good", "lgtm"
        ],
        UserIntent.ROLLBACK: [
            "回滚", "撤销", "返回", "回退", "rollback", "undo", "revert"
        ],
        UserIntent.ADD_NODE: [
            "添加", "加一个", "增加", "再加", "新增", "需要添加", "需要一个", "需要增加",
            "还需要", "补充一个", "加入", "引入", "插入",
            "add", "insert", "include", "need"
        ],
        UserIntent.REMOVE_NODE: [
            "删除", "移除", "去掉", "remove", "delete"
        ],
        UserIntent.MODIFY: [
            "修改", "改一下", "调整", "更新", "优化", "改进", "modify", "change", "update", "edit"
        ],
        UserIntent.SKIP_NODE: [
            "跳过", "略过", "skip"
        ],
        UserIntent.SAVE: [
            "保存", "存储", "save", "store"
        ],
        UserIntent.LOAD: [
            "加载", "打开", "load", "open"
        ],
        UserIntent.STATUS: [
            "状态", "进度", "情况", "status", "progress"
        ],
        UserIntent.HELP: [
            "帮助", "怎么用", "如何使用", "help", "how to"
        ],
        UserIntent.QUESTION: [
            "这是什么", "为什么", "哪个", "what is", "why", "which", "explain"
        ],
        UserIntent.INJECT_CONTEXT: [
            "注入", "添加上下文", "补充信息", "inject", "context"
        ],
        UserIntent.INTERVENE: [
            "干预", "介入", "插手", "intervene"
        ],
    }
    
    def __init__(self, llm_client: Any = None):
        """
        初始化意图处理器
        
        Args:
            llm_client: LLM 客户端（可选，用于复杂意图解析）
        """
        self.llm_client = llm_client
    
    async def parse(
        self,
        user_message: str,
        context: Optional[BuilderContext] = None
    ) -> ParsedIntent:
        """
        解析用户消息
        
        Args:
            user_message: 用户输入的自然语言
            context: 当前构建器上下文
            
        Returns:
            解析后的意图和实体
        """
        if context is None:
            context = BuilderContext()
        
        # 1. 先尝试快速关键词匹配
        quick_result = self._quick_match(user_message, context)
        if quick_result.confidence >= 0.8:
            logger.debug(f"快速匹配成功: {quick_result.intent.value} (置信度: {quick_result.confidence})")
            return quick_result
        
        # 2. 使用 LLM 进行深度解析
        if self.llm_client:
            try:
                llm_result = await self._llm_parse(user_message, context)
                if llm_result.confidence > quick_result.confidence:
                    logger.debug(f"LLM 解析成功: {llm_result.intent.value} (置信度: {llm_result.confidence})")
                    return llm_result
            except Exception as e:
                logger.warning(f"LLM 意图解析失败: {e}")
        
        # 3. 返回快速匹配结果（可能是 UNKNOWN）
        return quick_result
    
    def _quick_match(self, message: str, context: BuilderContext) -> ParsedIntent:
        """快速关键词匹配"""
        message_lower = message.lower().strip()
        
        # 检查执行上下文
        if context.is_executing:
            # 执行中，优先匹配执行相关意图
            execution_intents = [
                UserIntent.PAUSE, UserIntent.RESUME, UserIntent.STOP,
                UserIntent.SKIP_NODE, UserIntent.INTERVENE, UserIntent.INJECT_CONTEXT
            ]
            for intent in execution_intents:
                if self._match_intent_keywords(message_lower, intent):
                    entities = self._extract_entities(message, intent, context)
                    return ParsedIntent(
                        intent=intent,
                        confidence=0.85,
                        entities=entities,
                        original_text=message,
                    )
        
        # 通用意图匹配
        best_match = UserIntent.UNKNOWN
        best_confidence = 0.0
        
        for intent, keywords in self.INTENT_KEYWORDS.items():
            for keyword in keywords:
                if keyword in message_lower:
                    # 计算置信度（基于关键词长度和位置）
                    confidence = self._calculate_confidence(message_lower, keyword, intent, context)
                    if confidence > best_confidence:
                        best_confidence = confidence
                        best_match = intent
        
        # 提取实体
        entities = self._extract_entities(message, best_match, context)
        
        return ParsedIntent(
            intent=best_match,
            confidence=best_confidence if best_match != UserIntent.UNKNOWN else 0.3,
            entities=entities,
            original_text=message,
        )
    
    def _match_intent_keywords(self, message: str, intent: UserIntent) -> bool:
        """检查消息是否包含意图关键词"""
        keywords = self.INTENT_KEYWORDS.get(intent, [])
        return any(kw in message for kw in keywords)
    
    def _calculate_confidence(
        self,
        message: str,
        keyword: str,
        intent: UserIntent,
        context: BuilderContext
    ) -> float:
        """计算匹配置信度"""
        base_confidence = 0.65
        
        # 关键词越长，置信度越高
        if len(keyword) >= 3:
            base_confidence += 0.1
        if len(keyword) >= 5:
            base_confidence += 0.05
        
        # 关键词在消息开头，置信度更高
        if message.startswith(keyword):
            base_confidence += 0.1
        
        # ADD_NODE 特殊处理：如果包含功能性词汇（分析、监测、处理等），提高置信度
        if intent == UserIntent.ADD_NODE:
            functional_words = ["分析", "监测", "处理", "收集", "生成", "评估", "验证", "检测", "节点", "环节", "步骤", "agent"]
            if any(w in message for w in functional_words):
                base_confidence += 0.15
        
        # 根据上下文调整
        if context.stage == "idle" and intent == UserIntent.CREATE:
            base_confidence += 0.1
        elif context.stage in ["planning", "agent", "workflow"] and intent == UserIntent.ADD_NODE:
            # 在构建阶段，添加节点意图置信度更高
            base_confidence += 0.1
        elif context.stage == "workflow" and intent in [UserIntent.APPROVE, UserIntent.EXECUTE]:
            base_confidence += 0.1
        elif context.is_executing and intent in [UserIntent.PAUSE, UserIntent.STOP]:
            base_confidence += 0.1
        
        return min(base_confidence, 0.95)
    
    def _extract_entities(
        self,
        message: str,
        intent: UserIntent,
        context: BuilderContext
    ) -> Dict[str, Any]:
        """提取实体"""
        entities = {}
        
        if intent == UserIntent.CREATE:
            # 提取任务描述
            entities["task"] = message
            
        elif intent == UserIntent.ADD_NODE:
            # 提取节点描述
            # 移除常见前缀
            node_desc = message
            for prefix in ["添加", "加一个", "增加", "再加", "新增", "add", "insert"]:
                node_desc = node_desc.replace(prefix, "").strip()
            entities["node_description"] = node_desc
            
        elif intent == UserIntent.MODIFY_NODE:
            # 尝试提取节点 ID 和修改内容
            entities["modifications"] = message
            
        elif intent == UserIntent.ROLLBACK:
            # 尝试提取检查点 ID
            for ckpt in context.checkpoints:
                if ckpt in message:
                    entities["checkpoint_id"] = ckpt
                    break
            # 如果没有指定，使用最近的检查点
            if "checkpoint_id" not in entities and context.checkpoints:
                entities["checkpoint_id"] = context.checkpoints[-1]
                
        elif intent == UserIntent.SKIP_NODE:
            # 提取要跳过的节点
            if context.current_node:
                entities["node_id"] = context.current_node
                
        elif intent == UserIntent.INJECT_CONTEXT:
            # 提取要注入的上下文
            # 移除前缀
            ctx_content = message
            for prefix in ["注入", "添加上下文", "补充信息", "inject", "context"]:
                ctx_content = ctx_content.replace(prefix, "").strip()
            entities["context_content"] = ctx_content
            
        elif intent in [UserIntent.EXECUTE, UserIntent.EXECUTE_WITH_PARAMS]:
            # 尝试提取执行参数
            params = self._extract_execution_params(message)
            if params:
                entities["params"] = params
                if params:
                    # 如果有参数，升级为 EXECUTE_WITH_PARAMS
                    pass
        
        return entities
    
    def _extract_execution_params(self, message: str) -> Dict[str, Any]:
        """从消息中提取执行参数"""
        params = {}
        
        # 尝试提取 JSON 格式参数
        json_match = re.search(r'\{[^}]+\}', message)
        if json_match:
            try:
                params = json.loads(json_match.group())
                return params
            except json.JSONDecodeError:
                pass
        
        # 尝试提取常见参数模式
        # "目标公司是特斯拉" -> {"company": "特斯拉"}
        company_patterns = [
            r'目标公司[是为]?\s*(.+?)(?:\s|$|，|,)',
            r'公司[是为]?\s*(.+?)(?:\s|$|，|,)',
            r'分析\s*(.+?)\s*(?:的|股票|公司)',
        ]
        for pattern in company_patterns:
            match = re.search(pattern, message)
            if match:
                params["company"] = match.group(1).strip()
                break
        
        # 尝试提取股票代码
        ticker_match = re.search(r'([A-Z]{1,5})', message)
        if ticker_match:
            params["ticker"] = ticker_match.group(1)
        
        return params
    
    async def _llm_parse(
        self,
        message: str,
        context: BuilderContext
    ) -> ParsedIntent:
        """使用 LLM 进行深度意图解析"""
        prompt = self._build_intent_prompt(message, context)
        
        # 使用 UnifiedLLMClient 的 call 方法
        messages = [{"role": "user", "content": prompt}]
        response = await self.llm_client.call(messages)
        
        # 提取响应内容
        if hasattr(response, 'content'):
            content = response.content
        elif isinstance(response, dict) and 'content' in response:
            content = response['content']
        elif isinstance(response, str):
            content = response
        else:
            content = str(response)
        
        return self._parse_llm_response(content, message)
    
    def _build_intent_prompt(self, message: str, context: BuilderContext) -> str:
        """构建意图解析提示词"""
        # 构建详细的上下文信息
        context_info = f"当前阶段: {context.stage}"
        
        if context.is_executing:
            context_info += "\n状态: 工作流正在执行中"
            if context.current_node:
                context_info += f"\n当前执行节点: {context.current_node}"
        
        # 添加已有 Agent 信息
        if context.agents:
            agent_names = []
            for a in context.agents:
                name = a.get('name', '') if isinstance(a, dict) else getattr(a, 'name', '')
                if name:
                    agent_names.append(name)
            if agent_names:
                context_info += f"\n已有 Agents: {', '.join(agent_names)}"
        
        # 添加最近对话历史
        recent_history = ""
        if context.conversation_history:
            recent = context.conversation_history[-3:]  # 最近3轮
            for msg in recent:
                role = msg.get('role', 'user')
                content = msg.get('content', '')[:100]  # 截断
                recent_history += f"\n- {role}: {content}"
        
        return f"""你是一个工作流构建助手的意图解析器。用户正在交互式构建智能体工作流。

## 当前上下文
{context_info}
{f"近期对话:{recent_history}" if recent_history else ""}

## 用户消息
"{message}"

## 意图分类
根据用户消息，判断最可能的意图：

**构建类意图（工作流构建阶段）**:
- create: 用户想创建新的工作流
- add_node: 用户想添加新的节点/Agent（关键词：添加、需要、加入、补充、引入）
- remove_node: 用户想删除节点
- modify_node: 用户想修改现有节点
- approve: 用户确认/批准当前方案
- rollback: 用户想回滚/撤销

**执行类意图（工作流执行阶段）**:
- execute: 用户想执行工作流
- pause: 暂停执行
- resume: 恢复执行
- stop: 停止执行

**通用意图**:
- question: 用户在询问/澄清问题
- help: 用户需要帮助
- status: 查询状态

## 判断规则
1. 如果用户提到"需要"、"添加"、"加一个"等词汇，配合节点/功能描述，应判断为 add_node
2. 如果用户说"好的"、"确认"等简短确认词，应判断为 approve
3. 如果用户描述的是一个完整的新任务，应判断为 create

请以 JSON 格式返回（只返回 JSON）:
{{
    "intent": "意图类型（必须是上述列表中的一个）",
    "confidence": 0.0-1.0,
    "entities": {{"node_description": "如果是add_node，提取节点描述"}},
    "reasoning": "简短推理"
}}"""
    
    def _get_intent_description(self, intent: UserIntent) -> str:
        """获取意图描述"""
        descriptions = {
            UserIntent.CREATE: "创建新工作流",
            UserIntent.MODIFY: "修改现有内容",
            UserIntent.ADD_NODE: "添加节点",
            UserIntent.REMOVE_NODE: "删除节点",
            UserIntent.MODIFY_NODE: "修改节点",
            UserIntent.ADD_EDGE: "添加边",
            UserIntent.APPROVE: "批准当前状态",
            UserIntent.ROLLBACK: "回滚到检查点",
            UserIntent.SAVE: "保存工作流",
            UserIntent.LOAD: "加载工作流",
            UserIntent.EXECUTE: "执行工作流",
            UserIntent.EXECUTE_WITH_PARAMS: "带参数执行工作流",
            UserIntent.PAUSE: "暂停执行",
            UserIntent.RESUME: "恢复执行",
            UserIntent.STOP: "停止执行",
            UserIntent.INTERVENE: "干预当前节点",
            UserIntent.SKIP_NODE: "跳过节点",
            UserIntent.INJECT_CONTEXT: "注入上下文",
            UserIntent.QUESTION: "提问/澄清",
            UserIntent.HELP: "请求帮助",
            UserIntent.STATUS: "查询状态",
            UserIntent.LIST: "列出内容",
            UserIntent.UNKNOWN: "未知意图",
        }
        return descriptions.get(intent, "未知")
    
    def _parse_llm_response(self, response: str, original_message: str) -> ParsedIntent:
        """解析 LLM 响应"""
        try:
            # 提取 JSON
            json_match = re.search(r'\{[^{}]*\}', response, re.DOTALL)
            if json_match:
                data = json.loads(json_match.group())
                
                intent_str = data.get("intent", "unknown")
                try:
                    intent = UserIntent(intent_str)
                except ValueError:
                    intent = UserIntent.UNKNOWN
                
                return ParsedIntent(
                    intent=intent,
                    confidence=float(data.get("confidence", 0.7)),
                    entities=data.get("entities", {}),
                    original_text=original_message,
                    reasoning=data.get("reasoning"),
                )
        except (json.JSONDecodeError, Exception) as e:
            logger.warning(f"解析 LLM 响应失败: {e}")
        
        return ParsedIntent(
            intent=UserIntent.UNKNOWN,
            confidence=0.3,
            original_text=original_message,
        )
