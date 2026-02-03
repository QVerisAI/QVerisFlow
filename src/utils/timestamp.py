"""
统一的时间戳工具模块

提供统一的时间戳生成函数，确保整个项目使用一致的 UTC 时间戳。

问题背景：
- 项目中混用了多种时间戳生成方式：
  * datetime.utcnow() (已弃用，naive datetime)
  * datetime.now(timezone.utc) (aware datetime)
  * datetime.now(timezone.utc).replace(tzinfo=None) (UTC但移除时区)
  * datetime.now() (本地时间，无时区)

- 数据库字段类型不统一：
  * 部分表使用 DateTime(timezone=True) - 需要 aware datetime
  * 部分表使用 DateTime(timezone=False) - 需要 naive datetime

统一策略：
1. 所有时间戳统一使用 UTC 时间
2. 根据数据库字段类型自动处理时区信息
3. 提供明确的函数名区分不同用途
"""

from datetime import datetime, timezone
from typing import Optional


def utc_now_naive() -> datetime:
    """
    获取当前 UTC 时间（naive datetime，无时区信息）
    
    用于存储到 DateTime(timezone=False) 类型的数据库字段。
    例如：Provider, Tool, User 等表的 created_at/updated_at 字段。
    
    Returns:
        datetime: 当前 UTC 时间，无时区信息
        
    Example:
        >>> timestamp = utc_now_naive()
        >>> provider.created_at = timestamp
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)


def utc_now_aware() -> datetime:
    """
    获取当前 UTC 时间（aware datetime，带时区信息）
    
    用于存储到 DateTime(timezone=True) 类型的数据库字段。
    例如：CrawledPage, Frontier, ExtractedContent 等表的 created_at/updated_at 字段。
    
    Returns:
        datetime: 当前 UTC 时间，带时区信息
        
    Example:
        >>> timestamp = utc_now_aware()
        >>> crawled_page.crawled_at = timestamp
    """
    return datetime.now(timezone.utc)


def utc_now_iso() -> str:
    """
    获取当前 UTC 时间的 ISO 格式字符串
    
    用于序列化为 JSON 或存储为字符串格式。
    
    Returns:
        str: ISO 格式的时间字符串，例如 "2025-01-01T12:00:00+00:00"
        
    Example:
        >>> timestamp_str = utc_now_iso()
        >>> data['updated_at'] = timestamp_str
    """
    return datetime.now(timezone.utc).isoformat()


def to_utc_naive(dt: datetime) -> datetime:
    """
    将 datetime 对象转换为 UTC naive datetime
    
    如果输入是 aware datetime，转换为 UTC 后移除时区信息。
    如果输入是 naive datetime，假设已经是 UTC 时间。
    
    Args:
        dt: 输入的 datetime 对象（可以是 aware 或 naive）
        
    Returns:
        datetime: UTC naive datetime
        
    Example:
        >>> dt = datetime.now(timezone.utc)
        >>> naive = to_utc_naive(dt)
    """
    if dt.tzinfo is not None:
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def to_utc_aware(dt: datetime) -> datetime:
    """
    将 datetime 对象转换为 UTC aware datetime
    
    如果输入是 naive datetime，假设是 UTC 时间并添加时区信息。
    如果输入是 aware datetime，转换为 UTC。
    
    Args:
        dt: 输入的 datetime 对象（可以是 aware 或 naive）
        
    Returns:
        datetime: UTC aware datetime
        
    Example:
        >>> dt = datetime.now()
        >>> aware = to_utc_aware(dt)
    """
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# 向后兼容的别名（推荐使用上面的明确函数名）
utc_now = utc_now_naive  # 默认使用 naive，因为大部分表使用 timezone=False


__all__ = [
    'utc_now_naive',
    'utc_now_aware', 
    'utc_now_iso',
    'to_utc_naive',
    'to_utc_aware',
    'utc_now',  # 向后兼容
]

