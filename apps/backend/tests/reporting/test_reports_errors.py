"""Tests to finalize coverage for Issue #64."""

from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from src.models import (
    JournalEntry,
    JournalEntryStatus,
)
from src.services.reporting import ReportError


@pytest.mark.asyncio
async def test_reconciliation_coverage_errors(public_client: AsyncClient):
    """Test batch accept endpoint returns 200 with empty match list."""
    with patch("src.routers.reconciliation.batch_accept_service", new_callable=AsyncMock) as mock:
        mock.return_value = []
        resp = await public_client.post("/reconciliation/batch-accept", json={"match_ids": []})
        assert resp.status_code == 200
        assert resp.json()["total"] == 0
