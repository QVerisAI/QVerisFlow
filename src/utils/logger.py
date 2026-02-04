#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
日志管理模块

提供统一的日志配置和管理功能，独立于外部依赖。
"""

import logging
import logging.handlers
import os
import sys
from pathlib import Path
from typing import Optional


class LogConfig:
    """日志配置"""

    # 默认格式字符串
    DEFAULT_FORMAT = "%(asctime)s - %(levelname)s - %(name)s - [%(filename)s:%(funcName)s:%(lineno)d] - %(message)s"

    def __init__(self):
        self.level: str = os.getenv("LOG_LEVEL", "INFO")
        self.console_output: bool = os.getenv("LOG_CONSOLE", "true").lower() == "true"
        self.file_output: bool = os.getenv("LOG_FILE", "false").lower() == "true"
        self.file_path: Optional[str] = os.getenv("LOG_FILE_PATH")
        self.max_file_size: int = int(os.getenv("LOG_MAX_SIZE", "10485760"))  # 10MB
        self.backup_count: int = int(os.getenv("LOG_BACKUP_COUNT", "5"))

        # 日志格式：支持 "json" 关键字或自定义格式字符串
        format_value = os.getenv("LOG_FORMAT", "")
        if format_value.lower() == "json":
            self.use_json = True
            self.format = self.DEFAULT_FORMAT  # JSON 模式下也需要基础格式
        elif format_value and "%" in format_value:
            self.use_json = False
            self.format = format_value
        else:
            self.use_json = False
            self.format = self.DEFAULT_FORMAT


class LoggerManager:
    """日志管理器"""

    _instance: Optional["LoggerManager"] = None
    _loggers: dict = {}
    _initialized: bool = False

    def __new__(cls) -> "LoggerManager":
        """单例模式"""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        """初始化日志管理器"""
        if not LoggerManager._initialized:
            self.config = LogConfig()
            LoggerManager._initialized = True
            self._setup_root_logger()

    def _get_log_dir(self) -> Path:
        """获取日志目录"""
        log_dir = Path(os.getenv("LOG_DIR", "./logs"))
        try:
            log_dir.mkdir(parents=True, exist_ok=True)
            return log_dir
        except Exception:
            fallback = Path("./logs")
            fallback.mkdir(parents=True, exist_ok=True)
            return fallback

    def _setup_root_logger(self) -> None:
        """设置根日志器"""
        root_logger = logging.getLogger()
        root_logger.setLevel(getattr(logging, self.config.level.upper(), logging.INFO))

        # 清除现有处理器
        root_logger.handlers.clear()

        # 创建格式化器
        if getattr(self.config, "use_json", False):
            formatter = self._create_json_formatter()
        else:
            formatter = logging.Formatter(self.config.format)

        # 控制台处理器
        if self.config.console_output:
            console_handler = logging.StreamHandler(sys.stdout)
            console_handler.setFormatter(formatter)
            root_logger.addHandler(console_handler)

        # 文件处理器
        if self.config.file_output and self.config.file_path:
            self._setup_file_handler(root_logger, formatter)

    def _create_json_formatter(self) -> logging.Formatter:
        """创建 JSON 格式化器"""
        import json as json_module

        class JsonFormatter(logging.Formatter):
            def format(self, record):
                log_obj = {
                    "timestamp": self.formatTime(record),
                    "level": record.levelname,
                    "name": record.name,
                    "message": record.getMessage(),
                    "filename": record.filename,
                    "funcName": record.funcName,
                    "lineno": record.lineno,
                }
                if record.exc_info:
                    log_obj["exc_info"] = self.formatException(record.exc_info)
                return json_module.dumps(log_obj, ensure_ascii=False)

        return JsonFormatter()

    def _setup_file_handler(
        self, logger: logging.Logger, formatter: logging.Formatter
    ) -> None:
        """设置文件处理器"""
        try:
            log_file = Path(self.config.file_path)
            log_file.parent.mkdir(parents=True, exist_ok=True)

            file_handler = logging.handlers.RotatingFileHandler(
                log_file,
                maxBytes=self.config.max_file_size,
                backupCount=self.config.backup_count,
                encoding="utf-8",
            )
            file_handler.setFormatter(formatter)
            logger.addHandler(file_handler)

        except Exception as e:
            print(f"⚠️  文件日志设置失败: {e}")

    def get_logger(self, name: str) -> logging.Logger:
        """获取指定名称的日志器"""
        if name not in self._loggers:
            logger = logging.getLogger(name)
            self._loggers[name] = logger
        return self._loggers[name]

    def set_level(self, level: str) -> None:
        """设置日志级别"""
        self.config.level = level
        logging.getLogger().setLevel(getattr(logging, level.upper(), logging.INFO))

    @classmethod
    def reset(cls) -> None:
        """重置日志管理器（用于测试）"""
        cls._instance = None
        cls._loggers = {}
        cls._initialized = False


# 全局日志管理器实例
_logger_manager: Optional[LoggerManager] = None


def _get_manager() -> LoggerManager:
    """获取日志管理器实例"""
    global _logger_manager
    if _logger_manager is None:
        _logger_manager = LoggerManager()
    return _logger_manager


def get_logger(name: Optional[str] = None) -> logging.Logger:
    """
    获取日志器

    Args:
        name: 日志器名称（可选，默认为 'agent_framework'）

    Returns:
        配置好的日志器实例
    """
    logger_name = name or "agent_framework"
    return _get_manager().get_logger(logger_name)


def setup_logging(
    level: str = "INFO",
    file_path: Optional[str] = None,
    console_output: bool = True,
    file_output: bool = False,
) -> None:
    """
    设置日志配置

    Args:
        level: 日志级别 (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        file_path: 日志文件路径
        console_output: 是否输出到控制台
        file_output: 是否输出到文件
    """
    manager = _get_manager()
    manager.config.level = level
    manager.config.file_path = file_path
    manager.config.console_output = console_output
    manager.config.file_output = file_output
    manager._setup_root_logger()


def log_error(error: Exception, context: str = "") -> None:
    """
    记录错误信息

    Args:
        error: 异常对象
        context: 错误上下文
    """
    logger = get_logger("errors")
    logger.error(f"错误发生: {context} - {type(error).__name__}: {error}")


def log_performance(operation: str, duration: float, details: str = "") -> None:
    """
    记录性能信息

    Args:
        operation: 操作名称
        duration: 持续时间（秒）
        details: 详细信息
    """
    logger = get_logger("performance")
    logger.info(f"性能: {operation} - {duration:.3f}s {details}")


# 便捷的日志器获取函数
def get_module_logger(module_name: str) -> logging.Logger:
    """获取模块日志器"""
    return get_logger(f"agent_framework.{module_name}")


__all__ = [
    "get_logger",
    "setup_logging",
    "log_error",
    "log_performance",
    "get_module_logger",
    "LoggerManager",
    "LogConfig",
]
