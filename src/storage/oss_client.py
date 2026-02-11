"""
OSS 客户端抽象

提供统一的对象存储接口，支持 MinIO 和阿里云 OSS。
"""

from abc import ABC, abstractmethod
from typing import Union, BinaryIO, Optional, List, Dict, Any
from pathlib import Path
from src.utils.logger import get_logger

logger = get_logger()


class BaseOSSClient(ABC):
    """OSS 客户端抽象基类"""
    
    @abstractmethod
    async def upload_file(
        self,
        local_path: Union[str, Path],
        oss_path: str,
        metadata: Optional[Dict[str, str]] = None
    ) -> str:
        """
        上传文件到 OSS
        
        Args:
            local_path: 本地文件路径
            oss_path: OSS 对象路径
            metadata: 元数据
        
        Returns:
            OSS 对象 URL
        """
        pass
    
    @abstractmethod
    async def download_file(
        self,
        oss_path: str,
        local_path: Union[str, Path]
    ) -> str:
        """
        从 OSS 下载文件
        
        Args:
            oss_path: OSS 对象路径
            local_path: 本地文件路径
        
        Returns:
            本地文件路径
        """
        pass
    
    @abstractmethod
    async def read_object(self, oss_path: str) -> bytes:
        """
        读取 OSS 对象内容
        
        Args:
            oss_path: OSS 对象路径
        
        Returns:
            对象内容（字节）
        """
        pass
    
    @abstractmethod
    async def write_object(
        self,
        oss_path: str,
        data: Union[bytes, str],
        metadata: Optional[Dict[str, str]] = None
    ) -> str:
        """
        写入内容到 OSS 对象
        
        Args:
            oss_path: OSS 对象路径
            data: 数据（字节或字符串）
            metadata: 元数据
        
        Returns:
            OSS 对象 URL
        """
        pass
    
    @abstractmethod
    async def delete_object(self, oss_path: str) -> bool:
        """
        删除 OSS 对象
        
        Args:
            oss_path: OSS 对象路径
        
        Returns:
            是否删除成功
        """
        pass
    
    @abstractmethod
    async def list_objects(
        self,
        prefix: str,
        recursive: bool = False
    ) -> List[str]:
        """
        列出指定前缀下的对象
        
        Args:
            prefix: 对象前缀
            recursive: 是否递归列出
        
        Returns:
            对象路径列表
        """
        pass
    
    @abstractmethod
    async def object_exists(self, oss_path: str) -> bool:
        """
        检查对象是否存在
        
        Args:
            oss_path: OSS 对象路径
        
        Returns:
            是否存在
        """
        pass
    
    @abstractmethod
    async def get_presigned_url(
        self,
        oss_path: str,
        expiration: int = 3600
    ) -> str:
        """
        获取预签名 URL
        
        Args:
            oss_path: OSS 对象路径
            expiration: 过期时间（秒）
        
        Returns:
            预签名 URL
        """
        pass


class MinIOClient(BaseOSSClient):
    """MinIO 客户端实现"""
    
    def __init__(
        self,
        endpoint: str,
        access_key: str,
        secret_key: str,
        bucket_name: str,
        secure: bool = False
    ):
        """
        初始化 MinIO 客户端
        
        Args:
            endpoint: MinIO 服务地址
            access_key: Access Key
            secret_key: Secret Key
            bucket_name: 存储桶名称
            secure: 是否使用 HTTPS
        """
        self.endpoint = endpoint
        self.access_key = access_key
        self.secret_key = secret_key
        self.bucket_name = bucket_name
        self.secure = secure
        
        try:
            from minio import Minio
            self.client = Minio(
                endpoint=endpoint,
                access_key=access_key,
                secret_key=secret_key,
                secure=secure
            )
            
            # 确保存储桶存在
            if not self.client.bucket_exists(bucket_name):
                self.client.make_bucket(bucket_name)
                logger.info(f"创建 MinIO 存储桶: {bucket_name}")
        
        except ImportError:
            raise ImportError("需要安装 minio: pip install minio")
    
    async def upload_file(
        self,
        local_path: Union[str, Path],
        oss_path: str,
        metadata: Optional[Dict[str, str]] = None
    ) -> str:
        """上传文件到 MinIO"""
        import asyncio
        
        local_path = Path(local_path)
        
        await asyncio.to_thread(
            self.client.fput_object,
            self.bucket_name,
            oss_path,
            str(local_path),
            metadata=metadata
        )
        
        return f"{self.endpoint}/{self.bucket_name}/{oss_path}"
    
    async def download_file(
        self,
        oss_path: str,
        local_path: Union[str, Path]
    ) -> str:
        """从 MinIO 下载文件"""
        import asyncio
        
        local_path = Path(local_path)
        local_path.parent.mkdir(parents=True, exist_ok=True)
        
        await asyncio.to_thread(
            self.client.fget_object,
            self.bucket_name,
            oss_path,
            str(local_path)
        )
        
        return str(local_path)
    
    async def read_object(self, oss_path: str) -> bytes:
        """读取 MinIO 对象内容"""
        import asyncio
        
        response = await asyncio.to_thread(
            self.client.get_object,
            self.bucket_name,
            oss_path
        )
        
        try:
            return response.read()
        finally:
            response.close()
            response.release_conn()
    
    async def write_object(
        self,
        oss_path: str,
        data: Union[bytes, str],
        metadata: Optional[Dict[str, str]] = None
    ) -> str:
        """写入内容到 MinIO 对象"""
        import asyncio
        from io import BytesIO
        
        if isinstance(data, str):
            data = data.encode('utf-8')
        
        data_stream = BytesIO(data)
        
        await asyncio.to_thread(
            self.client.put_object,
            self.bucket_name,
            oss_path,
            data_stream,
            length=len(data),
            metadata=metadata
        )
        
        return f"{self.endpoint}/{self.bucket_name}/{oss_path}"
    
    async def delete_object(self, oss_path: str) -> bool:
        """删除 MinIO 对象"""
        import asyncio
        
        try:
            await asyncio.to_thread(
                self.client.remove_object,
                self.bucket_name,
                oss_path
            )
            return True
        except Exception as e:
            logger.error(f"删除对象失败 {oss_path}: {e}")
            return False
    
    async def list_objects(
        self,
        prefix: str,
        recursive: bool = False
    ) -> List[str]:
        """列出指定前缀下的对象"""
        import asyncio
        
        objects = await asyncio.to_thread(
            self.client.list_objects,
            self.bucket_name,
            prefix=prefix,
            recursive=recursive
        )
        
        return [obj.object_name for obj in objects]
    
    async def object_exists(self, oss_path: str) -> bool:
        """检查对象是否存在"""
        import asyncio
        
        try:
            await asyncio.to_thread(
                self.client.stat_object,
                self.bucket_name,
                oss_path
            )
            return True
        except Exception:
            return False
    
    async def get_presigned_url(
        self,
        oss_path: str,
        expiration: int = 3600
    ) -> str:
        """获取预签名 URL"""
        import asyncio
        from datetime import timedelta
        
        url = await asyncio.to_thread(
            self.client.presigned_get_object,
            self.bucket_name,
            oss_path,
            expires=timedelta(seconds=expiration)
        )
        
        return url


