"""Storage service for statement uploads."""

from __future__ import annotations

from typing import Any

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

from src.config import settings


class StorageError(Exception):
    """Raised when storage operations fail."""


class StorageService:
    """Simple S3/MinIO storage wrapper."""

    def __init__(self, bucket: str | None = None) -> None:
        self.bucket = bucket or settings.s3_bucket
        self.client = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint,
            aws_access_key_id=settings.s3_access_key,
            aws_secret_access_key=settings.s3_secret_key,
            region_name=settings.s3_region,
            config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
        )

    def upload_bytes(
        self,
        *,
        key: str,
        content: bytes,
        content_type: str | None = None,
    ) -> None:
        """Upload raw bytes to object storage."""
        extra_args: dict[str, Any] = {}
        if content_type:
            extra_args["ContentType"] = content_type
        try:
            self.client.put_object(
                Bucket=self.bucket,
                Key=key,
                Body=content,
                **extra_args,
            )
        except (BotoCoreError, ClientError) as exc:
            raise StorageError(f"Failed to upload {key} to {self.bucket}") from exc

    def generate_presigned_url(
        self,
        *,
        key: str,
        expires_in: int | None = None,
    ) -> str:
        """Generate a presigned URL for temporary access."""
        try:
            return self.client.generate_presigned_url(
                "get_object",
                Params={"Bucket": self.bucket, "Key": key},
                ExpiresIn=expires_in or settings.s3_presign_expiry_seconds,
            )
        except (BotoCoreError, ClientError) as exc:
            raise StorageError(f"Failed to generate presigned URL for {key}") from exc
