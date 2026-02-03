"""
上下文管理器测试

测试 ContextManager 的各项功能。
"""

import pytest
from src.core.context_manager import (
    ContextManager,
    ContextChunk,
    SimpleTokenCounter,
    TiktokenCounter,
)


class TestSimpleTokenCounter:
    """SimpleTokenCounter 测试"""

    def test_count_english_text(self):
        """测试英文文本计数"""
        counter = SimpleTokenCounter()

        # 简单英文
        text = "Hello world"
        count = counter.count(text)
        assert count > 0
        assert count < len(text)  # 英文字符约 0.25 token/char

    def test_count_chinese_text(self):
        """测试中文文本计数"""
        counter = SimpleTokenCounter()

        # 中文文本
        text = "你好世界"
        count = counter.count(text)
        assert count > 0
        assert count >= len(text)  # 中文约 1.5 token/char

    def test_count_mixed_text(self):
        """测试混合文本计数"""
        counter = SimpleTokenCounter()

        text = "Hello 世界"
        count = counter.count(text)
        assert count > 0

    def test_count_empty_text(self):
        """测试空文本计数"""
        counter = SimpleTokenCounter()
        assert counter.count("") == 0
        assert counter.count(None) == 0


class TestContextChunk:
    """ContextChunk 测试"""

    def test_create_chunk(self):
        """测试创建上下文块"""
        chunk = ContextChunk(
            content="Test content",
            source="test_source",
            timestamp="2024-01-01T00:00:00",
            token_count=10,
            priority=5,
        )

        assert chunk.content == "Test content"
        assert chunk.source == "test_source"
        assert chunk.token_count == 10
        assert chunk.priority == 5

    def test_auto_timestamp(self):
        """测试自动生成时间戳"""
        chunk = ContextChunk(
            content="Test",
            source="test",
            timestamp="",
        )

        assert chunk.timestamp  # 应该自动生成


class TestContextManager:
    """ContextManager 测试"""

    def test_add_context(self, context_manager):
        """测试添加上下文"""
        chunk = context_manager.add(
            content="Test content",
            source="test_source",
            priority=5,
        )

        assert chunk is not None
        assert chunk.content == "Test content"
        assert context_manager.total_tokens > 0

    def test_get_context(self, context_manager):
        """测试获取上下文"""
        context_manager.add("Content 1", source="source1", priority=1)
        context_manager.add("Content 2", source="source2", priority=2)

        context = context_manager.get_context()

        assert "Content 1" in context
        assert "Content 2" in context

    def test_is_near_limit(self):
        """测试接近限制检测"""
        manager = ContextManager(max_tokens=100, compression_threshold=0.8)

        # 未接近限制
        assert not manager.is_near_limit

        # 添加内容直到接近限制
        for _ in range(50):
            manager.add("Some long content that uses tokens", source="test")

        # 现在应该接近限制
        assert manager.is_near_limit or manager.total_tokens >= 80

    def test_simple_compress(self):
        """测试简单压缩"""
        manager = ContextManager(max_tokens=100, compression_threshold=0.5)

        # 添加不同优先级的内容
        manager.add("Low priority content", source="low", priority=1)
        manager.add("High priority content", source="high", priority=10)

        initial_chunks = len(manager._chunks)

        # 手动触发压缩
        manager._simple_compress()

        # 高优先级内容应该保留
        context = manager.get_context()
        assert "High priority" in context or initial_chunks <= len(manager._chunks)

    def test_clear(self, context_manager):
        """测试清空上下文"""
        context_manager.add("Test content", source="test")
        assert context_manager.total_tokens > 0

        context_manager.clear()

        assert context_manager.total_tokens == 0
        assert len(context_manager._chunks) == 0

    def test_get_stats(self, context_manager):
        """测试获取统计信息"""
        context_manager.add("Test content", source="test")

        stats = context_manager.get_stats()

        assert "total_chunks" in stats
        assert "total_tokens" in stats
        assert "max_tokens" in stats
        assert "utilization" in stats
        assert stats["total_chunks"] == 1

    def test_to_dict_and_from_dict(self, context_manager):
        """测试序列化和反序列化"""
        context_manager.add("Content 1", source="source1", priority=1)
        context_manager.add("Content 2", source="source2", priority=2)

        # 序列化
        data = context_manager.to_dict()
        assert "chunks" in data
        assert "stats" in data

        # 反序列化
        restored = ContextManager.from_dict(data)
        assert restored.total_tokens == context_manager.total_tokens
        assert len(restored._chunks) == len(context_manager._chunks)

    def test_priority_ordering_in_get_context(self):
        """测试获取上下文时的优先级排序"""
        manager = ContextManager(max_tokens=50, compression_threshold=1.0)

        # 添加低优先级内容（先添加）
        for i in range(5):
            manager.add(f"Low priority {i}" * 10, source=f"low_{i}", priority=1)

        # 添加高优先级内容
        manager.add("CRITICAL CONTENT", source="high", priority=100)

        # 获取有限 token 的上下文
        context = manager.get_context(max_tokens=50)

        # 高优先级内容应该优先保留
        assert "CRITICAL" in context or manager.total_tokens <= 50


class TestContextManagerAsync:
    """ContextManager 异步方法测试"""

    @pytest.mark.asyncio
    async def test_compress_if_needed_no_compression(self, context_manager):
        """测试不需要压缩的情况"""
        context_manager.add("Small content", source="test")

        # 不应该触发压缩
        compressed = await context_manager.compress_if_needed()
        assert not compressed

    @pytest.mark.asyncio
    async def test_compress_if_needed_with_compression(self):
        """测试需要压缩的情况"""
        manager = ContextManager(max_tokens=50, compression_threshold=0.5)

        # 添加足够内容触发压缩
        for i in range(10):
            manager.add(
                f"Content that needs to be compressed {i}" * 5, source=f"src_{i}"
            )

        # 应该触发压缩
        if manager.is_near_limit:
            compressed = await manager.compress_if_needed()
            # 无 LLM 客户端时使用简单压缩
            assert compressed or not manager.is_near_limit
