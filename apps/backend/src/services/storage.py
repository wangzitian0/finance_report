"""Storage service for statement uploads."""

from __future__ import annotations

import threading
from typing import Any

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

from src.config import settings
from src.logger import get_logger

logger = get_logger(__name__)


class StorageError(Exception):
    """Raised when storage operations fail."""


class StorageService:
    """Simple S3/MinIO storage wrapper."""

    _checked_buckets: set[str] = set()
    _bucket_lock = threading.Lock()

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

        # Initialize public client if configuration exists
        self.public_client = None
        if settings.s3_public_endpoint:
            self.public_bucket = settings.s3_public_bucket or self.bucket
            self.public_client = boto3.client(
                "s3",
                endpoint_url=settings.s3_public_endpoint,
                aws_access_key_id=settings.s3_public_access_key or settings.s3_access_key,
                aws_secret_access_key=settings.s3_public_secret_key or settings.s3_secret_key,
                region_name=settings.s3_region,
                config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
            )

    def _ensure_bucket(self) -> None:
        with self._bucket_lock:
            if self.bucket in self._checked_buckets:
                return
            try:
                self.client.head_bucket(Bucket=self.bucket)
            except ClientError as exc:
                code = exc.response.get("Error", {}).get("Code")
                if code in ("404", "NoSuchBucket", "NotFound"):
                    try:
                        if settings.s3_region and settings.s3_region != "us-east-1":
                            self.client.create_bucket(
                                Bucket=self.bucket,
                                CreateBucketConfiguration={
                                    "LocationConstraint": settings.s3_region
                                },
                            )
                        else:
                            self.client.create_bucket(Bucket=self.bucket)
                    except (BotoCoreError, ClientError) as create_exc:
                        raise StorageError(f"Failed to create bucket {self.bucket}") from create_exc
                else:
                    raise StorageError(f"Failed to access bucket {self.bucket}") from exc
            except BotoCoreError as exc:
                raise StorageError(f"Failed to access bucket {self.bucket}") from exc
            self._checked_buckets.add(self.bucket)

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
        self._ensure_bucket()
        try:
            self.client.put_object(
                Bucket=self.bucket,
                Key=key,
                Body=content,
                **extra_args,
            )
        except (BotoCoreError, ClientError) as exc:
            logger.error("Failed to upload to S3", bucket=self.bucket, key=key, error=str(exc))
            raise StorageError(f"Failed to upload {key} to {self.bucket}") from exc

    def generate_presigned_url(
        self,
        *,
        key: str,
        expires_in: int | None = None,
        public: bool = False,
    ) -> str:
        """Generate a presigned URL for temporary access.

        Args:
            key: S3 object key
            expires_in: Expiry in seconds
            public: If True, use public endpoint/client (for external services)
        """
        client = self.public_client if (public and self.public_client) else self.client
        bucket = self.public_bucket if (public and self.public_client) else self.bucket

        # Fallback validation: if public requested but no public client,
        # we might be returning an internal URL which external services can't access.
        # But we proceed with internal client as best effort (or maybe the internal
        # endpoint IS accessible).
        
        try:
            return client.generate_presigned_url(
                "get_object",
                Params={"Bucket": bucket, "Key": key},
                ExpiresIn=expires_in or settings.s3_presign_expiry_seconds,
            )
        except (BotoCoreError, ClientError) as exc:
            logger.error(
                "Failed to generate presigned URL",
                bucket=bucket,
                key=key,
                public=public,
                error=str(exc),
            )
            raise StorageError(f"Failed to generate presigned URL for {key}") from exc

    def delete_object(self, key: str) -> None:
        """Delete an object from storage."""
        self._ensure_bucket()
        try:
            self.client.delete_object(Bucket=self.bucket, Key=key)
        except (BotoCoreError, ClientError) as exc:
            logger.error("Failed to delete from S3", bucket=self.bucket, key=key, error=str(exc))
            raise StorageError(f"Failed to delete {key} from {self.bucket}") from exc