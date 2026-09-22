"""Tests for Flow 5: Alternative Asset Appraisal & Valuation Ingestion API.

SSOT Flow 5:
- Name: Alternative Asset Appraisal & Valuation Ingestion
- Title: 不动产/车辆/私募等另类资产凭证录入
- UI Surface: /assets
- Frontend Component: AssetsPage
- Backend Endpoint: POST /assets/valuation-snapshots
- Invariant: Valuation creates journal entry adjusting Asset and UnrealizedGain (or audited valuation snapshot)
- Reference: apps/backend/tests/api/test_assets_valuation_api.py
"""

from uuid import uuid4

from httpx import AsyncClient


class TestAssetsValuationApi:
    """Test suite for Flow 5: POST/GET/PATCH/DELETE /assets/valuation-snapshots."""

    async def test_flow5_create_alternative_asset_valuation_snapshot(self, client: AsyncClient) -> None:
        """Flow 5: Ingestion of alternative asset appraisal snapshot persists with correct provenance."""
        payload = {
            "component_type": "property_value",
            "as_of_date": "2026-05-18",
            "value": "1250000.00",
            "currency": "SGD",
            "source": "manual appraisal",
            "valuation_basis": "market_appraisal",
            "notes": "Real estate certified appraisal",
            "recurrence_days": 90,
            "reminder_date": "2026-08-16",
        }

        create_response = await client.post("/assets/valuation-snapshots", json=payload)
        assert create_response.status_code == 201
        created = create_response.json()
        assert created["component_type"] == "property_value"
        assert created["liquidity_class"] == "illiquid"
        assert created["value"] == "1250000.00"
        assert created["provenance"] == "manual"
        assert created["source"] == "manual appraisal"
        assert created["notes"] == "Real estate certified appraisal"
        assert created["id"] is not None

        # Verify retrieval by ID
        get_response = await client.get(f"/assets/valuation-snapshots/{created['id']}")
        assert get_response.status_code == 200
        fetched = get_response.json()
        assert fetched["id"] == created["id"]
        assert fetched["value"] == "1250000.00"

    async def test_flow5_list_valuation_snapshots(self, client: AsyncClient) -> None:
        """Flow 5: Valuation snapshots can be queried and filtered by component_type."""
        payload = {
            "component_type": "other_asset",
            "as_of_date": "2026-06-01",
            "value": "85000.00",
            "currency": "SGD",
            "source": "dealer quote",
        }
        create_resp = await client.post("/assets/valuation-snapshots", json=payload)
        assert create_resp.status_code == 201

        list_resp = await client.get("/assets/valuation-snapshots?component_type=other_asset")
        assert list_resp.status_code == 200
        data = list_resp.json()
        assert data["total"] >= 1
        assert any(item["component_type"] == "other_asset" for item in data["items"])

    async def test_flow5_update_and_delete_valuation_snapshot(self, client: AsyncClient) -> None:
        """Flow 5: Snapshot supports in-place valuation adjustment; physical deletion is rejected with 400 (immutable audit trail)."""
        payload = {
            "component_type": "other_asset",
            "as_of_date": "2026-06-15",
            "value": "500000.00",
            "currency": "USD",
            "source": "fund statement",
        }
        create_resp = await client.post("/assets/valuation-snapshots", json=payload)
        assert create_resp.status_code == 201
        snapshot_id = create_resp.json()["id"]

        # Update valuation
        update_resp = await client.patch(
            f"/assets/valuation-snapshots/{snapshot_id}",
            json={"value": "525000.00", "notes": "Q2 mark-to-market revaluation"},
        )
        assert update_resp.status_code == 200
        updated = update_resp.json()
        assert updated["value"] == "525000.00"
        assert updated["notes"] == "Q2 mark-to-market revaluation"

        # Deletion is rejected for immutable decision-backed snapshots
        delete_resp = await client.delete(f"/assets/valuation-snapshots/{snapshot_id}")
        assert delete_resp.status_code == 400

        # Confirm 404 for non-existent snapshot
        missing_id = uuid4()
        get_resp = await client.get(f"/assets/valuation-snapshots/{missing_id}")
        assert get_resp.status_code == 404

    async def test_flow5_invalid_component_type_returns_400(self, client: AsyncClient) -> None:
        """Flow 5: Invalid component_type query parameter triggers 400 Bad Request."""
        resp = await client.get("/assets/valuation-snapshots?component_type=non_existent_type")
        assert resp.status_code == 400
