"""Financial-invariant observability (EPIC-026 AC26.8.1).

Detection + structured metrics for financial-invariant violations, with NO change
to statement routing/status/approval. Covers:

- the within-document dedup-collapse conservation property (#1254 class),
- the structured-metric recorder for invariant violations, and
- a parse-path behavior test proving a balance-invalid bank statement still routes
  to PARSED/review (unchanged) while the metric fires.
"""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest

from src.extraction.base.validation import count_within_document_dedup_collapse
from src.extraction.extension.service import ExtractionService
from src.models.statement_enums import BankStatementStatus
from src.observability import telemetry_metrics

pytestmark = pytest.mark.no_db


# ---------------------------------------------------------------------------
# Within-document dedup-collapse conservation property (#1254 class)
# ---------------------------------------------------------------------------


def test_AC26_8_1_within_document_collapse_counts_only_duplicate_hashes() -> None:
    """AC26.8.1: collapse count == extracted rows − distinct hashes for one parse.

    The detector is a pure conservation invariant over a single parse's hashes:
    every duplicate hash beyond the first is one silently-absorbed row.
    """
    assert count_within_document_dedup_collapse([]) == 0
    # All distinct -> no collapse.
    assert count_within_document_dedup_collapse(["a", "b", "c"]) == 0
    # One pair collides within the parse -> exactly one collapsed row.
    assert count_within_document_dedup_collapse(["a", "a", "b"]) == 1
    # Three identical -> two extra rows absorbed.
    assert count_within_document_dedup_collapse(["a", "a", "a"]) == 2
    # Multiple independent collisions add up.
    assert count_within_document_dedup_collapse(["a", "a", "b", "b", "c"]) == 2


def test_AC26_8_1_collapse_never_over_reports_cross_document_dedup() -> None:
    """AC26.8.1: the signal is scoped to ONE parse, so legit cross-doc dedup is invisible.

    A re-uploaded statement reproduces the *same* hashes, but those collapse against
    already-persisted rows in the DB upsert — never counted here. Within a single
    parse, distinct genuine rows carry distinct hashes (the occurrence_index keeps
    #1254's same-balance repeats apart), so the conservation count is 0.
    """
    # Distinct hashes for genuinely-distinct rows in one parse: no false positive.
    distinct_for_one_parse = [f"hash-{i}" for i in range(25)]
    assert count_within_document_dedup_collapse(distinct_for_one_parse) == 0


# ---------------------------------------------------------------------------
# Structured-metric recorder
# ---------------------------------------------------------------------------


class _FakeCounter:
    def __init__(self) -> None:
        self.add_calls: list[tuple[int, dict[str, str]]] = []

    def add(self, value: int, attributes: dict[str, str]) -> None:
        self.add_calls.append((value, attributes))


def test_AC26_8_1_invariant_violation_recorder_emits_labelled_counter(monkeypatch) -> None:
    """AC26.8.1: each violation kind emits a queryable counter with anonymized labels."""
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
    # The labelled kinds are part of the closed, low-cardinality vocabulary.
    for kind in ("balance_mismatch", "per_currency_nav", "chain_break", "dedup_within_doc_collapse"):
        assert kind in telemetry_metrics.INVARIANT_VIOLATION_KINDS


def test_AC26_8_1_recorder_guards_label_cardinality_and_pii(monkeypatch) -> None:
    """AC26.8.1: an unknown kind is dropped and a stray institution_class is coerced.

    The metric label space must stay bounded and PII-free: a typo'd kind is a no-op
    (no label emitted), and anything outside the closed institution-class set
    becomes ``"unknown"`` so a real institution name can never become a label.
    """
    counter = _FakeCounter()
    monkeypatch.setitem(telemetry_metrics._instruments, "financial_invariant_violation", counter)

    # Unknown kind -> dropped, nothing emitted.
    telemetry_metrics.record_financial_invariant_violation(kind="totally_bogus_kind")
    assert counter.add_calls == []

    # A leaked real institution name is coerced to the anonymized "unknown" bucket.
    telemetry_metrics.record_financial_invariant_violation(
        kind="balance_mismatch", institution_class="DBS Bank Account 1234"
    )
    assert counter.add_calls == [(1, {"kind": "balance_mismatch", "institution_class": "unknown"})]


def test_AC26_8_1_recorder_is_safe_noop_without_instrument(monkeypatch) -> None:
    """AC26.8.1: recording is a safe no-op when metrics export is not configured."""
    # monkeypatch.delitem restores the dict afterward, so removing the instrument
    # cannot leak into other tests (no order-dependent failures).
    monkeypatch.delitem(telemetry_metrics._instruments, "financial_invariant_violation", raising=False)
    # Must not raise when the instrument is absent (export disabled).
    telemetry_metrics.record_financial_invariant_violation(kind="chain_break")


# ---------------------------------------------------------------------------
# Parse-path behavior: routing/status UNCHANGED + metric fires
# ---------------------------------------------------------------------------


async def test_AC26_8_1_balance_invalid_parse_quarantines_and_emits_metric(monkeypatch) -> None:
    """AC26.8.1 (+AC20.9.2 #1352): a balance-invalid bank parse emits the detection metric.

    The AC26.8.1 detection counter (`balance_mismatch`) still fires at detection time.
    Since #1352 the routing is no longer "PARSED/review": the LLM-LED blocking gate quarantines
    the extraction to REJECTED (AC20.9.2). The detection observability and the blocking
    gate are independent — this asserts both: the metric fires AND the status is REJECTED.
    """
    service = ExtractionService()

    # A bank statement whose opening + ΣIN − ΣOUT does NOT equal closing.
    balance_invalid = {
        "institution": "DBS",
        "currency": "SGD",
        "period_start": "2025-01-01",
        "period_end": "2025-01-31",
        "opening_balance": "100.00",
        "closing_balance": "999.99",  # does not reconcile with the single +50 txn
        "transactions": [
            {"date": "2025-01-05", "amount": "50.00", "direction": "IN", "description": "Deposit"},
        ],
    }

    async def fake_retry(**_kwargs):
        return balance_invalid

    monkeypatch.setattr(service, "_extract_with_balance_retry", fake_retry)

    recorded: list[tuple[str, str]] = []

    def capture(*, kind: str, institution_class: str = "unknown") -> None:
        recorded.append((kind, institution_class))

    # Patch the symbol imported into the extraction service module.
    monkeypatch.setattr("src.extraction.extension.service.record_financial_invariant_violation", capture)

    statement, transactions = await service.parse_document(
        file_path=Path("dbs.pdf"),
        institution="DBS",
        user_id=uuid4(),
        file_type="pdf",
        account_id=uuid4(),
        file_content=b"fake pdf",
        db=None,  # no persistence; we only assert routing + metric
    )

    # BLOCKING (AC20.9.2): balance-invalid bank statement -> REJECTED quarantine.
    assert statement.status == BankStatementStatus.REJECTED
    assert statement.balance_validated is False
    assert statement.validation_error is not None
    assert len(transactions) == 1

    # Detection (AC26.8.1) still fires: the balance-mismatch counter is queryable,
    # and the blocking gate adds its own distinct quarantine counter (AC20.9.7).
    assert ("balance_mismatch", "bank") in recorded
    assert ("llm_led_gate_quarantine_balance", "bank") in recorded
