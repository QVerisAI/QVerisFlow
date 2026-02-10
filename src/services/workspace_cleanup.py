"""
定时任务执行记录清理服务

根据配置的保留策略自动清理过期的执行记录，
避免磁盘空间无限增长。
"""

import asyncio
import os
import shutil
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from src.utils.logger import get_logger

logger = get_logger()


class WorkspaceCleanupService:
    """
    工作空间清理服务
    
    支持两种清理策略：
    1. 按执行次数：保留每个工作流最近 N 次执行
    2. 按时间：删除超过 N 天的执行记录
    """
    
    def __init__(
        self,
        workspace_path: str,
        max_executions_per_workflow: int = 10,
        max_age_days: int = 30,
    ):
        """
        初始化清理服务
        
        Args:
            workspace_path: 执行记录存储路径
            max_executions_per_workflow: 每个工作流保留的最大执行次数
            max_age_days: 保留最近 N 天的记录
        """
        self.workspace_path = Path(workspace_path)
        self.max_executions_per_workflow = max_executions_per_workflow
        self.max_age_days = max_age_days
        
        # 清理统计
        self._last_cleanup_time: Optional[datetime] = None
        self._total_cleaned_count: int = 0
        self._total_cleaned_size: int = 0
        
    @classmethod
    def from_config(cls) -> "WorkspaceCleanupService":
        """
        从配置创建清理服务实例
        
        Returns:
            WorkspaceCleanupService 实例
        """
        try:
            from src.config import get_scheduled_execution_config
            config = get_scheduled_execution_config()
            
            workspace_path = config.get("workspace_path", "./data/scheduled_executions")
            retention = config.get("retention", {})
            
            # 确保配置值是正确的整数类型（环境变量可能返回字符串）
            max_executions = retention.get("max_executions_per_workflow", 10)
            max_age = retention.get("max_age_days", 30)
            
            return cls(
                workspace_path=workspace_path,
                max_executions_per_workflow=int(max_executions) if max_executions else 10,
                max_age_days=int(max_age) if max_age else 30,
            )
        except Exception as e:
            logger.warning(f"从配置创建清理服务失败，使用默认配置: {e}")
            return cls(
                workspace_path="./data/scheduled_executions",
                max_executions_per_workflow=10,
                max_age_days=30,
            )
    
    async def cleanup(self) -> Dict[str, int]:
        """
        执行清理操作
        
        Returns:
            清理结果统计：
            - directories_removed: 删除的目录数量
            - bytes_freed: 释放的空间（字节）
            - errors: 错误数量
        """
        result = {
            "directories_removed": 0,
            "bytes_freed": 0,
            "errors": 0,
        }
        
        if not self.workspace_path.exists():
            logger.info(f"工作空间目录不存在，跳过清理: {self.workspace_path}")
            return result
        
        logger.info(f"开始清理定时任务执行记录: {self.workspace_path}")
        logger.info(f"保留策略: 每个工作流最多 {self.max_executions_per_workflow} 次执行，最多保留 {self.max_age_days} 天")
        
        # 收集所有执行目录
        execution_dirs = self._collect_execution_dirs()
        
        if not execution_dirs:
            logger.info("没有找到需要清理的执行目录")
            return result
        
        # 按工作流 ID 分组
        grouped = self._group_by_workflow(execution_dirs)
        
        # 确定要删除的目录
        dirs_to_remove = self._get_dirs_to_remove(grouped)
        
        # 执行删除
        for dir_path in dirs_to_remove:
            try:
                dir_size = self._get_dir_size(dir_path)
                # 使用线程池执行 IO 密集操作
                await asyncio.get_event_loop().run_in_executor(
                    None, shutil.rmtree, str(dir_path)
                )
                result["directories_removed"] += 1
                result["bytes_freed"] += dir_size
                logger.debug(f"已删除: {dir_path} ({self._format_size(dir_size)})")
            except Exception as e:
                logger.error(f"删除目录失败 {dir_path}: {e}")
                result["errors"] += 1
        
        # 更新统计
        self._last_cleanup_time = datetime.now()
        self._total_cleaned_count += result["directories_removed"]
        self._total_cleaned_size += result["bytes_freed"]
        
        logger.info(
            f"清理完成: 删除 {result['directories_removed']} 个目录，"
            f"释放 {self._format_size(result['bytes_freed'])}，"
            f"错误 {result['errors']} 个"
        )
        
        return result
    
    def _collect_execution_dirs(self) -> List[Tuple[Path, datetime]]:
        """
        收集所有执行目录及其创建时间
        
        Returns:
            (目录路径, 创建时间) 元组列表
        """
        execution_dirs = []
        
        try:
            for item in self.workspace_path.iterdir():
                if not item.is_dir():
                    continue
                
                # 获取目录创建/修改时间
                try:
                    # 优先使用 ctime（创建时间），在某些系统上可能不准确
                    # 退回使用 mtime（修改时间）
                    stat = item.stat()
                    created_time = datetime.fromtimestamp(stat.st_mtime)
                    execution_dirs.append((item, created_time))
                except Exception as e:
                    logger.warning(f"获取目录时间失败 {item}: {e}")
                    
        except Exception as e:
            logger.error(f"遍历工作空间目录失败: {e}")
            
        return execution_dirs
    
    def _group_by_workflow(
        self, execution_dirs: List[Tuple[Path, datetime]]
    ) -> Dict[str, List[Tuple[Path, datetime]]]:
        """
        按工作流 ID 分组执行目录
        
        目录命名格式：{workflow_id}_{execution_id} 或 {workflow_id}
        
        Returns:
            {workflow_id: [(目录, 时间), ...]} 字典
        """
        grouped: Dict[str, List[Tuple[Path, datetime]]] = {}
        
        for dir_path, created_time in execution_dirs:
            # 从目录名提取工作流 ID
            # 格式可能是: workflow_name_version_hash_execution_id
            # 我们按最后一个 _ 分割，前面的部分作为 workflow_id
            dir_name = dir_path.name
            
            # 检查是否有检查点目录来确认是有效的执行目录
            checkpoint_dir = dir_path / "checkpoints"
            if not checkpoint_dir.exists():
                # 可能是子目录（如 workspace_id_node_id），跳过
                continue
            
            # 使用完整目录名作为标识（因为包含了 execution_id）
            # 但分组时用工作流 ID
            # 简单处理：使用目录的父部分作为 workflow_id
            # 实际上每个执行都是独立目录，不需要按工作流分组
            # 改为按目录本身处理
            workflow_id = dir_name
            
            if workflow_id not in grouped:
                grouped[workflow_id] = []
            grouped[workflow_id].append((dir_path, created_time))
        
        # 按时间排序（最新的在前）
        for workflow_id in grouped:
            grouped[workflow_id].sort(key=lambda x: x[1], reverse=True)
            
        return grouped
    
    def _get_dirs_to_remove(
        self, grouped: Dict[str, List[Tuple[Path, datetime]]]
    ) -> List[Path]:
        """
        根据保留策略确定要删除的目录
        
        Returns:
            要删除的目录列表
        """
        dirs_to_remove = []
        cutoff_time = datetime.now() - timedelta(days=self.max_age_days)
        
        for workflow_id, dirs_with_time in grouped.items():
            # 按时间排序后，保留前 N 个
            for i, (dir_path, created_time) in enumerate(dirs_with_time):
                should_remove = False
                
                # 策略 1：超过最大保留次数
                if i >= self.max_executions_per_workflow:
                    should_remove = True
                    logger.debug(f"超过最大保留次数 ({i + 1} > {self.max_executions_per_workflow}): {dir_path}")
                
                # 策略 2：超过最大保留天数
                if created_time < cutoff_time:
                    should_remove = True
                    logger.debug(f"超过最大保留天数 ({self.max_age_days}): {dir_path}")
                
                if should_remove:
                    dirs_to_remove.append(dir_path)
                    
        return dirs_to_remove
    
    def _get_dir_size(self, dir_path: Path) -> int:
        """计算目录大小（字节）"""
        total_size = 0
        try:
            for item in dir_path.rglob("*"):
                if item.is_file():
                    total_size += item.stat().st_size
        except Exception as e:
            logger.warning(f"计算目录大小失败 {dir_path}: {e}")
        return total_size
    
    @staticmethod
    def _format_size(size_bytes: int) -> str:
        """格式化文件大小"""
        for unit in ["B", "KB", "MB", "GB", "TB"]:
            if size_bytes < 1024:
                return f"{size_bytes:.2f} {unit}"
            size_bytes /= 1024
        return f"{size_bytes:.2f} PB"
    
    def get_stats(self) -> Dict[str, any]:
        """获取清理统计信息"""
        return {
            "workspace_path": str(self.workspace_path),
            "max_executions_per_workflow": self.max_executions_per_workflow,
            "max_age_days": self.max_age_days,
            "last_cleanup_time": self._last_cleanup_time.isoformat() if self._last_cleanup_time else None,
            "total_cleaned_count": self._total_cleaned_count,
            "total_cleaned_size": self._total_cleaned_size,
            "total_cleaned_size_human": self._format_size(self._total_cleaned_size),
        }


# 全局清理服务实例
_cleanup_service: Optional[WorkspaceCleanupService] = None


def get_cleanup_service() -> WorkspaceCleanupService:
    """
    获取全局清理服务实例
    
    Returns:
        WorkspaceCleanupService 实例
    """
    global _cleanup_service
    if _cleanup_service is None:
        _cleanup_service = WorkspaceCleanupService.from_config()
    return _cleanup_service


async def cleanup_scheduled_executions() -> Dict[str, int]:
    """
    便捷函数：执行定时任务执行记录清理
    
    Returns:
        清理结果统计
    """
    service = get_cleanup_service()
    return await service.cleanup()
