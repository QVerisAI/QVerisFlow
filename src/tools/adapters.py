"""
LangChain 工具适配器

将框架工具转换为 LangChain Tool 格式。
"""

from typing import Dict, Any, Callable, Optional
import asyncio
import inspect
from src.utils.logger import get_logger

from ..definitions import ToolDefinition

logger = get_logger()


class LangChainToolAdapter:
    """将框架工具转换为 LangChain Tool"""
    
    @staticmethod
    def adapt(
        definition: ToolDefinition,
        implementation: Callable
    ):
        """
        将工具定义转换为 LangChain StructuredTool
        
        Args:
            definition: 工具定义
            implementation: 工具实现函数
        
        Returns:
            LangChain StructuredTool
        """
        try:
            from langchain_core.tools import StructuredTool
            from pydantic import BaseModel, Field, create_model
        except ImportError:
            raise ImportError("需要安装 langchain-core: pip install langchain-core")
        
        # 动态创建输入 Schema
        input_model = LangChainToolAdapter._create_input_model(
            definition.tool_id,
            definition.input_schema
        )
        
        # 包装实现函数
        async def wrapped_func(**kwargs):
            try:
                if definition.is_async:
                    if inspect.iscoroutinefunction(implementation):
                        return await implementation(**kwargs)
                    else:
                        return await asyncio.to_thread(implementation, **kwargs)
                else:
                    if inspect.iscoroutinefunction(implementation):
                        return await implementation(**kwargs)
                    else:
                        return implementation(**kwargs)
            except Exception as e:
                logger.error(f"工具 {definition.tool_id} 执行失败: {e}")
                raise
        
        return StructuredTool(
            name=definition.tool_id,
            description=definition.description,
            args_schema=input_model,
            func=wrapped_func if not definition.is_async else None,
            coroutine=wrapped_func if definition.is_async else None
        )
    
    @staticmethod
    def _create_input_model(name: str, schema: Dict[str, Any]) -> type:
        """从 JSON Schema 创建 Pydantic 模型"""
        try:
            from pydantic import create_model, Field
            from typing import Any, Optional
        except ImportError:
            raise ImportError("需要安装 pydantic")
        
        fields = {}
        properties = schema.get("properties", {})
        required = schema.get("required", [])
        
        type_mapping = {
            "string": str,
            "integer": int,
            "number": float,
            "boolean": bool,
            "array": list,
            "object": dict
        }
        
        for field_name, field_def in properties.items():
            field_type = type_mapping.get(field_def.get("type"), Any)
            is_required = field_name in required
            field_description = field_def.get("description", "")
            
            if is_required:
                fields[field_name] = (
                    field_type,
                    Field(description=field_description)
                )
            else:
                fields[field_name] = (
                    Optional[field_type],
                    Field(default=None, description=field_description)
                )
        
        return create_model(f"{name}Input", **fields)


# 扩展 ToolRegistry
class EnhancedToolRegistry:
    """增强的工具注册表，支持 LangChain"""
    
    def __init__(self, base_registry):
        """
        Args:
            base_registry: ToolRegistry 实例
        """
        self.base_registry = base_registry
    
    def get_langchain_tool(self, tool_id: str):
        """
        获取 LangChain 格式的工具
        
        Args:
            tool_id: 工具 ID
        
        Returns:
            LangChain StructuredTool，如果不存在则返回 None
        """
        definition = self.base_registry.get(tool_id)
        implementation = self.base_registry._tool_impls.get(tool_id)
        
        if definition and implementation:
            try:
                return LangChainToolAdapter.adapt(definition, implementation)
            except Exception as e:
                logger.error(f"适配工具 {tool_id} 为 LangChain Tool 失败: {e}")
                return None
        
        return None
    
    def get_all_langchain_tools(self) -> list:
        """
        获取所有 LangChain 工具
        
        Returns:
            LangChain StructuredTool 列表
        """
        tools = []
        for tool_id in self.base_registry._tools:
            tool = self.get_langchain_tool(tool_id)
            if tool:
                tools.append(tool)
        return tools

