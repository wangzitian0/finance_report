from httpx import AsyncClient


class TestAssetsValuationApi:
    async def test_flow5_create_list_supersede_and_invalid_filter(self, client: AsyncClient) -> None:
        prop_payload = {"component_type": "property_value", "as_of_date": "2026-05-18", "value": "1250000.00", "currency": "SGD", "source": "manual appraisal", "valuation_basis": "market_appraisal", "notes": "Real estate certified appraisal", "recurrence_days": 90, "reminder_date": "2026-08-16"}
        create_resp = await client.post("/pricing/manual-valuations", json=prop_payload)
        created = create_resp.json()
        prop_list = await client.get("/pricing/manual-valuations", params={"component_type": "property_value"})

        other_payload = {"component_type": "other_asset", "as_of_date": "2026-06-15", "value": "500000.00", "currency": "USD", "source": "fund statement"}
        first_id = (await client.post("/pricing/manual-valuations", json=other_payload)).json()["id"]
        corr_resp = await client.post("/pricing/manual-valuations", json={**other_payload, "value": "525000.00", "notes": "Q2 mark-to-market revaluation"})
        corrected = corr_resp.json()
        other_list = await client.get("/pricing/manual-valuations", params={"component_type": "other_asset"})
        other_ids = [i["id"] for i in other_list.json()["items"]]
        bad = await client.get("/pricing/manual-valuations?component_type=non_existent_type")
        assert (
            (create_resp.status_code, created["component_type"], created["liquidity_class"], created["value"], created["provenance"], created["source"], created["notes"], created["id"] is not None),
            (prop_list.status_code, any(i["id"] == created["id"] and i["value"] == "1250000.00" for i in prop_list.json()["items"])),
            (corr_resp.status_code, corrected["id"] != first_id, corrected["value"], corrected["notes"]),
            (other_list.status_code, other_list.json()["total"] >= 1, all(i["component_type"] == "other_asset" for i in other_list.json()["items"]), corrected["id"] in other_ids, first_id not in other_ids),
            bad.status_code,
        ) == ((201, "property_value", "illiquid", "1250000.00", "manual", "manual appraisal", "Real estate certified appraisal", True), (200, True), (201, True, "525000.00", "Q2 mark-to-market revaluation"), (200, True, True, True, True), 400)
