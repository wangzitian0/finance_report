"""Tests for Prometheus metrics endpoint (EPIC-012 M4)."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_metrics_endpoint_returns_200(public_client: AsyncClient) -> None:
    """Prometheus /metrics endpoint should return 200 OK."""
    response = await public_client.get("/metrics")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_metrics_endpoint_content_type(public_client: AsyncClient) -> None:
    """Prometheus /metrics endpoint should return text/plain content type."""
    response = await public_client.get("/metrics")
    assert "text/plain" in response.headers["content-type"]


@pytest.mark.asyncio
async def test_metrics_endpoint_contains_prometheus_data(public_client: AsyncClient) -> None:
    """Prometheus /metrics response should contain metric definitions."""
    # Trigger a request first so http_request metrics exist
    await public_client.get("/health")
    response = await public_client.get("/metrics")
    content = response.text
    # prometheus_fastapi_instrumentator exposes http_request_* metrics
    assert "http_request" in content or "python_info" in content
