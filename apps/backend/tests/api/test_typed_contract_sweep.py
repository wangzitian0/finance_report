"""Typed backend contract sweep (#1074 → #1005/#1008/#1001).

One pass that gives every touched router a declared response/param contract:
- AC12.27 structured ``ErrorResponse`` shape across handlers + OpenAPI (#1005)
- AC4.12  reconciliation ``match_id``/``txn_id`` path params typed as ``UUID`` (#1008)
- AC5.33  ``GET /reports/{report_type}/snapshots`` typed list + enum param (#1008)
- AC17.31 portfolio ``PATCH``/``prices/update`` typed responses, no raw ``dict`` (#1008)
- AC16.35 Stage-2 batch endpoints typed + 409 on unresolved checks (#1001)
"""

from __future__ import annotations

from fastapi import HTTPException, status
from httpx import AsyncClient

from src.models.consistency_check import CheckStatus, CheckType, ConsistencyCheck
from src.routers import review as review_router
from src.schemas.review import BatchApproveRequest

# --- AC12.27: structured error contract (#1005) --------------------------------


async def test_AC12_27_1_http_error_has_structured_error_id(client: AsyncClient) -> None:
    """AC12.27.1: an HTTPException-derived 404 returns a structured body with a
    machine-readable ``error_id`` (not just free-text ``detail``)."""
    missing = "00000000-0000-0000-0000-000000000000"
    response = await client.post(f"/reconciliation/matches/{missing}/accept")

    assert response.status_code == status.HTTP_404_NOT_FOUND
    body = response.json()
    assert body["error_id"] == "not_found"
    assert isinstance(body["detail"], str) and body["detail"]
    assert "request_id" in body


async def test_AC12_27_2_openapi_declares_error_response_contract() -> None:
    """AC12.27.2: the shared ``ErrorResponse`` is declared in OpenAPI and referenced
    by the common 4xx responses, so the contract is visible to the generated client."""
    from src.main import app

    schema = app.openapi()
    assert "ErrorResponse" in schema["components"]["schemas"]
    props = schema["components"]["schemas"]["ErrorResponse"]["properties"]
    assert {"error_id", "detail", "request_id"} <= set(props)

    responses = schema["paths"]["/accounts"]["get"]["responses"]
    ref = responses["404"]["content"]["application/json"]["schema"]["$ref"]
    assert ref.endswith("/ErrorResponse")


# --- AC4.12: reconciliation UUID-typed path params (#1008) ----------------------


async def test_AC4_12_1_accept_match_malformed_uuid_returns_422(client: AsyncClient) -> None:
    """AC4.12.1: a non-UUID ``match_id`` is rejected with 422 at the boundary."""
    response = await client.post("/reconciliation/matches/not-a-uuid/accept")
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


async def test_AC4_12_2_create_entry_malformed_uuid_returns_422(client: AsyncClient) -> None:
    """AC4.12.2: a non-UUID ``txn_id`` is rejected with 422 at the boundary."""
    response = await client.post("/reconciliation/unmatched/not-a-uuid/create-entry")
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


# --- AC5.33: report snapshots typed contract (#1008) ----------------------------


async def test_AC5_33_1_report_snapshots_unknown_type_returns_422(client: AsyncClient) -> None:
    """AC5.33.1: an unknown ``report_type`` is rejected with 422 instead of
    silently returning an empty list."""
    response = await client.get("/reports/not-a-report-type/snapshots")
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


async def test_AC5_33_2_report_snapshots_valid_type_returns_typed_list(client: AsyncClient) -> None:
    """AC5.33.2: a valid ``report_type`` returns a (possibly empty) typed list."""
    response = await client.get("/reports/balance_sheet/snapshots")
    assert response.status_code == status.HTTP_200_OK
    assert isinstance(response.json(), list)


# --- AC17.31: portfolio typed responses (#1008) ---------------------------------


async def test_AC17_31_1_prices_update_returns_typed_batch_response(client: AsyncClient) -> None:
    """AC17.31.1: ``POST /portfolio/prices/update`` returns the typed
    ``{updated_count, results}`` shape, not an ad-hoc dict."""
    response = await client.post("/portfolio/prices/update", json={"updates": []})
    assert response.status_code == status.HTTP_200_OK
    body = response.json()
    assert body["updated_count"] == 0
    assert body["results"] == []


async def test_AC17_31_2_patch_unknown_holding_returns_404(client: AsyncClient) -> None:
    """AC17.31.2: ``PATCH /portfolio/{ticker}`` for an unknown holding returns a
    structured 404 (no raw ``dict`` success path)."""
    response = await client.patch("/portfolio/NOPE", json={"cost_basis_method": "FIFO"})
    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert response.json()["error_id"] == "not_found"


# --- AC16.35: Stage-2 batch typed contract (#1001) ------------------------------


async def test_AC16_35_1_batch_approve_empty_returns_typed_response(client: AsyncClient) -> None:
    """AC16.35.1: an empty batch approve returns the typed counters with no
    ``success`` field smuggled into the body."""
    response = await client.post("/statements/batch-approve-matches", json={"match_ids": []})
    assert response.status_code == status.HTTP_200_OK
    body = response.json()
    assert body == {
        "approved_count": 0,
        "journal_entries_created": 0,
        "journal_entries_reconciled": 0,
    }
    assert "success" not in body


async def test_AC16_35_2_batch_approve_blocked_returns_409(db, test_user) -> None:
    """AC16.35.2: unresolved consistency checks block batch approve with a 409
    structured error instead of a 200 body carrying ``{"success": false}``."""
    db.add(
        ConsistencyCheck(
            user_id=test_user.id,
            check_type=CheckType.DUPLICATE,
            status=CheckStatus.PENDING,
            related_txn_ids=["txn1"],
            details={"count": 1},
            severity="high",
        )
    )
    await db.commit()

    try:
        await review_router.batch_approve_matches(
            request=BatchApproveRequest(match_ids=[]),
            db=db,
            user_id=test_user.id,
        )
    except HTTPException as exc:
        assert exc.status_code == status.HTTP_409_CONFLICT
        assert "unresolved" in exc.detail
    else:  # pragma: no cover - defensive
        raise AssertionError("expected a 409 HTTPException")
