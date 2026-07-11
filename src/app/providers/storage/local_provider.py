from __future__ import annotations

import logging
import shutil
from pathlib import Path

from app.providers.storage.base import StorageObject

logger = logging.getLogger(__name__)


class LocalStorageProvider:
    name = "local"

    def __init__(self, base_dir: Path, public_base_url: str = ""):
        self._base_dir = base_dir
        self._public_base_url = public_base_url
        base_dir.mkdir(parents=True, exist_ok=True)

    async def upload(self, local_path: Path, key: str) -> StorageObject:
        dest = self._base_dir / key
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(str(local_path), str(dest))
        url = self.get_url(key)
        size = dest.stat().st_size
        logger.info(f"Local upload: {key} ({size} bytes)")
        return StorageObject(key=key, url=url, size=size, provider=self.name)

    async def download(self, key: str, local_path: Path) -> Path:
        src = self._base_dir / key
        if not src.exists():
            raise FileNotFoundError(f"Object not found: {key}")
        local_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(str(src), str(local_path))
        return local_path

    def get_url(self, key: str) -> str:
        if self._public_base_url:
            return f"{self._public_base_url.rstrip('/')}/{key}"
        return str(self._base_dir / key)


class S3StorageProvider:
    name = "s3"

    def __init__(
        self,
        endpoint: str = "",
        access_key: str = "",
        secret_key: str = "",
        bucket: str = "",
        public_base_url: str = "",
        region: str = "",
    ):
        self._endpoint = endpoint
        self._access_key = access_key
        self._secret_key = secret_key
        self._bucket = bucket
        self._public_base_url = public_base_url
        self._region = region

    async def upload(self, local_path: Path, key: str) -> StorageObject:
        try:
            import boto3
            from botocore.config import Config as BotoConfig
        except ImportError:
            raise RuntimeError("boto3 not installed")

        s3 = boto3.client(
            "s3",
            endpoint_url=self._endpoint or None,
            aws_access_key_id=self._access_key,
            aws_secret_access_key=self._secret_key,
            region_name=self._region or "auto",
            config=BotoConfig(signature_version="s3v4"),
        )
        s3.upload_file(str(local_path), self._bucket, key)
        url = self.get_url(key)
        size = local_path.stat().st_size
        logger.info(f"S3 upload: {key} → {self._bucket} ({size} bytes)")
        return StorageObject(key=key, url=url, size=size, provider=self.name)

    async def download(self, key: str, local_path: Path) -> Path:
        try:
            import boto3
        except ImportError:
            raise RuntimeError("boto3 not installed")

        s3 = boto3.client(
            "s3",
            endpoint_url=self._endpoint or None,
            aws_access_key_id=self._access_key,
            aws_secret_access_key=self._secret_key,
            region_name=self._region or "auto",
        )
        local_path.parent.mkdir(parents=True, exist_ok=True)
        s3.download_file(self._bucket, key, str(local_path))
        return local_path

    def get_url(self, key: str) -> str:
        if self._public_base_url:
            return f"{self._public_base_url.rstrip('/')}/{key}"
        if self._endpoint:
            return f"{self._endpoint}/{self._bucket}/{key}"
        return f"https://{self._bucket}.s3.amazonaws.com/{key}"
