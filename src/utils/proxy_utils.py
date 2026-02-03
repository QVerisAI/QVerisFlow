"""
代理配置工具

检测 .env.proxy 文件并配置 HTTP 代理
"""

import os
from pathlib import Path
from typing import Dict, Optional
import httpx

from src.utils.logger import get_logger

logger = get_logger()


def _find_proxy_config_file() -> Optional[Path]:
    """
    查找 .env.proxy 文件

    从当前目录向上查找项目根目录的 .env.proxy 文件
    同时检查常见的项目目录位置

    Returns:
        .env.proxy 文件路径，如果不存在则返回 None
    """
    # 1. 从当前工作目录开始向上查找
    current = Path.cwd()

    # 最多向上查找 5 层
    for _ in range(5):
        proxy_file = current / ".env.proxy"
        if proxy_file.exists():
            logger.info(f"找到代理配置文件: {proxy_file}")
            return proxy_file

        # 到达根目录
        if current.parent == current:
            break

        current = current.parent

    # 2. 检查常见的项目目录位置（如果从工作目录向上查找失败）
    common_locations = [
        Path("/data/etf-platform/.env.proxy"),  # 服务器项目根目录
        Path("/data/etf-event-analysis/.env.proxy"),  # 服务器运行目录
        Path.home() / ".env.proxy",  # 用户主目录
    ]

    for location in common_locations:
        if location.exists():
            logger.debug(f"在常见位置找到代理配置: {location}")
            return location

    return None


def _parse_proxy_config(proxy_file: Path) -> Dict[str, str]:
    """
    解析 .env.proxy 文件

    Args:
        proxy_file: .env.proxy 文件路径

    Returns:
        代理配置字典
    """
    config = {}

    try:
        with open(proxy_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()

                # 跳过注释和空行
                if not line or line.startswith("#"):
                    continue

                # 解析 key=value
                if "=" in line:
                    key, value = line.split("=", 1)
                    key = key.strip()
                    value = value.strip()

                    # 只保留小写的代理配置（大写版本是为了某些工具）
                    if key in ["http_proxy", "https_proxy", "no_proxy"]:
                        config[key] = value

        return config

    except Exception as e:
        logger.warning(f"解析 .env.proxy 文件失败: {e}")
        return {}


def get_proxy_config() -> Optional[Dict[str, str]]:
    """
    获取代理配置

    Returns:
        代理配置字典，如果没有配置则返回 None
        格式: {"http://": "http://127.0.0.1:7890", "https://": "http://127.0.0.1:7890"}
    """
    # 1. 查找 .env.proxy 文件
    proxy_file = _find_proxy_config_file()

    if not proxy_file:
        logger.debug("未找到 .env.proxy 文件，不使用代理")
        return None

    logger.info(f"📡 检测到代理配置文件: {proxy_file}")

    # 2. 解析代理配置
    config = _parse_proxy_config(proxy_file)

    if not config:
        logger.warning("代理配置文件为空或解析失败")
        return None

    # 3. 转换为 httpx 格式
    proxies = {}

    if "http_proxy" in config:
        proxies["http://"] = config["http_proxy"]
        logger.info(f"  HTTP 代理: {config['http_proxy']}")

    if "https_proxy" in config:
        proxies["https://"] = config["https_proxy"]
        logger.info(f"  HTTPS 代理: {config['https_proxy']}")

    if not proxies:
        logger.warning("代理配置文件中未找到 http_proxy 或 https_proxy")
        return None

    return proxies


def create_http_client_with_proxy(async_client: bool = False):
    """
    创建配置了代理的 HTTP 客户端

    Args:
        async_client: 是否创建异步客户端，默认为 False（同步客户端）

    Returns:
        配置了代理的 httpx.Client 或 httpx.AsyncClient，如果没有代理配置则返回 None
    """
    proxies = get_proxy_config()

    if not proxies:
        return None

    try:
        # httpx 使用 mounts 参数配置代理
        # 格式: mounts={"http://": httpx.HTTPTransport(proxy=...), "https://": ...}
        if async_client:
            from httpx import AsyncHTTPTransport, AsyncClient

            mounts = {}
            if "http://" in proxies:
                mounts["http://"] = AsyncHTTPTransport(proxy=proxies["http://"])
            if "https://" in proxies:
                mounts["https://"] = AsyncHTTPTransport(proxy=proxies["https://"])

            # 创建配置了代理的异步 HTTP 客户端
            client = AsyncClient(
                mounts=mounts,
                timeout=120.0,
                follow_redirects=True,
            )
            logger.info("✅ 已创建配置了代理的异步 HTTP 客户端")
        else:
            from httpx import HTTPTransport, Client

            mounts = {}
            if "http://" in proxies:
                mounts["http://"] = HTTPTransport(proxy=proxies["http://"])
            if "https://" in proxies:
                mounts["https://"] = HTTPTransport(proxy=proxies["https://"])

            # 创建配置了代理的同步 HTTP 客户端
            client = Client(
                mounts=mounts,
                timeout=120.0,
                follow_redirects=True,
            )
            logger.info("✅ 已创建配置了代理的同步 HTTP 客户端")

        return client

    except Exception as e:
        logger.error(f"创建代理 HTTP 客户端失败: {e}")
        return None


def should_use_proxy() -> bool:
    """
    检查是否应该使用代理

    Returns:
        如果存在 .env.proxy 文件则返回 True
    """
    return _find_proxy_config_file() is not None
