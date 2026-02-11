"""
Redis 缓存客户端

提供 Redis 缓存功能，支持：
- 通用键值缓存（异步 + 同步）
- LLM 响应缓存
- 分布式锁
- 会话存储
- LangGraph 检查点兼容（同步 API）
"""

import json
import hashlib
from typing import Any, Optional, Dict, List, Union, Iterator
from datetime import timedelta
from functools import wraps
import asyncio

from src.utils.logger import get_logger

logger = get_logger()

# 可选依赖：redis
try:
    import redis.asyncio as aioredis
    from redis.asyncio import Redis
    import redis as sync_redis

    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False
    aioredis = None
    Redis = None
    sync_redis = None
    logger.debug("redis 未安装，Redis 功能不可用。请运行: pip install redis")


class RedisClient:
    """
    Redis 客户端

    提供异步 Redis 操作接口。

    使用示例:
    ```python
    client = RedisClient(host="localhost", port=6379)
    await client.connect()

    # 基本操作
    await client.set("key", "value", ttl=3600)
    value = await client.get("key")

    # 关闭
    await client.close()
    ```
    """

    def __init__(
        self,
        host: str = "localhost",
        port: int = 6379,
        db: int = 0,
        password: Optional[str] = None,
        max_connections: int = 10,
        decode_responses: bool = True,
        ssl: bool = False,
        url: Optional[str] = None,
    ):
        """
        初始化 Redis 客户端

        Args:
            host: Redis 主机
            port: Redis 端口
            db: 数据库编号
            password: 密码
            max_connections: 最大连接数
            decode_responses: 是否解码响应
            ssl: 是否使用 SSL
            url: Redis URL（优先于其他参数）
        """
        if not REDIS_AVAILABLE:
            raise ImportError("redis 未安装。请运行: pip install redis")

        self.host = host
        self.port = port
        self.db = db
        self.password = password
        self.max_connections = max_connections
        self.decode_responses = decode_responses
        self.ssl = ssl
        self.url = url

        self._redis: Optional[Redis] = None
        self._connected = False

    async def connect(self) -> None:
        """建立 Redis 连接"""
        if self._connected:
            return

        try:
            if self.url:
                self._redis = aioredis.from_url(
                    self.url,
                    max_connections=self.max_connections,
                    decode_responses=self.decode_responses,
                )
            else:
                self._redis = aioredis.Redis(
                    host=self.host,
                    port=self.port,
                    db=self.db,
                    password=self.password,
                    max_connections=self.max_connections,
                    decode_responses=self.decode_responses,
                    ssl=self.ssl,
                )

            # 测试连接
            await self._redis.ping()
            self._connected = True
            logger.info(f"Redis 连接成功: {self.host}:{self.port}/{self.db}")

        except Exception as e:
            logger.error(f"Redis 连接失败: {e}")
            raise

    async def close(self) -> None:
        """关闭 Redis 连接"""
        if self._redis:
            await self._redis.close()
            self._redis = None
            self._connected = False
        if self._sync_client:
            self._sync_client.close()
            self._sync_client = None
        logger.info("Redis 连接已关闭")

    async def __aenter__(self):
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()

    def _ensure_connected(self):
        """确保已连接"""
        if not self._connected or not self._redis:
            raise RuntimeError("Redis 未连接。请先调用 connect()")

    # ==================== 基本操作 ====================

    async def get(self, key: str) -> Optional[str]:
        """获取值"""
        self._ensure_connected()
        return await self._redis.get(key)

    async def set(
        self,
        key: str,
        value: str,
        ttl: Optional[int] = None,
        nx: bool = False,
        xx: bool = False,
    ) -> bool:
        """
        设置值

        Args:
            key: 键
            value: 值
            ttl: 过期时间（秒）
            nx: 仅当键不存在时设置
            xx: 仅当键存在时设置

        Returns:
            是否设置成功
        """
        self._ensure_connected()
        return await self._redis.set(key, value, ex=ttl, nx=nx, xx=xx)

    async def delete(self, *keys: str) -> int:
        """删除键"""
        self._ensure_connected()
        return await self._redis.delete(*keys)

    async def exists(self, *keys: str) -> int:
        """检查键是否存在"""
        self._ensure_connected()
        return await self._redis.exists(*keys)

    async def expire(self, key: str, ttl: int) -> bool:
        """设置过期时间"""
        self._ensure_connected()
        return await self._redis.expire(key, ttl)

    async def ttl(self, key: str) -> int:
        """获取剩余过期时间"""
        self._ensure_connected()
        return await self._redis.ttl(key)

    # ==================== JSON 操作 ====================

    async def get_json(self, key: str) -> Optional[Any]:
        """获取 JSON 值"""
        value = await self.get(key)
        if value:
            try:
                return json.loads(value)
            except json.JSONDecodeError:
                return value
        return None

    async def set_json(
        self,
        key: str,
        value: Any,
        ttl: Optional[int] = None,
    ) -> bool:
        """设置 JSON 值"""
        json_str = json.dumps(value, ensure_ascii=False, default=str)
        return await self.set(key, json_str, ttl=ttl)

    # ==================== Hash 操作 ====================

    async def hget(self, name: str, key: str) -> Optional[str]:
        """获取 Hash 字段"""
        self._ensure_connected()
        return await self._redis.hget(name, key)

    async def hset(self, name: str, key: str, value: str) -> int:
        """设置 Hash 字段"""
        self._ensure_connected()
        return await self._redis.hset(name, key, value)

    async def hgetall(self, name: str) -> Dict[str, str]:
        """获取所有 Hash 字段"""
        self._ensure_connected()
        return await self._redis.hgetall(name)

    async def hdel(self, name: str, *keys: str) -> int:
        """删除 Hash 字段"""
        self._ensure_connected()
        return await self._redis.hdel(name, *keys)

    # ==================== 列表操作 ====================

    async def lpush(self, name: str, *values: str) -> int:
        """从左侧添加"""
        self._ensure_connected()
        return await self._redis.lpush(name, *values)

    async def rpush(self, name: str, *values: str) -> int:
        """从右侧添加"""
        self._ensure_connected()
        return await self._redis.rpush(name, *values)

    async def lrange(self, name: str, start: int, end: int) -> List[str]:
        """获取列表范围"""
        self._ensure_connected()
        return await self._redis.lrange(name, start, end)

    async def ltrim(self, name: str, start: int, end: int) -> bool:
        """修剪列表"""
        self._ensure_connected()
        return await self._redis.ltrim(name, start, end)

    # ==================== 分布式锁 ====================

    async def acquire_lock(
        self,
        lock_name: str,
        timeout: int = 10,
        blocking_timeout: Optional[int] = None,
    ) -> Optional[str]:
        """
        获取分布式锁

        Args:
            lock_name: 锁名称
            timeout: 锁超时时间（秒）
            blocking_timeout: 阻塞等待超时（秒）

        Returns:
            锁标识符（用于释放锁），获取失败返回 None
        """
        import uuid

        self._ensure_connected()
        lock_key = f"lock:{lock_name}"
        lock_value = str(uuid.uuid4())

        if blocking_timeout:
            # 阻塞等待
            end_time = asyncio.get_event_loop().time() + blocking_timeout
            while asyncio.get_event_loop().time() < end_time:
                if await self._redis.set(lock_key, lock_value, ex=timeout, nx=True):
                    return lock_value
                await asyncio.sleep(0.1)
            return None
        else:
            # 非阻塞
            if await self._redis.set(lock_key, lock_value, ex=timeout, nx=True):
                return lock_value
            return None

    async def release_lock(self, lock_name: str, lock_value: str) -> bool:
        """
        释放分布式锁

        Args:
            lock_name: 锁名称
            lock_value: 锁标识符

        Returns:
            是否释放成功
        """
        self._ensure_connected()
        lock_key = f"lock:{lock_name}"

        # 使用 Lua 脚本确保原子操作
        script = """
        if redis.call("get", KEYS[1]) == ARGV[1] then
            return redis.call("del", KEYS[1])
        else
            return 0
        end
        """
        result = await self._redis.eval(script, 1, lock_key, lock_value)
        return bool(result)

    # ==================== 健康检查 ====================

    async def ping(self) -> bool:
        """检查连接健康状态"""
        try:
            self._ensure_connected()
            return await self._redis.ping()
        except Exception:
            return False

    # ==================== 同步 API (用于 LangGraph) ====================

    _sync_client: Optional["sync_redis.Redis"] = None

    def _ensure_sync_client(self) -> "sync_redis.Redis":
        """确保同步客户端已初始化"""
        if self._sync_client is None:
            if not REDIS_AVAILABLE:
                raise ImportError("redis 未安装。请运行: pip install redis")

            if self.url:
                self._sync_client = sync_redis.from_url(
                    self.url,
                    max_connections=self.max_connections,
                    decode_responses=False,  # 同步客户端使用 bytes
                )
            else:
                self._sync_client = sync_redis.Redis(
                    host=self.host,
                    port=self.port,
                    db=self.db,
                    password=self.password,
                    max_connections=self.max_connections,
                    decode_responses=False,
                    ssl=self.ssl,
                )
        return self._sync_client

    @property
    def sync_client(self) -> "sync_redis.Redis":
        """
        获取底层同步 Redis 客户端

        用于需要直接访问同步客户端的场景（如 LangGraph 检查点）。
        """
        return self._ensure_sync_client()

    def get_sync(self, key: str) -> Optional[bytes]:
        """同步获取值"""
        return self._ensure_sync_client().get(key)

    def set_sync(
        self,
        key: str,
        value: Union[str, bytes],
        ttl: Optional[int] = None,
        nx: bool = False,
        xx: bool = False,
    ) -> bool:
        """
        同步设置值

        Args:
            key: 键
            value: 值
            ttl: 过期时间（秒）
            nx: 仅当键不存在时设置
            xx: 仅当键存在时设置

        Returns:
            是否设置成功
        """
        return self._ensure_sync_client().set(key, value, ex=ttl, nx=nx, xx=xx)

    def delete_sync(self, *keys: str) -> int:
        """同步删除键"""
        return self._ensure_sync_client().delete(*keys)

    def exists_sync(self, *keys: str) -> int:
        """同步检查键是否存在"""
        return self._ensure_sync_client().exists(*keys)

    def lpush_sync(self, name: str, *values) -> int:
        """同步从左侧添加"""
        return self._ensure_sync_client().lpush(name, *values)

    def lrange_sync(self, name: str, start: int, end: int) -> List[bytes]:
        """同步获取列表范围"""
        return self._ensure_sync_client().lrange(name, start, end)

    def ltrim_sync(self, name: str, start: int, end: int) -> bool:
        """同步修剪列表"""
        return self._ensure_sync_client().ltrim(name, start, end)

    def expire_sync(self, key: str, ttl: int) -> bool:
        """同步设置过期时间"""
        return self._ensure_sync_client().expire(key, ttl)

    def scan_iter_sync(self, match: str = "*", count: int = 100) -> Iterator[bytes]:
        """同步扫描键"""
        return self._ensure_sync_client().scan_iter(match=match, count=count)

    def pipeline_sync(self):
        """获取同步 pipeline"""
        return self._ensure_sync_client().pipeline()

    def ping_sync(self) -> bool:
        """同步检查连接健康状态"""
        try:
            return self._ensure_sync_client().ping()
        except Exception:
            return False

    def close_sync(self) -> None:
        """关闭同步连接"""
        if self._sync_client:
            self._sync_client.close()
            self._sync_client = None


