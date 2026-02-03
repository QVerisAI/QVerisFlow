"""
验证相关接口定义
"""

from abc import ABC, abstractmethod
from typing import Protocol, Dict, Any, Optional, List, runtime_checkable


@runtime_checkable
class IVerificationResult(Protocol):
    """
    验证结果接口
    """

    @property
    def passed(self) -> bool:
        """是否通过验证"""
        ...

    @property
    def score(self) -> float:
        """验证分数 (0.0 - 1.0)"""
        ...

    @property
    def feedback(self) -> str:
        """验证反馈"""
        ...

    @property
    def details(self) -> Optional[Dict[str, Any]]:
        """详细信息"""
        ...


class IVerifier(ABC):
    """
    验证器抽象接口

    所有验证器必须实现此接口
    """

    @abstractmethod
    async def verify(
        self, output: Any, context: Optional[Dict[str, Any]] = None
    ) -> IVerificationResult:
        """
        验证输出

        Args:
            output: 待验证的输出
            context: 验证上下文

        Returns:
            验证结果
        """
        ...

    @property
    @abstractmethod
    def name(self) -> str:
        """验证器名称"""
        ...


@runtime_checkable
class IValidationRule(Protocol):
    """
    验证规则接口
    """

    @property
    def name(self) -> str:
        """规则名称"""
        ...

    @property
    def weight(self) -> float:
        """规则权重"""
        ...

    def validate(
        self, output: Any, context: Optional[Dict[str, Any]] = None
    ) -> IVerificationResult:
        """
        执行验证

        Args:
            output: 待验证的输出
            context: 验证上下文

        Returns:
            验证结果
        """
        ...


class ICompositeVerifier(IVerifier):
    """
    组合验证器接口

    支持组合多个验证器
    """

    @abstractmethod
    def add_verifier(self, verifier: IVerifier, weight: float = 1.0) -> None:
        """
        添加子验证器

        Args:
            verifier: 子验证器
            weight: 权重
        """
        ...

    @abstractmethod
    def remove_verifier(self, name: str) -> bool:
        """
        移除子验证器

        Args:
            name: 验证器名称

        Returns:
            是否成功移除
        """
        ...
