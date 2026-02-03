"""
Hooks 管理器

集成 Claude Agent SDK 的 Hooks 机制到 agent_framework 的编排层。

设计原则：
1. 提供常用的 Hook 模板
2. 与验证层集成
3. 支持跨 Agent 的 Hook 共享
"""

from typing import Dict, Any, Optional, List, Callable, Awaitable
from enum import Enum
from src.utils.logger import get_logger

logger = get_logger()


class HookEvent(str, Enum):
    """Hook 事件类型"""
    
    PRE_TOOL_USE = "PreToolUse"  # 工具使用前
    POST_TOOL_USE = "PostToolUse"  # 工具使用后
    PRE_RESPONSE = "PreResponse"  # 响应前
    POST_RESPONSE = "PostResponse"  # 响应后


class HookAction(str, Enum):
    """Hook 动作"""
    
    ALLOW = "allow"  # 允许
    DENY = "deny"  # 拒绝
    MODIFY = "modify"  # 修改
    LOG = "log"  # 仅记录


class HooksManager:
    """
    Hooks 管理器
    
    提供 Hook 的注册、管理和执行。
    
    用法：
    ```python
    from orchestration import HooksManager, HookEvent
    
    # 创建管理器
    hooks_mgr = HooksManager()
    
    # 注册 Hook
    @hooks_mgr.register_hook(HookEvent.PRE_TOOL_USE, matcher="Bash")
    async def check_bash_command(input_data, tool_use_id, context):
        command = input_data.get("tool_input", {}).get("command", "")
        if "rm -rf" in command:
            return {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": "危险命令禁止执行"
                }
            }
        return {}
    
    # 获取配置
    hook_config = hooks_mgr.get_hooks_config()
    
    # 用于 ClaudeNativeAgent
    agent = ClaudeNativeAgent(
        ...,
        hooks=hook_config
    )
    ```
    """
    
    def __init__(self):
        self.hooks: Dict[str, List[Dict[str, Any]]] = {}
        
        logger.info("✅ Hooks 管理器初始化")
    
    def register_hook(
        self,
        event: HookEvent,
        matcher: str,
        hook_func: Optional[Callable] = None
    ):
        """
        注册 Hook（可作为装饰器使用）
        
        Args:
            event: Hook 事件
            matcher: 匹配器（工具名称等）
            hook_func: Hook 函数（装饰器模式下为 None）
        
        Returns:
            装饰器或 None
        """
        def decorator(func: Callable):
            self._add_hook(event, matcher, func)
            return func
        
        if hook_func is not None:
            # 直接调用
            self._add_hook(event, matcher, hook_func)
            return None
        else:
            # 装饰器模式
            return decorator
    
    def _add_hook(
        self,
        event: HookEvent,
        matcher: str,
        hook_func: Callable
    ):
        """内部方法：添加 Hook"""
        event_name = event.value
        
        if event_name not in self.hooks:
            self.hooks[event_name] = []
        
        # 构建 HookMatcher（Claude SDK 格式）
        hook_matcher = {
            "matcher": matcher,
            "hook": hook_func
        }
        
        self.hooks[event_name].append(hook_matcher)
        
        logger.info(f"✅ 注册 Hook: {event_name} - {matcher}")
    
    def get_hooks_config(self) -> Dict[str, List[Any]]:
        """
        获取适用于 Claude SDK 的 Hooks 配置
        
        Returns:
            Hooks 配置字典
        """
        # 转换为 Claude SDK 格式
        try:
            from claude_agent_sdk import HookMatcher
            
            config = {}
            for event_name, matchers in self.hooks.items():
                config[event_name] = []
                for matcher_config in matchers:
                    hook_matcher = HookMatcher(
                        matcher=matcher_config["matcher"],
                        hooks=[matcher_config["hook"]]
                    )
                    config[event_name].append(hook_matcher)
            
            return config
        
        except ImportError:
            logger.warning("Claude SDK 未安装，返回原始配置")
            return self.hooks
    
    def remove_hook(self, event: HookEvent, matcher: str):
        """
        移除 Hook
        
        Args:
            event: Hook 事件
            matcher: 匹配器
        """
        event_name = event.value
        
        if event_name in self.hooks:
            self.hooks[event_name] = [
                h for h in self.hooks[event_name]
                if h["matcher"] != matcher
            ]
            
            logger.info(f"🗑️ 移除 Hook: {event_name} - {matcher}")
    
    def clear_hooks(self, event: Optional[HookEvent] = None):
        """
        清除 Hooks
        
        Args:
            event: 事件类型（None 表示清除所有）
        """
        if event:
            event_name = event.value
            if event_name in self.hooks:
                self.hooks[event_name] = []
                logger.info(f"🗑️ 清除 Hook 事件: {event_name}")
        else:
            self.hooks = {}
            logger.info("🗑️ 清除所有 Hooks")


# ========== 预定义 Hooks ==========

