"""Contract tests for provider-backed economic-review journeys."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from common.testing.provider_review import (
    FixtureDisposition,
    approve_statement_with_fixture_review,
)


@dataclass
class _Response:
    status_code: int
    payload: dict

    @property
    def text(self) -> str:
        return str(self.payload)

    def json(self) -> dict:
        return self.payload


class _Client:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict | None]] = []
        self.approvals = 0

    async def get(self, path: str) -> _Response:
        self.calls.append(("GET", path, None))
        if path == "/api/reconciliation/unmatched?statement_id=statement-1":
            return _Response(
                200,
                {
                    "items": [
                        {
                            "id": "txn-1",
                            "description": "Synthetic refund",
                            "direction": "IN",
                            "currency": "SGD",
                        }
                    ],
                    "total": 1,
                },
            )
        raise AssertionError(f"Unexpected request: {path}")

    async def post(self, path: str, json: dict | None = None) -> _Response:
        self.calls.append(("POST", path, json))
        if path.endswith("/review/approve"):
            self.approvals += 1
            if self.approvals == 1:
                return _Response(
                    409,
                    {"detail": "Economic review required: intent_missing"},
                )
            return _Response(200, {"journal_entries_created": 0, "status": "approved"})
        if path == "/api/accounts":
            return _Response(201, {"id": "expense-account"})
        if path.endswith("/reviewed-disposition"):
            return _Response(200, {"id": "entry-1"})
        raise AssertionError(f"Unexpected request: {path}")


@pytest.mark.asyncio
async def test_AC_testing_product_gates_13_retries_after_reviewed_dispositions() -> (
    None
):
    """AC-testing.product-gates.13: explicit fixture semantics cross the review boundary."""
    client = _Client()
    outcome = await approve_statement_with_fixture_review(
        client,
        api_url=lambda path: f"/api{path}",
        statement_id="statement-1",
        transactions=[
            {
                "id": "txn-1",
                "description": "Synthetic refund",
                "direction": "IN",
                "currency": "SGD",
            }
        ],
        dispositions={
            "Synthetic refund": FixtureDisposition(
                intent="expense_refund",
                account_type="EXPENSE",
                category="REFUND",
                rationale="The generated fixture explicitly identifies an expense refund.",
            )
        },
    )

    assert outcome == {
        "status": "approved",
        "journal_entries_created": 0,
        "reviewed_dispositions": 1,
    }
    reviewed_call = next(
        call for call in client.calls if call[1].endswith("/reviewed-disposition")
    )
    assert reviewed_call[2] == {
        "intent": "expense_refund",
        "counter_account_id": "expense-account",
        "category": "REFUND",
        "rationale": "The generated fixture explicitly identifies an expense refund.",
    }
    assert (
        "GET",
        "/api/reconciliation/unmatched?statement_id=statement-1",
        None,
    ) in client.calls
    assert client.approvals == 2


@pytest.mark.asyncio
async def test_provider_review_adapter_preserves_direct_approval() -> None:
    client = _Client()
    client.approvals = 1

    outcome = await approve_statement_with_fixture_review(
        client,
        api_url=lambda path: f"/api{path}",
        statement_id="statement-1",
        transactions=[],
        dispositions={},
    )

    assert outcome == {
        "status": "approved",
        "journal_entries_created": 0,
        "reviewed_dispositions": 0,
    }
    assert all(method != "GET" for method, _path, _body in client.calls)


@pytest.mark.asyncio
async def test_provider_review_adapter_rejects_non_review_failures() -> None:
    class NonReviewClient(_Client):
        async def post(self, path: str, json: dict | None = None) -> _Response:
            return _Response(503, {"detail": "provider unavailable"})

    with pytest.raises(AssertionError, match="outside the review boundary"):
        await approve_statement_with_fixture_review(
            NonReviewClient(),
            api_url=lambda path: f"/api{path}",
            statement_id="statement-1",
            transactions=[],
            dispositions={},
        )


@pytest.mark.asyncio
async def test_provider_review_adapter_fails_closed_without_fixture_semantics() -> None:
    with pytest.raises(AssertionError, match="no explicit disposition"):
        await approve_statement_with_fixture_review(
            _Client(),
            api_url=lambda path: f"/api{path}",
            statement_id="statement-1",
            transactions=[],
            dispositions={},
        )


@pytest.mark.asyncio
async def test_provider_review_adapter_fails_closed_when_scoped_queue_is_unavailable() -> (
    None
):
    class QueueFailureClient(_Client):
        async def get(self, path: str) -> _Response:
            return _Response(503, {"detail": "queue unavailable"})

    with pytest.raises(
        AssertionError, match="statement-scoped unmatched lookup failed"
    ):
        await approve_statement_with_fixture_review(
            QueueFailureClient(),
            api_url=lambda path: f"/api{path}",
            statement_id="statement-1",
            transactions=[],
            dispositions={},
        )


@pytest.mark.asyncio
async def test_provider_review_adapter_reuses_account_and_omits_empty_category() -> (
    None
):
    class TwoTransactionClient(_Client):
        async def get(self, path: str) -> _Response:
            self.calls.append(("GET", path, None))
            return _Response(
                200,
                {
                    "items": [
                        {
                            "id": "txn-1",
                            "description": "Synthetic refund",
                            "currency": "SGD",
                        },
                        {
                            "id": "txn-2",
                            "description": "Synthetic rent",
                            "currency": "SGD",
                        },
                    ],
                    "total": 2,
                },
            )

    client = TwoTransactionClient()
    outcome = await approve_statement_with_fixture_review(
        client,
        api_url=lambda path: f"/api{path}",
        statement_id="statement-1",
        transactions=[],
        dispositions={
            "Synthetic refund": FixtureDisposition(
                "expense_refund", "EXPENSE", "Fixture-owned refund.", "REFUND"
            ),
            "Synthetic rent": FixtureDisposition(
                "expense", "EXPENSE", "Fixture-owned rent."
            ),
        },
    )

    assert outcome["reviewed_dispositions"] == 2
    assert sum(path == "/api/accounts" for _method, path, _body in client.calls) == 1
    reviewed_payloads = [
        body
        for _method, path, body in client.calls
        if path.endswith("/reviewed-disposition")
    ]
    assert reviewed_payloads[1] == {
        "intent": "expense",
        "counter_account_id": "expense-account",
        "rationale": "Fixture-owned rent.",
    }
