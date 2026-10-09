"""API integration tests for GET /reports/data-quality endpoint (#2294)."""

from unittest.mock import AsyncMock, patch

import pytest
from fastapi import status
from httpx import AsyncClient

from src.identity import User
from src.reporting import ReportError


class TestDataQualityRouter:
    """Test data quality observatory endpoint."""

    @pytest.mark.asyncio
    async def test_get_data_quality_health_endpoint_success(
        self,
        client: AsyncClient,
        db,
        test_user: User,
    ):
        """GET /reports/data-quality returns 200 with full health observatory payload."""
        response = await client.get("/reports/data-quality")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()

        assert "score" in data
        assert isinstance(data["score"], int)
        assert 0 <= data["score"] <= 100

        assert "grade" in data
        assert data["grade"] in [
            "A_AUDIT_READY",
            "B_BALANCED_GAPS",
            "C_ATTENTION_NEEDED",
            "D_OUT_OF_BALANCE",
        ]

        assert "as_of_date" in data
        assert "currency" in data

        # 4 Core Invariants
        assert "equation_invariant" in data
        assert "is_healthy" in data["equation_invariant"]
        assert "temporal_continuity_invariant" in data
        assert "reconciliation_purity_invariant" in data
        assert "lineage_anchors_invariant" in data

        # Timeline & Action items
        assert "timeline" in data
        assert isinstance(data["timeline"], list)
        assert len(data["timeline"]) == 12

        assert "action_items" in data
        assert isinstance(data["action_items"], list)

    @pytest.mark.asyncio
    async def test_get_data_quality_health_with_custom_params(
        self,
        client: AsyncClient,
        db,
        test_user: User,
    ):
        """GET /reports/data-quality supports custom as_of_date and currency query params."""
        custom_date = "2026-06-30"
        custom_currency = "USD"
        response = await client.get(f"/reports/data-quality?as_of_date={custom_date}&currency={custom_currency}")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["as_of_date"] == custom_date
        assert data["currency"] == custom_currency

    @pytest.mark.asyncio
    @patch("src.routers.reports.compute_personal_data_quality")
    async def test_get_data_quality_health_report_error_returns_400(
        self,
        mock_compute: AsyncMock,
        client: AsyncClient,
        db,
        test_user: User,
    ):
        """ReportError raised during calculation safely returns HTTP 400 Bad Request."""
        mock_compute.side_effect = ReportError("Exchange rate unavailable for SGD/JPY")

        response = await client.get("/reports/data-quality")
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "Exchange rate unavailable" in response.text