class CommonHooks:
    """
    常用 Hooks 模板
    
    提供开箱即用的 Hook 函数。
    """
    
    @staticmethod
    async def block_dangerous_commands(
        input_data: Dict[str, Any],
        tool_use_id: str,
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        阻止危险命令执行
        
        适用于 Bash、Shell 等工具。
        """
        tool_name = input_data.get("tool_name", "")
        tool_input = input_data.get("tool_input", {})
        
        if tool_name in ["Bash", "Shell"]:
            command = tool_input.get("command", "")
            
            # 危险命令列表
            dangerous_patterns = [
                "rm -rf",
                "mkfs",
                "dd if=",
                "> /dev/sd",
                "fork bomb",
                ":(){ :|:& };:",
            ]
            
            for pattern in dangerous_patterns:
                if pattern in command:
                    return {
                        "hookSpecificOutput": {
                            "hookEventName": "PreToolUse",
                            "permissionDecision": "deny",
                            "permissionDecisionReason": f"检测到危险命令模式: {pattern}"
                        }
                    }
        
        return {}
    
    @staticmethod
    async def log_tool_usage(
        input_data: Dict[str, Any],
        tool_use_id: str,
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        记录工具使用日志
        
        适用于所有工具。
        """
        tool_name = input_data.get("tool_name", "unknown")
        tool_input = input_data.get("tool_input", {})
        
        logger.info(f"🔧 工具调用: {tool_name} - {tool_use_id}")
        logger.debug(f"参数: {tool_input}")
        
        return {}
    
    @staticmethod
    async def rate_limit_tool(
        input_data: Dict[str, Any],
        tool_use_id: str,
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        工具速率限制
        
        防止工具被过度调用。
        """
        tool_name = input_data.get("tool_name", "")
        
        # 这里需要实现速率限制逻辑（基于 Redis 或内存缓存）
        # 示例：检查最近 1 分钟内的调用次数
        
        # 临时实现：简单计数
        if not hasattr(CommonHooks, '_call_counts'):
            CommonHooks._call_counts = {}
        
        if tool_name not in CommonHooks._call_counts:
            CommonHooks._call_counts[tool_name] = 0
        
        CommonHooks._call_counts[tool_name] += 1
        
        # 假设限制为 10 次/分钟
        if CommonHooks._call_counts[tool_name] > 10:
            return {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": f"工具 {tool_name} 调用频率过高，请稍后再试"
                }
            }
        
        return {}
    
    @staticmethod
    async def validate_tool_input(
        input_data: Dict[str, Any],
        tool_use_id: str,
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        验证工具输入
        
        检查输入是否符合预期格式。
        """
        tool_input = input_data.get("tool_input", {})
        
        # 这里可以添加具体的验证逻辑
        # 例如：检查 SQL 注入、XSS 等
        
        return {}
    
    @staticmethod
    async def integrate_with_verifier(
        verifier: Any,  # BaseVerifier
    ) -> Callable:
        """
        与验证层集成的 Hook
        
        在工具使用后自动验证结果。
        
        Args:
            verifier: 验证器实例
        
        Returns:
            Hook 函数
        """
        async def post_tool_use_hook(
            input_data: Dict[str, Any],
            tool_use_id: str,
            context: Dict[str, Any]
        ) -> Dict[str, Any]:
            tool_output = input_data.get("tool_output", {})
            
            # 使用验证器验证工具输出
            try:
                result = await verifier.verify(
                    output=tool_output,
                    context=context
                )
                
                if not result.passed:
                    logger.warning(f"⚠️ 工具输出验证失败: {result.feedback}")
                    
                    # 可以选择拒绝或修改
                    return {
                        "hookSpecificOutput": {
                            "hookEventName": "PostToolUse",
                            "feedback": result.feedback,
                            "score": result.score
                        }
                    }
            
            except Exception as e:
                logger.error(f"❌ 验证器执行失败: {e}")
            
            return {}
        
        return post_tool_use_hook


# ========== 便捷函数 ==========

def create_security_hooks() -> Dict[str, List[Any]]:
    """
    创建安全相关的 Hooks 配置
    
    Returns:
        Hooks 配置
    """
    manager = HooksManager()
    
    # 阻止危险命令
    manager.register_hook(
        HookEvent.PRE_TOOL_USE,
        "Bash",
        CommonHooks.block_dangerous_commands
    )
    
    # 记录所有工具使用
    manager.register_hook(
        HookEvent.PRE_TOOL_USE,
        "*",  # 匹配所有工具
        CommonHooks.log_tool_usage
    )
    
    return manager.get_hooks_config()


def create_rate_limit_hooks(tools: List[str]) -> Dict[str, List[Any]]:
    """
    为指定工具创建速率限制 Hooks
    
    Args:
        tools: 工具名称列表
    
    Returns:
        Hooks 配置
    """
    manager = HooksManager()
    
    for tool_name in tools:
        manager.register_hook(
            HookEvent.PRE_TOOL_USE,
            tool_name,
            CommonHooks.rate_limit_tool
        )
    
    return manager.get_hooks_config()


def create_verifier_hooks(verifier: Any) -> Dict[str, List[Any]]:
    """
    创建与验证器集成的 Hooks
    
    Args:
        verifier: 验证器实例
    
    Returns:
        Hooks 配置
    """
    import asyncio
    
    manager = HooksManager()
    
    # 创建集成 Hook
    hook_func = asyncio.run(CommonHooks.integrate_with_verifier(verifier))
    
    manager.register_hook(
        HookEvent.POST_TOOL_USE,
        "*",
        hook_func
    )
    
    return manager.get_hooks_config()

