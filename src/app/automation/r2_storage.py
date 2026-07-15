from __future__ import annotations

from pathlib import Path

import boto3


class R2Storage:
    def __init__(
        self,
        endpoint_url: str,
        access_key_id: str,
        secret_access_key: str,
        bucket: str,
        public_base_url: str,
    ):
        self.bucket = bucket
        self.public_base_url = public_base_url.rstrip("/")
        self.client = boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            aws_access_key_id=access_key_id,
            aws_secret_access_key=secret_access_key,
            region_name="auto",
        )

    def upload_video(self, source: Path, object_key: str) -> str:
        self.client.upload_file(
            str(source),
            self.bucket,
            object_key,
            ExtraArgs={
                "ContentType": "video/mp4",
                "CacheControl": "private, no-store, max-age=0",
            },
        )
        return f"{self.public_base_url}/{object_key}"

    def delete(self, object_key: str) -> None:
        self.client.delete_object(Bucket=self.bucket, Key=object_key)
