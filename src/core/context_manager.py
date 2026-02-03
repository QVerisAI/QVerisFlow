"""
上下文管理器

负责管理 Agent 执行过程中的上下文，支持：
- 上下文大小控制
- 智能压缩和摘要
- Token 计数
- 上下文窗口管理
"""

from typing import Dict, Any, Optional, List, Callable
from dataclasses import dataclass, field
from datetime import datetime
from abc import ABC, abstractmethod

from src.utils.logger import get_logger

logger = get_logger()

# 可选依赖：tiktoken
try:
    import tiktoken

    TIKTOKEN_AVAILABLE = True
except ImportError:
    tiktoken = None
    TIKTOKEN_AVAILABLE = False
    logger.debug("tiktoken 未安装，将使用简单 token 计数器")


@dataclass
class ContextChunk:
    """上下文块"""

    content: str
    source: str  # 来源（如工具名、文件路径等）
    timestamp: str
    token_count: int = 0
    priority: int = 0  # 优先级，越高越重要
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now().isoformat()


class TokenCounter(ABC):
    """Token 计数器抽象基类"""

    @abstractmethod
    def count(self, text: str) -> int:
        """计算文本的 token 数量"""
        ...


class SimpleTokenCounter(TokenCounter):
    """
    简单 Token 计数器

    使用字符数 / 4 作为估算（适用于英文）
    中文字符按 1.5 token 计算
    """

    def count(self, text: str) -> int:
        if not text:
            return 0

        chinese_chars = sum(1 for c in text if "\u4e00" <= c <= "\u9fff")
        other_chars = len(text) - chinese_chars

        # 中文约 1.5 token/字符，英文约 0.25 token/字符
        estimated_tokens = int(chinese_chars * 1.5 + other_chars * 0.25)
        return max(1, estimated_tokens)


class TiktokenCounter(TokenCounter):
    """
    使用 tiktoken 的精确 Token 计数器

    需要安装 tiktoken: pip install tiktoken
    """

    def __init__(self, model: str = "gpt-4"):
        self.encoding = None
        self._fallback_counter = None

        if not TIKTOKEN_AVAILABLE:
            logger.warning("tiktoken 未安装，将使用简单计数器")
            return

        try:
            self.encoding = tiktoken.encoding_for_model(model)
        except KeyError:
            logger.warning(f"未知模型 {model}，使用 cl100k_base 编码")
            try:
                self.encoding = tiktoken.get_encoding("cl100k_base")
            except Exception as e:
                logger.warning(f"获取编码失败: {e}，将使用简单计数器")
                self.encoding = None

    def count(self, text: str) -> int:
        if not text:
            return 0

        if self.encoding:
            return len(self.encoding.encode(text))
        else:
            # 回退到简单计数
            if self._fallback_counter is None:
                self._fallback_counter = SimpleTokenCounter()
            return self._fallback_counter.count(text)


