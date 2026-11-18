from __future__ import annotations

from typing import Any

import pytest
from fastapi import status
from httpx import AsyncClient


async def test_AC12_27_1_http_error_has_structured_error_id(client: AsyncClient) -> None:
    resp = await client.patch("/reconciliation/matches/00000000-0000-0000-0000-000000000000", json={"action": "accept"})
    body = resp.json()
    assert resp.status_code == status.HTTP_404_NOT_FOUND and body["error_id"] == "not_found"
    assert isinstance(body["detail"], str) and body["detail"] and body["request_id"] == resp.headers["X-Request-ID"]


async def test_AC12_27_2_openapi_declares_error_response_contract(openapi_schema: dict[str, Any]) -> None:
    assert "ErrorResponse" in openapi_schema["components"]["schemas"]
    assert {"error_id", "detail", "request_id"} <= set(
        openapi_schema["components"]["schemas"]["ErrorResponse"]["properties"]
    )
    assert openapi_schema["paths"]["/accounts"]["get"]["responses"]["404"]["content"]["application/json"]["schema"][
        "$ref"
    ].endswith("/ErrorResponse")


@pytest.mark.parametrize(
    ("method", "url", "payload", "expected_status", "expected_body"),
    [
        (
            "PATCH",
            "/reconciliation/matches/not-a-uuid",
            {"action": "accept"},
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            None,
        ),
        (
            "POST",
            "/reconciliation/unmatched/not-a-uuid/reviewed-dispositions",
            {
                "intent": "expense",
                "counter_account_id": "00000000-0000-0000-0000-000000000001",
                "category": "DINING",
                "rationale": "Reviewed.",
            },
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            None,
        ),
        ("POST", "/pricing/price-overrides", {"updates": []}, status.HTTP_200_OK, {"updated_count": 0, "results": []}),
        (
            "PATCH",
            "/portfolio/NOPE",
            {"cost_basis_method": "FIFO"},
            status.HTTP_404_NOT_FOUND,
            {"error_id": "not_found"},
        ),
        (
            "POST",
            "/reconciliation/matches",
            {"action": "accept", "match_ids": []},
            status.HTTP_200_OK,
            {"approved_count": 0, "rejected_count": 0, "journal_entries_reconciled": 0},
        ),
    ],
)
async def test_AC4_12_AC16_35_AC17_31_typed_contract_routes(
    client: AsyncClient, method, url, payload, expected_status, expected_body
) -> None:
    resp = await client.request(method, url, json=payload)
    assert resp.status_code == expected_status
    if expected_body is not None:
        body = resp.json()
        assert all(body[k] == v for k, v in expected_body.items()) and "success" not in body
