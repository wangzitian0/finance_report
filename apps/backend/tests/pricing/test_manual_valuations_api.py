from httpx import AsyncClient


class TestAssetsValuationApi:
    async def test_flow5_create_alternative_asset_valuation_snapshot(self, client: AsyncClient) -> None:
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
        create_response = await client.post("/pricing/manual-valuations", json=payload)
        assert create_response.status_code == 201
        created = create_response.json()
        assert created["component_type"] == "property_value"
        assert created["liquidity_class"] == "illiquid"
        assert created["value"] == "1250000.00"
        assert created["provenance"] == "manual"
        assert created["source"] == "manual appraisal"
        assert created["notes"] == "Real estate certified appraisal"
        assert created["id"] is not None

        list_response = await client.get("/pricing/manual-valuations", params={"component_type": "property_value"})
        assert list_response.status_code == 200
        assert any(item["id"] == created["id"] and item["value"] == "1250000.00" for item in list_response.json()["items"])

    async def test_flow5_list_valuation_snapshots(self, client: AsyncClient) -> None:
        payload = {
            "component_type": "other_asset",
            "as_of_date": "2026-06-01",
            "value": "85000.00",
            "currency": "SGD",
            "source": "dealer quote",
        }
        create_resp = await client.post("/pricing/manual-valuations", json=payload)
        assert create_resp.status_code == 201
        list_resp = await client.get("/pricing/manual-valuations?component_type=other_asset")
        assert list_resp.status_code == 200
        data = list_resp.json()
        assert data["total"] >= 1
        assert all(item["component_type"] == "other_asset" for item in data["items"])

    async def test_flow5_append_only_correction_supersedes_snapshot(self, client: AsyncClient) -> None:
        payload = {
            "component_type": "other_asset",
            "as_of_date": "2026-06-15",
            "value": "500000.00",
            "currency": "USD",
            "source": "fund statement",
        }
        create_resp = await client.post("/pricing/manual-valuations", json=payload)
        assert create_resp.status_code == 201
        first_id = create_resp.json()["id"]

        correct_resp = await client.post(
            "/pricing/manual-valuations",
            json={**payload, "value": "525000.00", "notes": "Q2 mark-to-market revaluation"},
        )
        assert correct_resp.status_code == 201
        corrected = correct_resp.json()
        assert corrected["id"] != first_id
        assert corrected["value"] == "525000.00"
        assert corrected["notes"] == "Q2 mark-to-market revaluation"

        list_resp = await client.get("/pricing/manual-valuations", params={"component_type": "other_asset"})
        assert list_resp.status_code == 200
        ids = [item["id"] for item in list_resp.json()["items"]]
        assert corrected["id"] in ids
        assert first_id not in ids

    async def test_flow5_invalid_component_type_returns_400(self, client: AsyncClient) -> None:
        resp = await client.get("/pricing/manual-valuations?component_type=non_existent_type")
        assert resp.status_code == 400
