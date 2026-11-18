from __future__ import annotations

from unittest.mock import AsyncMock, patch

from fastapi import status
from httpx import AsyncClient

from src.identity import User
from src.reporting import ReportError


class TestDataQualityRouter:
    async def test_get_data_quality_health_endpoint_success_and_params(self, client: AsyncClient, db, test_user: User):
        resp = await client.get("/reports/data-quality")
        data = resp.json()
        assert resp.status_code == status.HTTP_200_OK
        assert isinstance(data["score"], int) and 0 <= data["score"] <= 100
        assert data["grade"] in {"A_AUDIT_READY", "B_BALANCED_GAPS", "C_ATTENTION_NEEDED", "D_OUT_OF_BALANCE"}
        assert {
            "as_of_date",
            "currency",
            "temporal_continuity_invariant",
            "reconciliation_purity_invariant",
            "lineage_anchors_invariant",
        } <= data.keys()
        assert (
            "is_healthy" in data["equation_invariant"]
            and isinstance(data["timeline"], list)
            and len(data["timeline"]) == 12
            and isinstance(data["action_items"], list)
        )

        custom = await client.get("/reports/data-quality?as_of_date=2026-06-30&currency=USD")
        assert custom.status_code == status.HTTP_200_OK and (
            custom.json()["as_of_date"],
            custom.json()["currency"],
        ) == ("2026-06-30", "USD")

    @patch("src.routers.reports.compute_personal_data_quality")
    async def test_get_data_quality_health_report_error_returns_400(
        self, mock_compute: AsyncMock, client: AsyncClient, db, test_user: User
    ):
        mock_compute.side_effect = ReportError("Exchange rate unavailable for SGD/JPY")
        resp = await client.get("/reports/data-quality")
        assert resp.status_code == status.HTTP_400_BAD_REQUEST and "Exchange rate unavailable" in resp.text
