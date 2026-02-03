"""
Agent 注册表

负责 Agent 定义的注册、查找和实例化。

重构：消除单例模式，改用工厂函数获取默认实例，支持依赖注入。
"""

from typing import Dict, List, Optional, Type, Any
from pathlib import Path
from ..utils.logger import get_logger
from ..definitions import AgentDefinition, AgentDomainType, AgentExecutionType

logger = get_logger()

# 默认实例（延迟初始化）
_default_registry: Optional["AgentRegistry"] = None


class AgentRegistry:
    """
    Agent 注册表 - 支持多种注册方式

    重构：
    - 消除单例模式，支持创建多个独立实例
    - 使用 get_default() 获取全局默认实例
    - 支持依赖注入和测试
    """

    def __init__(self):
        """初始化 Agent 注册表"""
        self._definitions: Dict[str, AgentDefinition] = {}
        self._implementations: Dict[str, Type] = {}
        self._factory_funcs: Dict[str, Any] = {}

        # 索引
        self._by_domain: Dict[AgentDomainType, List[str]] = {}
        self._by_execution_type: Dict[AgentExecutionType, List[str]] = {}
        self._by_tag: Dict[str, List[str]] = {}

    @classmethod
    def get_default(cls) -> "AgentRegistry":
        """
        获取默认的全局注册表实例

        Returns:
            默认的 AgentRegistry 实例
        """
        global _default_registry
        if _default_registry is None:
            _default_registry = cls()
        return _default_registry

    @classmethod
    def set_default(cls, registry: "AgentRegistry") -> None:
        """
        设置默认的全局注册表实例

        Args:
            registry: 新的默认注册表
        """
        global _default_registry
        _default_registry = registry

    @classmethod
    def reset_default(cls) -> None:
        """重置默认注册表（主要用于测试）"""
        global _default_registry
        _default_registry = None

    # ========== 注册方法 ==========

    def register_definition(self, definition: AgentDefinition) -> None:
        """
        注册 Agent 定义

        Args:
            definition: Agent 定义
        """
        agent_id = definition.agent_id

        if agent_id in self._definitions:
            logger.warning(f"⚠️ Agent {agent_id} 已存在，将被覆盖")

        self._definitions[agent_id] = definition
        self._index_definition(definition)

        logger.info(
            f"✅ 注册 Agent 定义: {agent_id} "
            f"({definition.execution_type.value}, {definition.domain_type.value})"
        )

    def register_implementation(self, agent_id: str, impl_class: Type) -> None:
        """
        注册 Agent 实现类

        Args:
            agent_id: Agent ID
            impl_class: 实现类
        """
        self._implementations[agent_id] = impl_class
        logger.info(f"✅ 注册 Agent 实现: {agent_id} -> {impl_class.__name__}")

    def register_from_yaml(self, yaml_path: str) -> None:
        """
        从 YAML 文件注册 Agent

        Args:
            yaml_path: YAML 文件路径或目录路径
        """
        path = Path(yaml_path)

        if path.is_dir():
            # 注册目录下所有 YAML
            for yaml_file in path.glob("*.yaml"):
                self._load_yaml_definition(yaml_file)
            for yaml_file in path.glob("*.yml"):
                self._load_yaml_definition(yaml_file)
        else:
            self._load_yaml_definition(path)

    def _load_yaml_definition(self, yaml_path: Path) -> None:
        """加载单个 YAML 定义"""
        try:
            definition = AgentDefinition.from_yaml_file(str(yaml_path))
            self.register_definition(definition)
        except Exception as e:
            logger.error(f"加载 YAML 定义失败 {yaml_path}: {e}")

    def _index_definition(self, definition: AgentDefinition) -> None:
        """建立索引"""
        agent_id = definition.agent_id

        # 按领域索引
        domain = definition.domain_type
        if domain not in self._by_domain:
            self._by_domain[domain] = []
        if agent_id not in self._by_domain[domain]:
            self._by_domain[domain].append(agent_id)

        # 按执行类型索引
        exec_type = definition.execution_type
        if exec_type not in self._by_execution_type:
            self._by_execution_type[exec_type] = []
        if agent_id not in self._by_execution_type[exec_type]:
            self._by_execution_type[exec_type].append(agent_id)

        # 按标签索引
        for tag in definition.tags:
            if tag not in self._by_tag:
                self._by_tag[tag] = []
            if agent_id not in self._by_tag[tag]:
                self._by_tag[tag].append(agent_id)

    # ========== 查询方法 ==========

    def get_definition(self, agent_id: str) -> Optional[AgentDefinition]:
        """
        获取 Agent 定义

        Args:
            agent_id: Agent ID

        Returns:
            Agent 定义，如果不存在则返回 None
        """
        return self._definitions.get(agent_id)

    def find_by_domain(self, domain: AgentDomainType) -> List[AgentDefinition]:
        """
        按领域查找

        Args:
            domain: 领域类型

        Returns:
            Agent 定义列表
        """
        agent_ids = self._by_domain.get(domain, [])
        return [self._definitions[aid] for aid in agent_ids]

    def find_by_execution_type(
        self, exec_type: AgentExecutionType
    ) -> List[AgentDefinition]:
        """
        按执行类型查找

        Args:
            exec_type: 执行类型

        Returns:
            Agent 定义列表
        """
        agent_ids = self._by_execution_type.get(exec_type, [])
        return [self._definitions[aid] for aid in agent_ids]

    def find_by_tag(self, tag: str) -> List[AgentDefinition]:
        """
        按标签查找

        Args:
            tag: 标签

        Returns:
            Agent 定义列表
        """
        agent_ids = self._by_tag.get(tag, [])
        return [self._definitions[aid] for aid in agent_ids]

    # ========== 实例化方法 ==========

    def create_agent(self, agent_id: str, **kwargs) -> "BaseAgent":
        """
        创建 Agent 实例

        Args:
            agent_id: Agent ID
            **kwargs: 传递给 Agent 构造函数的参数

        Returns:
            Agent 实例
        """
        from ..core import BaseAgent

        definition = self._definitions.get(agent_id)
        if not definition:
            raise ValueError(f"Agent {agent_id} 未注册")

        impl_class = self._implementations.get(agent_id)

        if impl_class:
            # 使用注册的实现类
            return impl_class(definition=definition, **kwargs)
        else:
            # 使用通用执行器
            return BaseAgent(definition=definition, **kwargs)

    def list_all(self) -> List[Dict[str, Any]]:
        """
        列出所有 Agent 摘要

        Returns:
            Agent 摘要列表
        """
        return [
            {
                "agent_id": d.agent_id,
                "name": d.name,
                "domain": d.domain_type.value,
                "execution_type": d.execution_type.value,
                "tags": d.tags,
                "is_active": d.is_active,
            }
            for d in self._definitions.values()
        ]

    def reset(self):
        """重置此注册表实例"""
        self._definitions = {}
        self._implementations = {}
        self._factory_funcs = {}
        self._by_domain = {}
        self._by_execution_type = {}
        self._by_tag = {}

    def copy(self) -> "AgentRegistry":
        """
        创建此注册表的副本

        Returns:
            新的 AgentRegistry 实例
        """
        new_registry = AgentRegistry()
        new_registry._definitions = self._definitions.copy()
        new_registry._implementations = self._implementations.copy()
        new_registry._factory_funcs = self._factory_funcs.copy()
        new_registry._by_domain = {k: v.copy() for k, v in self._by_domain.items()}
        new_registry._by_execution_type = {
            k: v.copy() for k, v in self._by_execution_type.items()
        }
        new_registry._by_tag = {k: v.copy() for k, v in self._by_tag.items()}
        return new_registry


# 装饰器
def agent(
    agent_id: str,
    name: str,
    domain: AgentDomainType,
    execution_type: AgentExecutionType = AgentExecutionType.EXECUTOR,
    registry: "AgentRegistry" = None,
    **kwargs,
):
    """
    Agent 注册装饰器

    用法：
    ```python
    @agent(
        agent_id="financial_analyst",
        name="金融分析师",
        domain=AgentDomainType.FINANCIAL_ANALYSIS,
        execution_type=AgentExecutionType.REASONING_EXECUTOR
    )
    class FinancialAnalystAgent(BaseAgent):
        ...
    ```

    Args:
        agent_id: Agent 唯一标识
        name: Agent 名称
        domain: Agent 领域类型
        execution_type: 执行类型
        registry: 要注册到的注册表（可选，默认使用全局默认注册表）
        **kwargs: 其他参数
    """

    def decorator(cls):
        # 使用指定的注册表或默认注册表
        target_registry = registry or AgentRegistry.get_default()
        target_registry.register_implementation(agent_id, cls)

        return cls

    return decorator
