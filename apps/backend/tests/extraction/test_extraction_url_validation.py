"""Tests for URL validation in ExtractionService."""

import pytest

from src.services.extraction import ExtractionService


@pytest.fixture
def service():
    """ExtractionService instance."""
    return ExtractionService()


def test_validate_external_url_public_https(service):
    """Public HTTPS URLs should be allowed."""
    assert service._validate_external_url("https://example.com/file.pdf") is True
    assert service._validate_external_url("https://s3.amazonaws.com/bucket/obj") is True


def test_validate_external_url_public_http(service):
    """Public HTTP URLs should be allowed."""
    assert service._validate_external_url("http://example.com/file.pdf") is True


def test_validate_external_url_reject_localhost(service):
    """Localhost should be rejected."""
    assert service._validate_external_url("http://localhost:9000/file.pdf") is False
    assert service._validate_external_url("http://127.0.0.1:9000/file.pdf") is False
    assert service._validate_external_url("http://[::1]:9000/file.pdf") is False


def test_validate_external_url_ipv6_private(service):
    """Private IPv6 ranges should be rejected."""
    # Unique Local Address (ULA)
    assert service._validate_external_url("http://[fd00::1]/file.pdf") is False
    # Link-local
    assert service._validate_external_url("http://[fe80::1]/file.pdf") is False


def test_validate_external_url_reject_private_10(service):
    """10.x.x.x private range should be rejected."""
    assert service._validate_external_url("http://10.0.0.1/file.pdf") is False
    assert service._validate_external_url("http://10.255.255.255/file.pdf") is False


def test_validate_external_url_reject_private_172(service):
    """172.16.x.x - 172.31.x.x private range should be rejected."""
    assert service._validate_external_url("http://172.16.0.1/file.pdf") is False
    assert service._validate_external_url("http://172.31.255.255/file.pdf") is False
    # 172.15 and 172.32 are public
    assert service._validate_external_url("http://172.15.0.1/file.pdf") is True
    assert service._validate_external_url("http://172.32.0.1/file.pdf") is True


def test_validate_external_url_reject_private_192(service):
    """192.168.x.x private range should be rejected."""
    assert service._validate_external_url("http://192.168.1.1/file.pdf") is False
    assert service._validate_external_url("http://192.168.0.254/file.pdf") is False


def test_validate_external_url_reject_internal_names(service):
    """Internal hostnames (no dots) should be rejected (common in Docker)."""
    assert service._validate_external_url("http://minio:9000/bucket/file") is False
    assert service._validate_external_url("http://postgres/file") is False
    assert service._validate_external_url("http://backend/file") is False


def test_validate_external_url_invalid_urls(service):
    """Invalid URLs should handle gracefully."""

    assert service._validate_external_url("not-a-url") is False

    assert service._validate_external_url("") is False

    # Technically external but we really only care if it passes the IP/hostname check.

    # The service doesn't strictly validate scheme here, but downstream HTTP client might fail.

    # For now, validation allows it if the hostname is public.

    assert service._validate_external_url("ftp://example.com") is True
