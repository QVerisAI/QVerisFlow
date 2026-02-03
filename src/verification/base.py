"""
验证层 - 基础抽象与结果模型

提供验证器的抽象基类和验证结果模型。
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field


class VerificationResult(BaseModel):
    """验证结果"""
    
    passed: bool = Field(description="是否通过验证")
    score: float = Field(description="评分 0-1", ge=0.0, le=1.0)
    feedback: str = Field(description="反馈信息")
    details: Dict[str, Any] = Field(
        default_factory=dict,
        description="详细信息"
    )


class BaseVerifier(ABC):
    """
    验证器抽象基类
    
    定义验证器的标准接口，所有验证器都应继承此类。
    """
    
    @abstractmethod
    async def verify(
        self,
        output: Any,
        context: Optional[Dict[str, Any]] = None
    ) -> VerificationResult:
        """
        验证输出
        
        Args:
            output: 待验证的输出
            context: 验证上下文（可选）
        
        Returns:
            验证结果
        """
        pass