class ContextManager:
    """
    上下文管理器

    管理 Agent 执行过程中的上下文，支持：
    - 自动 token 计数
    - 上下文大小限制
    - 智能压缩（保留重要内容）
    - LLM 摘要生成
    """

    def __init__(
        self,
        max_tokens: int = 100000,
        compression_threshold: float = 0.8,
        token_counter: Optional[TokenCounter] = None,
        llm_client: Any = None,
    ):
        """
        初始化上下文管理器

        Args:
            max_tokens: 最大 token 数量
            compression_threshold: 触发压缩的阈值（占 max_tokens 的比例）
            token_counter: Token 计数器
            llm_client: LLM 客户端（用于生成摘要）
        """
        self.max_tokens = max_tokens
        self.compression_threshold = compression_threshold
        self.token_counter = token_counter or SimpleTokenCounter()
        self.llm_client = llm_client

        # 上下文存储
        self._chunks: List[ContextChunk] = []
        self._total_tokens: int = 0
        self._compressed_count: int = 0

    @property
    def total_tokens(self) -> int:
        """当前总 token 数"""
        return self._total_tokens

    @property
    def is_near_limit(self) -> bool:
        """是否接近 token 限制"""
        return self._total_tokens >= self.max_tokens * self.compression_threshold

    def add(
        self,
        content: str,
        source: str = "unknown",
        priority: int = 0,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ContextChunk:
        """
        添加上下文块

        Args:
            content: 内容
            source: 来源
            priority: 优先级
            metadata: 元数据

        Returns:
            创建的上下文块
        """
        token_count = self.token_counter.count(content)

        chunk = ContextChunk(
            content=content,
            source=source,
            timestamp=datetime.now().isoformat(),
            token_count=token_count,
            priority=priority,
            metadata=metadata or {},
        )

        self._chunks.append(chunk)
        self._total_tokens += token_count

        logger.debug(
            f"添加上下文块: source={source}, tokens={token_count}, "
            f"total={self._total_tokens}/{self.max_tokens}"
        )

        return chunk

    def get_context(self, max_tokens: Optional[int] = None) -> str:
        """
        获取当前上下文

        Args:
            max_tokens: 可选的 token 限制

        Returns:
            拼接后的上下文字符串
        """
        if not self._chunks:
            return ""

        limit = max_tokens or self.max_tokens

        if self._total_tokens <= limit:
            # 不需要截断
            return self._format_chunks(self._chunks)

        # 按优先级排序，保留高优先级内容
        sorted_chunks = sorted(
            self._chunks, key=lambda c: (c.priority, c.timestamp), reverse=True
        )

        selected = []
        current_tokens = 0

        for chunk in sorted_chunks:
            if current_tokens + chunk.token_count <= limit:
                selected.append(chunk)
                current_tokens += chunk.token_count

        # 按时间排序输出
        selected.sort(key=lambda c: c.timestamp)

        return self._format_chunks(selected)

    def _format_chunks(self, chunks: List[ContextChunk]) -> str:
        """格式化上下文块"""
        parts = []
        for chunk in chunks:
            header = f"[{chunk.source}]"
            parts.append(f"{header}\n{chunk.content}")

        return "\n\n---\n\n".join(parts)

    async def compress_if_needed(self) -> bool:
        """
        如果需要则压缩上下文

        Returns:
            是否执行了压缩
        """
        if not self.is_near_limit:
            return False

        if not self.llm_client:
            # 无 LLM 客户端，使用简单压缩
            self._simple_compress()
            return True

        # 使用 LLM 生成摘要
        await self._llm_compress()
        return True

    def _simple_compress(self):
        """简单压缩：移除低优先级内容"""
        if len(self._chunks) <= 1:
            return

        # 按优先级排序
        sorted_chunks = sorted(enumerate(self._chunks), key=lambda x: x[1].priority)

        # 移除最低优先级的内容，直到低于阈值
        target_tokens = int(self.max_tokens * self.compression_threshold * 0.6)

        to_remove = []
        for idx, chunk in sorted_chunks:
            if self._total_tokens <= target_tokens:
                break
            to_remove.append(idx)
            self._total_tokens -= chunk.token_count

        # 从后向前移除，避免索引错位
        for idx in sorted(to_remove, reverse=True):
            del self._chunks[idx]

        self._compressed_count += len(to_remove)
        logger.info(
            f"简单压缩完成: 移除 {len(to_remove)} 块, "
            f"剩余 {self._total_tokens} tokens"
        )

    async def _llm_compress(self):
        """使用 LLM 压缩上下文"""
        if not self._chunks:
            return

        # 将所有内容合并
        full_context = self._format_chunks(self._chunks)

        # 构建摘要提示
        summary_prompt = f"""请对以下上下文进行摘要，保留关键信息，压缩到原来的 1/3 左右。

上下文：
{full_context}

要求：
1. 保留所有关键数据和结论
2. 保留重要的引用和来源
3. 删除冗余和重复内容
4. 保持结构清晰

摘要："""

        try:
            # 调用 LLM 生成摘要
            messages = [{"role": "user", "content": summary_prompt}]
            response = await self.llm_client.call(
                messages, max_tokens=self.max_tokens // 3
            )

            summary = (
                response if isinstance(response, str) else response.get("content", "")
            )

            # 替换所有块为摘要
            old_count = len(self._chunks)
            self._chunks = [
                ContextChunk(
                    content=summary,
                    source="compressed_summary",
                    timestamp=datetime.now().isoformat(),
                    token_count=self.token_counter.count(summary),
                    priority=10,  # 高优先级
                    metadata={"compressed_from": old_count},
                )
            ]

            self._total_tokens = self._chunks[0].token_count
            self._compressed_count += old_count

            logger.info(
                f"LLM 压缩完成: {old_count} 块 -> 1 块, " f"{self._total_tokens} tokens"
            )

        except Exception as e:
            logger.error(f"LLM 压缩失败: {e}, 回退到简单压缩")
            self._simple_compress()

    def clear(self):
        """清空上下文"""
        self._chunks = []
        self._total_tokens = 0

    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        return {
            "total_chunks": len(self._chunks),
            "total_tokens": self._total_tokens,
            "max_tokens": self.max_tokens,
            "utilization": (
                self._total_tokens / self.max_tokens if self.max_tokens > 0 else 0
            ),
            "compressed_count": self._compressed_count,
            "is_near_limit": self.is_near_limit,
        }

    def to_dict(self) -> Dict[str, Any]:
        """序列化为字典"""
        return {
            "chunks": [
                {
                    "content": c.content,
                    "source": c.source,
                    "timestamp": c.timestamp,
                    "token_count": c.token_count,
                    "priority": c.priority,
                    "metadata": c.metadata,
                }
                for c in self._chunks
            ],
            "stats": self.get_stats(),
        }

    @classmethod
    def from_dict(
        cls,
        data: Dict[str, Any],
        token_counter: Optional[TokenCounter] = None,
        llm_client: Any = None,
    ) -> "ContextManager":
        """从字典恢复"""
        stats = data.get("stats", {})
        manager = cls(
            max_tokens=stats.get("max_tokens", 100000),
            token_counter=token_counter,
            llm_client=llm_client,
        )

        for chunk_data in data.get("chunks", []):
            chunk = ContextChunk(
                content=chunk_data["content"],
                source=chunk_data["source"],
                timestamp=chunk_data["timestamp"],
                token_count=chunk_data["token_count"],
                priority=chunk_data.get("priority", 0),
                metadata=chunk_data.get("metadata", {}),
            )
            manager._chunks.append(chunk)
            manager._total_tokens += chunk.token_count

        return manager


# 导出
__all__ = [
    "ContextManager",
    "ContextChunk",
    "TokenCounter",
    "SimpleTokenCounter",
    "TiktokenCounter",
]
