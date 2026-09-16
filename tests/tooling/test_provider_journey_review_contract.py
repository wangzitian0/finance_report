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


@pytest.mark.asyncio
async def test_provider_review_confirms_only_fixture_owned_envelope() -> None:
    """AC-testing.product-gates.13: missing source facts require explicit fixture evidence."""
    from common.testing.provider_review import FixtureEnvelope
    from datetime import date
    from decimal import Decimal

    class EnvelopeClient(_Client):
        async def post(self, path, json=None):
            if path.endswith("/review/approve") and not any(
                c[1].endswith("/review/envelope") for c in self.calls
            ):
                self.calls.append(("POST", path, json))
                return _Response(
                    400,
                    {
                        "detail": "Current source requires explicit human confirmation before posting"
                    },
                )
            if path.endswith("/review/envelope"):
                self.calls.append(("POST", path, json))
                return _Response(200, {"id": "envelope-1"})
            return await super().post(path, json)

        async def get(self, path):
            if path.endswith("/review"):
                return _Response(
                    200, {"source_result_digest": "a" * 64, "account_id": "bank-1"}
                )
            return await super().get(path)

    fixture = FixtureEnvelope(
        "SGD",
        date(2026, 1, 1),
        date(2026, 1, 31),
        Decimal("100"),
        Decimal("110"),
        "Generated original facts",
    )
    client = EnvelopeClient()
    result = await approve_statement_with_fixture_review(
        client,
        api_url=lambda p: "/api" + p,
        statement_id="statement-1",
        transactions=[],
        dispositions={
            "Synthetic refund": FixtureDisposition(
                "expense_refund", "EXPENSE", "Fixture refund"
            )
        },
        envelope=fixture,
    )
    command = next(c[2] for c in client.calls if c[1].endswith("/review/envelope"))
    assert command == {
        "source_result_digest": "a" * 64,
        "account_id": "bank-1",
        "currency": "SGD",
        "period_start": "2026-01-01",
        "period_end": "2026-01-31",
        "opening_balance": "100",
        "closing_balance": "110",
        "rationale": "Generated original facts",
    }
    assert result["reviewed_dispositions"] == 1
    with pytest.raises(AssertionError, match="fixture envelope"):
        await approve_statement_with_fixture_review(
            EnvelopeClient(),
            api_url=lambda p: "/api" + p,
            statement_id="statement-1",
            transactions=[],
            dispositions={},
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "digest,confirmation_status", [(None, 200), ("b" * 64, 400), ("b" * 64, 200)]
)
async def test_fixture_source_confirmation_fails_closed(
    digest, confirmation_status
) -> None:
    """AC-testing.product-gates.13: source confirmation needs a current digest and accepted command."""
    from datetime import date
    from decimal import Decimal

    from common.testing.provider_review import (
        FixtureEnvelope,
        _confirm_fixture_envelope,
    )

    class SourceClient(_Client):
        async def get(self, path):
            return _Response(200, {"source_result_digest": digest, "account_id": None})

        async def post(self, path, json=None):
            self.calls.append(("POST", path, json))
            if path == "/api/accounts":
                return _Response(201, {"id": "new-custody"})
            return _Response(
                confirmation_status, {"id": "envelope", "detail": "source mismatch"}
            )

    client = SourceClient()
    envelope = FixtureEnvelope(
        "SGD",
        date(2026, 1, 1),
        date(2026, 1, 31),
        Decimal("0"),
        Decimal("0"),
        "Generated source",
    )
    if digest is None or confirmation_status != 200:
        with pytest.raises(
            AssertionError, match="exact current extraction digest|confirmation failed"
        ):
            await _confirm_fixture_envelope(
                client, lambda p: "/api" + p, "statement-1", envelope
            )
        if digest is None:
            assert client.calls == []
    else:
        await _confirm_fixture_envelope(
            client, lambda p: "/api" + p, "statement-1", envelope
        )
        assert client.calls[0][2]["type"] == "ASSET"
        assert client.calls[1][2]["account_id"] == "new-custody"