class AliyunOSSClient(BaseOSSClient):
    """阿里云 OSS 客户端实现"""
    
    def __init__(
        self,
        endpoint: str,
        access_key_id: str,
        access_key_secret: str,
        bucket_name: str
    ):
        """
        初始化阿里云 OSS 客户端
        
        Args:
            endpoint: OSS Endpoint
            access_key_id: Access Key ID
            access_key_secret: Access Key Secret
            bucket_name: 存储桶名称
        """
        self.endpoint = endpoint
        self.access_key_id = access_key_id
        self.access_key_secret = access_key_secret
        self.bucket_name = bucket_name
        
        try:
            import oss2
            
            auth = oss2.Auth(access_key_id, access_key_secret)
            self.bucket = oss2.Bucket(auth, endpoint, bucket_name)
        
        except ImportError:
            raise ImportError("需要安装 oss2: pip install oss2")
    
    async def upload_file(
        self,
        local_path: Union[str, Path],
        oss_path: str,
        metadata: Optional[Dict[str, str]] = None
    ) -> str:
        """上传文件到阿里云 OSS"""
        import asyncio
        
        local_path = Path(local_path)
        
        await asyncio.to_thread(
            self.bucket.put_object_from_file,
            oss_path,
            str(local_path),
            headers=metadata
        )
        
        return f"https://{self.bucket_name}.{self.endpoint}/{oss_path}"
    
    async def download_file(
        self,
        oss_path: str,
        local_path: Union[str, Path]
    ) -> str:
        """从阿里云 OSS 下载文件"""
        import asyncio
        
        local_path = Path(local_path)
        local_path.parent.mkdir(parents=True, exist_ok=True)
        
        await asyncio.to_thread(
            self.bucket.get_object_to_file,
            oss_path,
            str(local_path)
        )
        
        return str(local_path)
    
    async def read_object(self, oss_path: str) -> bytes:
        """读取阿里云 OSS 对象内容"""
        import asyncio
        
        result = await asyncio.to_thread(
            self.bucket.get_object,
            oss_path
        )
        
        return result.read()
    
    async def write_object(
        self,
        oss_path: str,
        data: Union[bytes, str],
        metadata: Optional[Dict[str, str]] = None
    ) -> str:
        """写入内容到阿里云 OSS 对象"""
        import asyncio
        
        if isinstance(data, str):
            data = data.encode('utf-8')
        
        await asyncio.to_thread(
            self.bucket.put_object,
            oss_path,
            data,
            headers=metadata
        )
        
        return f"https://{self.bucket_name}.{self.endpoint}/{oss_path}"
    
    async def delete_object(self, oss_path: str) -> bool:
        """删除阿里云 OSS 对象"""
        import asyncio
        
        try:
            await asyncio.to_thread(
                self.bucket.delete_object,
                oss_path
            )
            return True
        except Exception as e:
            logger.error(f"删除对象失败 {oss_path}: {e}")
            return False
    
    async def list_objects(
        self,
        prefix: str,
        recursive: bool = False
    ) -> List[str]:
        """列出指定前缀下的对象"""
        import asyncio
        
        delimiter = '' if recursive else '/'
        
        result = await asyncio.to_thread(
            lambda: list(self.bucket.list_objects(prefix=prefix, delimiter=delimiter).object_list)
        )
        
        return [obj.key for obj in result]
    
    async def object_exists(self, oss_path: str) -> bool:
        """检查对象是否存在"""
        import asyncio
        
        try:
            await asyncio.to_thread(
                self.bucket.object_exists,
                oss_path
            )
            return True
        except Exception:
            return False
    
    async def get_presigned_url(
        self,
        oss_path: str,
        expiration: int = 3600
    ) -> str:
        """获取预签名 URL"""
        import asyncio
        
        url = await asyncio.to_thread(
            self.bucket.sign_url,
            'GET',
            oss_path,
            expiration
        )
        
        return url

