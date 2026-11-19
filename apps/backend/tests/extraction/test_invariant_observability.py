from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest

from src.extraction import DocumentSource
from src.extraction.base.validation import count_within_document_dedup_collapse
from src.extraction.extension.service import ExtractionService
from src.observability import telemetry_metrics

pytestmark = pytest.mark.no_db


class _FakeCounter:
    def __init__(self) -> None:
        self.add_calls: list[tuple[int, dict[str, str]]] = []

    def add(self, value: int, attributes: dict[str, str]) -> None:
        self.add_calls.append((value, attributes))


def test_AC26_8_1_dedup_collapse_and_invariant_recorder(monkeypatch) -> None:
    assert [
        count_within_document_dedup_collapse(c)
        for c in (
            [],
            ["a", "b", "c"],
            ["a", "a", "b"],
            ["a", "a", "a"],
            ["a", "a", "b", "b", "c"],
            [f"hash-{i}" for i in range(25)],
        )
    ] == [0, 0, 1, 2, 2, 0]

    counter = _FakeCounter()
    monkeypatch.setitem(telemetry_metrics._instruments, "financial_invariant_violation", counter)
    telemetry_metrics.record_financial_invariant_violation(kind="balance_mismatch", institution_class="bank")
    telemetry_metrics.record_financial_invariant_violation(
        kind="dedup_within_doc_collapse", institution_class="brokerage"
    )
    assert counter.add_calls == [
        (1, {"kind": "balance_mismatch", "institution_class": "bank"}),
        (1, {"kind": "dedup_within_doc_collapse", "institution_class": "brokerage"}),
    ]
    assert all(
        k in telemetry_metrics.INVARIANT_VIOLATION_KINDS
        for k in ("balance_mismatch", "per_currency_nav", "chain_break", "dedup_within_doc_collapse")
    )

    counter.add_calls.clear()
    telemetry_metrics.record_financial_invariant_violation(kind="totally_bogus_kind")
    assert counter.add_calls == []
    telemetry_metrics.record_financial_invariant_violation(
        kind="balance_mismatch", institution_class="DBS Bank Account 1234"
    )
    assert counter.add_calls == [(1, {"kind": "balance_mismatch", "institution_class": "unknown"})]

    monkeypatch.delitem(telemetry_metrics._instruments, "financial_invariant_violation", raising=False)
    telemetry_metrics.record_financial_invariant_violation(kind="chain_break")


async def test_AC26_8_1_balance_invalid_parse_quarantines_and_emits_metric(monkeypatch) -> None:
    service = ExtractionService()
    payload = {
        "institution": "DBS",
        "currency": "SGD",
        "period_start": "2025-01-01",
        "period_end": "2025-01-31",
        "opening_balance": "100.00",
        "closing_balance": "999.99",
        "transactions": [{"date": "2025-01-05", "amount": "50.00", "direction": "IN", "description": "Deposit"}],
    }

    async def fake_retry(**_kwargs):
        return payload

    recorded: list[tuple[str, str]] = []
    monkeypatch.setattr(service, "extract_financial_data", fake_retry)
    monkeypatch.setattr(
        "src.extraction.extension.service.record_financial_invariant_violation",
        lambda *, kind, institution_class="unknown": recorded.append((kind, institution_class)),
    )
    result = await service.parse_document(
        DocumentSource.resolve(path=Path("dbs.pdf"), content=b"fake pdf"),
        institution="DBS",
        user_id=uuid4(),
        file_type="pdf",
        account_id=uuid4(),
        db=None,
    )
    assert (
        result.balance_validated is False
        and bool(result.review_reasons)
        and len(result.transactions) == 0
        and {("balance_mismatch", "bank"), ("llm_led_gate_quarantine_balance", "bank")} <= set(recorded)
    )