class LLMResponseCache:
    """
    LLM 响应缓存

    缓存 LLM API 调用的响应，支持：
    - 基于请求内容的缓存键生成
    - 可配置的过期时间
    - 缓存统计

    使用示例:
    ```python
    cache = LLMResponseCache(redis_client)

    # 尝试获取缓存
    cached = await cache.get(
        model="gpt-4",
        messages=[{"role": "user", "content": "Hello"}],
        temperature=0.7,
    )

    if cached:
        return cached

    # 调用 LLM
    response = await llm_client.call(...)

    # 保存缓存
    await cache.set(
        model="gpt-4",
        messages=[{"role": "user", "content": "Hello"}],
        temperature=0.7,
        response=response,
    )
    ```
    """

    def __init__(
        self,
        redis_client: RedisClient,
        prefix: str = "llm_cache",
        default_ttl: int = 3600,  # 1 小时
        enabled: bool = True,
    ):
        """
        初始化 LLM 响应缓存

        Args:
            redis_client: Redis 客户端
            prefix: 缓存键前缀
            default_ttl: 默认过期时间（秒）
            enabled: 是否启用缓存
        """
        self.redis = redis_client
        self.prefix = prefix
        self.default_ttl = default_ttl
        self.enabled = enabled

        # 统计
        self._hits = 0
        self._misses = 0

    def _generate_cache_key(
        self,
        model: str,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        **kwargs,
    ) -> str:
        """生成缓存键"""
        # 构建用于哈希的内容
        cache_content = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
        }

        if max_tokens:
            cache_content["max_tokens"] = max_tokens

        # 添加其他影响输出的参数
        for key in ["top_p", "presence_penalty", "frequency_penalty"]:
            if key in kwargs:
                cache_content[key] = kwargs[key]

        # 生成哈希
        content_str = json.dumps(cache_content, sort_keys=True, ensure_ascii=False)
        hash_value = hashlib.sha256(content_str.encode()).hexdigest()[:16]

        return f"{self.prefix}:{model}:{hash_value}"

    async def get(
        self,
        model: str,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        **kwargs,
    ) -> Optional[Dict[str, Any]]:
        """
        获取缓存的响应

        Args:
            model: 模型名称
            messages: 消息列表
            temperature: 温度参数
            **kwargs: 其他参数

        Returns:
            缓存的响应，未命中返回 None
        """
        if not self.enabled:
            return None

        # 高温度不缓存（结果随机性高）
        if temperature > 0.5:
            return None

        cache_key = self._generate_cache_key(
            model=model,
            messages=messages,
            temperature=temperature,
            **kwargs,
        )

        try:
            cached = await self.redis.get_json(cache_key)
            if cached:
                self._hits += 1
                logger.debug(f"LLM 缓存命中: {cache_key}")
                return cached
            else:
                self._misses += 1
                return None
        except Exception as e:
            logger.warning(f"获取 LLM 缓存失败: {e}")
            self._misses += 1
            return None

    async def set(
        self,
        model: str,
        messages: List[Dict[str, str]],
        response: Dict[str, Any],
        temperature: float = 0.7,
        ttl: Optional[int] = None,
        **kwargs,
    ) -> bool:
        """
        设置缓存响应

        Args:
            model: 模型名称
            messages: 消息列表
            response: LLM 响应
            temperature: 温度参数
            ttl: 过期时间（秒）
            **kwargs: 其他参数

        Returns:
            是否设置成功
        """
        if not self.enabled:
            return False

        # 高温度不缓存
        if temperature > 0.5:
            return False

        cache_key = self._generate_cache_key(
            model=model,
            messages=messages,
            temperature=temperature,
            **kwargs,
        )

        try:
            await self.redis.set_json(
                cache_key,
                response,
                ttl=ttl or self.default_ttl,
            )
            logger.debug(f"LLM 响应已缓存: {cache_key}")
            return True
        except Exception as e:
            logger.warning(f"设置 LLM 缓存失败: {e}")
            return False

    async def invalidate(
        self,
        model: str,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        **kwargs,
    ) -> bool:
        """使缓存失效"""
        cache_key = self._generate_cache_key(
            model=model,
            messages=messages,
            temperature=temperature,
            **kwargs,
        )

        try:
            await self.redis.delete(cache_key)
            return True
        except Exception:
            return False

    def get_stats(self) -> Dict[str, Any]:
        """获取缓存统计"""
        total = self._hits + self._misses
        hit_rate = self._hits / total if total > 0 else 0

        return {
            "hits": self._hits,
            "misses": self._misses,
            "total": total,
            "hit_rate": hit_rate,
            "enabled": self.enabled,
        }

    def reset_stats(self) -> None:
        """重置统计"""
        self._hits = 0
        self._misses = 0


