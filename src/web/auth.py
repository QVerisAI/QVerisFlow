"""
用户认证模块

提供基于 JWT 的用户登录认证功能。
当前使用硬编码账号，后续可扩展为数据库存储。
"""

import os
from datetime import datetime, timedelta, timezone
from typing import Optional

import bcrypt
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

from src.utils.logger import get_logger

logger = get_logger()

# ======================== 配置 ========================

# JWT 签名密钥（从环境变量读取，提供默认值用于开发）
SECRET_KEY = os.getenv("AUTH_SECRET_KEY", "qveris-flow-dev-secret-key-change-in-production")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_HOURS = 24 * 7  # Token 有效期 7 天

# HTTP Bearer 认证方案
security = HTTPBearer(auto_error=False)


# ======================== 密码工具 ========================


def _hash_password(plain_password: str) -> str:
    """使用 bcrypt 哈希密码"""
    return bcrypt.hashpw(plain_password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def _verify_password(plain_password: str, hashed_password: str) -> bool:
    """验证密码"""
    return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))


# ======================== 硬编码用户 ========================

# 预先生成哈希（模块加载时执行一次）
_ADMIN_HASH = _hash_password("admin123")
_USER_HASH = _hash_password("user123")

# 用户字典：username -> {hashed_password, display_name, role}
USERS = {
    "admin": {
        "hashed_password": _ADMIN_HASH,
        "display_name": "管理员",
        "role": "admin",
    },
    "user1": {
        "hashed_password": _USER_HASH,
        "display_name": "用户一",
        "role": "user",
    },
    "user2": {
        "hashed_password": _USER_HASH,
        "display_name": "用户二",
        "role": "user",
    },
}


# ======================== 数据模型 ========================


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    username: str
    display_name: str
    role: str


class UserInfo(BaseModel):
    username: str
    display_name: str
    role: str


# ======================== 核心函数 ========================


def authenticate_user(username: str, password: str) -> Optional[dict]:
    """
    验证用户凭据。
    返回用户信息字典（不含密码），验证失败返回 None。
    """
    user = USERS.get(username)
    if not user:
        return None
    if not _verify_password(password, user["hashed_password"]):
        return None
    return {
        "username": username,
        "display_name": user["display_name"],
        "role": user["role"],
    }


def create_access_token(username: str, expires_delta: Optional[timedelta] = None) -> str:
    """
    创建 JWT access token。
    """
    if expires_delta is None:
        expires_delta = timedelta(hours=ACCESS_TOKEN_EXPIRE_HOURS)

    now = datetime.now(timezone.utc)
    expire = now + expires_delta

    payload = {
        "sub": username,
        "exp": expire,
        "iat": now,
    }
    token = jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)
    return token


def verify_token(token: str) -> Optional[UserInfo]:
    """
    验证 JWT token。
    返回 UserInfo，验证失败返回 None。
    """
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            return None
        user = USERS.get(username)
        if user is None:
            return None
        return UserInfo(
            username=username,
            display_name=user["display_name"],
            role=user["role"],
        )
    except jwt.ExpiredSignatureError:
        logger.debug("Token 已过期")
        return None
    except jwt.InvalidTokenError as e:
        logger.debug(f"Token 无效: {e}")
        return None


# ======================== FastAPI 依赖 ========================


async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> UserInfo:
    """
    FastAPI 依赖项：从 Authorization 头中提取并验证 JWT token。
    用于保护 REST API 路由。
    """
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="未提供认证凭据",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user = verify_token(credentials.credentials)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="认证凭据无效或已过期",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return user
