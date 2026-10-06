"""Storage service for statement uploads."""

from __future__ import annotations

import threading
from typing import Any

from botocore.exceptions import BotoCoreError, ClientError
from infra2_sdk.runtime.s3 import (
    S3Settings,
    create_s3_client,
    is_not_found,
    read_object_bytes,
    redact_presigned_url as _sdk_redact_presigned_url,
)

import src.config
from src.observability import get_logger

logger = get_logger(__name__)
settings = src.config.settings

__all__ = ["StorageError", "StorageService", "redact_presigned_url"]


class StorageError(Exception):
    """Raised when storage operations fail."""


def redact_presigned_url(url: str | None) -> str | None:
    """Return a log-safe form of a presigned URL."""
    return _sdk_redact_presigned_url(url)


class StorageService:
    """Simple S3/MinIO storage wrapper."""

    _checked_buckets: set[str] = set()
    _bucket_lock = threading.Lock()

    def __init__(self, bucket: str | None = None) -> None:
        self.bucket = bucket or settings.s3_bucket
        self.client = create_s3_client(
            S3Settings(
                bucket=self.bucket,
                endpoint_url=settings.s3_endpoint,
                access_key_id=settings.s3_access_key,
                secret_access_key=settings.s3_secret_key,
                region_name=settings.s3_region,
                addressing_style="path",
            )
        )

        # Initialize public client if configuration exists
        self.public_client = None
        if settings.s3_public_endpoint:
            self.public_bucket = settings.s3_public_bucket or self.bucket
            self.public_client = create_s3_client(
                S3Settings(
                    bucket=self.public_bucket,
                    endpoint_url=settings.s3_public_endpoint,
                    access_key_id=settings.s3_public_access_key or settings.s3_access_key,
                    secret_access_key=settings.s3_public_secret_key or settings.s3_secret_key,
                    region_name=settings.s3_region,
                    addressing_style="path",
                )
            )

    def _ensure_bucket(self) -> None:
        with self._bucket_lock:
            if self.bucket in self._checked_buckets:
                return
            try:
                self.client.head_bucket(Bucket=self.bucket)
            except ClientError as exc:
                if is_not_found(exc):
                    try:
                        if settings.s3_region and settings.s3_region != "us-east-1":
                            self.client.create_bucket(
                                Bucket=self.bucket,
                                CreateBucketConfiguration={"LocationConstraint": settings.s3_region},
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
        use_public_client = public and self.public_client is not None

        if public and not use_public_client:
            logger.error(
                "Public presigned URL requested but no public S3 client configured",
                bucket=self.bucket,
                key=key,
            )
            # Halt if public URL is requested but cannot be generated via public endpoint
            raise StorageError("Public storage client is not configured; cannot generate public presigned URL")

        client = self.public_client if use_public_client else self.client
        bucket = self.public_bucket if use_public_client else self.bucket

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

    def get_object(self, key: str) -> bytes:
        """Download raw object bytes."""
        self._ensure_bucket()
        try:
            return read_object_bytes(self.client, bucket=self.bucket, key=key)
        except (BotoCoreError, ClientError) as exc:
            logger.error("Failed to download from S3", bucket=self.bucket, key=key, error=str(exc))
            raise StorageError(f"Failed to download {key} from {self.bucket}") from exc

    def delete_object(self, key: str) -> None:
        """Delete an object from storage."""
        self._ensure_bucket()
        try:
            self.client.delete_object(Bucket=self.bucket, Key=key)
        except (BotoCoreError, ClientError) as exc:
            logger.error("Failed to delete from S3", bucket=self.bucket, key=key, error=str(exc))
            raise StorageError(f"Failed to delete {key} from {self.bucket}") from exc