def cache_llm_response(
    cache: LLMResponseCache,
    ttl: Optional[int] = None,
):
    """
    LLM 响应缓存装饰器

    使用示例:
    ```python
    @cache_llm_response(cache, ttl=3600)
    async def call_llm(model: str, messages: List[Dict], **kwargs):
        return await llm_client.call(model, messages, **kwargs)
    ```
    """

    def decorator(func):
        @wraps(func)
        async def wrapper(model: str, messages: List[Dict], **kwargs):
            # 尝试获取缓存
            temperature = kwargs.get("temperature", 0.7)
            cached = await cache.get(
                model=model,
                messages=messages,
                temperature=temperature,
                **kwargs,
            )

            if cached:
                return cached

            # 调用原函数
            response = await func(model, messages, **kwargs)

            # 保存缓存
            await cache.set(
                model=model,
                messages=messages,
                response=response,
                temperature=temperature,
                ttl=ttl,
                **kwargs,
            )

            return response

        return wrapper

    return decorator


# 全局实例
_redis_client: Optional[RedisClient] = None
_llm_cache: Optional[LLMResponseCache] = None


async def get_redis_client(
    host: str = "localhost",
    port: int = 6379,
    db: int = 0,
    password: Optional[str] = None,
) -> RedisClient:
    """获取全局 Redis 客户端"""
    global _redis_client
    if _redis_client is None:
        _redis_client = RedisClient(
            host=host,
            port=port,
            db=db,
            password=password,
        )
        await _redis_client.connect()
    return _redis_client


async def get_llm_cache(
    redis_client: Optional[RedisClient] = None,
    default_ttl: int = 3600,
) -> LLMResponseCache:
    """获取全局 LLM 缓存"""
    global _llm_cache, _redis_client

    if _llm_cache is None:
        if redis_client:
            client = redis_client
        elif _redis_client:
            client = _redis_client
        else:
            client = await get_redis_client()

        _llm_cache = LLMResponseCache(
            redis_client=client,
            default_ttl=default_ttl,
        )

    return _llm_cache


# 导出
__all__ = [
    "RedisClient",
    "LLMResponseCache",
    "cache_llm_response",
    "get_redis_client",
    "get_llm_cache",
    "REDIS_AVAILABLE",
]
