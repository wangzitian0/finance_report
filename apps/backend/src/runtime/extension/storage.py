"""Storage service for statement uploads."""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any, TypeVar
from urllib.parse import urlsplit, urlunsplit

import boto3
from botocore.config import Config as BotocoreConfig
from botocore.exceptions import BotoCoreError, ClientError
from infra2_sdk.storage import (
    S3Settings,
    create_s3_client,
    ensure_bucket,
    put_object_bytes,
    read_object_bytes,
    redact_presigned_url as _sdk_redact_presigned_url,
)

import src.config
from src.observability import get_logger

logger = get_logger(__name__)
settings = src.config.settings

__all__ = ["StorageError", "StorageService", "redact_presigned_url"]

_T = TypeVar("_T")


def redact_presigned_url(url: str | None) -> str | None:
    """Strip presigned query secrets and URL fragments while handling empty or invalid inputs."""
    if not url:
        return url
    try:
        urlsplit(url)
    except ValueError:
        return "<invalid-url>"
    redacted = _sdk_redact_presigned_url(url)
    parts = urlsplit(redacted)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, parts.query, ""))


def _build_s3_client(
    *,
    bucket: str,
    endpoint_url: str | None,
    access_key_id: str | None,
    secret_access_key: str | None,
    region: str,
) -> Any:
    if isinstance(endpoint_url, str) and endpoint_url.strip():
        return create_s3_client(
            S3Settings(
                bucket=bucket,
                endpoint_url=endpoint_url,
                access_key_id=access_key_id or "",
                secret_access_key=secret_access_key or "",
                region=region,
                use_path_style=True,
            )
        )
    # Moto-backed tests unset `s3_endpoint` (None) so boto3 routes requests in-process without a live server.
    cfg = BotocoreConfig(
        region_name=region,
        signature_version="s3v4",
        connect_timeout=5.0,
        read_timeout=10.0,
        s3={"addressing_style": "path"},
    )
    return boto3.client(
        "s3",
        endpoint_url=None,
        aws_access_key_id=access_key_id,
        aws_secret_access_key=secret_access_key,
        region_name=region,
        config=cfg,
    )


class StorageError(Exception):
    """Raised when storage operations fail."""


class StorageService:
    """Simple S3/MinIO storage wrapper."""

    _checked_buckets: set[str] = set()
    _bucket_lock = threading.Lock()

    def __init__(self, bucket: str | None = None) -> None:
        self.bucket = bucket or settings.s3_bucket
        self._region = (settings.s3_region or "").strip() or "us-east-1"
        self.client = _build_s3_client(
            bucket=self.bucket,
            endpoint_url=settings.s3_endpoint,
            access_key_id=settings.s3_access_key,
            secret_access_key=settings.s3_secret_key,
            region=self._region,
        )
        self.public_client = None
        if settings.s3_public_endpoint:
            self.public_bucket = settings.s3_public_bucket or self.bucket
            self.public_client = _build_s3_client(
                bucket=self.public_bucket,
                endpoint_url=settings.s3_public_endpoint,
                access_key_id=settings.s3_public_access_key or settings.s3_access_key,
                secret_access_key=settings.s3_public_secret_key or settings.s3_secret_key,
                region=self._region,
            )

    def _ensure_bucket(self) -> None:
        with self._bucket_lock:
            if self.bucket in self._checked_buckets:
                return
            try:
                ensure_bucket(self.client, self.bucket, region=self._region)
            except (BotoCoreError, ClientError) as exc:
                op = str(getattr(exc, "operation_name", "") or "").lower()
                verb = "create" if op in ("create_bucket", "createbucket") else "access"
                raise StorageError(f"Failed to {verb} bucket {self.bucket}") from exc
            self._checked_buckets.add(self.bucket)

    def _run_s3(self, fn: Callable[[], _T], *, log_msg: str, err_msg: str, **log_ctx: object) -> _T:
        try:
            return fn()
        except (BotoCoreError, ClientError) as exc:
            logger.error(log_msg, error=str(exc), **log_ctx)
            raise StorageError(err_msg) from exc

    def upload_bytes(self, *, key: str, content: bytes, content_type: str | None = None) -> None:
        self._ensure_bucket()
        self._run_s3(
            lambda: put_object_bytes(
                self.client,
                bucket=self.bucket,
                key=key,
                data=content,
                content_type=content_type or "application/octet-stream",
            ),
            log_msg="Failed to upload to S3",
            err_msg=f"Failed to upload {key} to {self.bucket}",
            bucket=self.bucket,
            key=key,
        )

    def generate_presigned_url(self, *, key: str, expires_in: int | None = None, public: bool = False) -> str:
        use_public = public and self.public_client is not None
        if public and not use_public:
            logger.error(
                "Public presigned URL requested but no public S3 client configured", bucket=self.bucket, key=key
            )
            raise StorageError("Public storage client is not configured; cannot generate public presigned URL")
        client = self.public_client if use_public else self.client
        bucket = self.public_bucket if use_public else self.bucket
        return self._run_s3(
            lambda: client.generate_presigned_url(
                "get_object",
                Params={"Bucket": bucket, "Key": key},
                ExpiresIn=expires_in or settings.s3_presign_expiry_seconds,
            ),
            log_msg="Failed to generate presigned URL",
            err_msg=f"Failed to generate presigned URL for {key}",
            bucket=bucket,
            key=key,
            public=public,
        )

    def get_object(self, key: str) -> bytes:
        self._ensure_bucket()
        return self._run_s3(
            lambda: read_object_bytes(self.client, bucket=self.bucket, key=key),
            log_msg="Failed to download from S3",
            err_msg=f"Failed to download {key} from {self.bucket}",
            bucket=self.bucket,
            key=key,
        )

    def delete_object(self, key: str) -> None:
        self._ensure_bucket()
        self._run_s3(
            lambda: self.client.delete_object(Bucket=self.bucket, Key=key),
            log_msg="Failed to delete from S3",
            err_msg=f"Failed to delete {key} from {self.bucket}",
            bucket=self.bucket,
            key=key,
        )
