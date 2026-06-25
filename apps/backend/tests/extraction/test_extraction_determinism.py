"""Reproducibility regression for #989 — deterministic extraction scoring/routing.

Issue #989: "Statement extraction is non-deterministic — same PDF yields
different transactions / confidence / routing across uploads."

The AI vision model is not bit-reproducible and cannot be pinned in CI. What
*must* be deterministic is everything downstream of the model response: given
identical extracted model output, the ``confidence_score``, ``status`` (routing),
``validation_error``, and the resulting transaction set must be identical on every
parse. These tests pin that seam so a regression that re-introduces
non-determinism (dict/set iteration order, unstable tie-breaking, unseeded
randomness) in the scoring/routing pipeline fails CI.

Model-level reproducibility (the same PDF re-sent to the provider) is a separate
concern owned by the extraction-retry / temperature configuration, not this gate.

Covers AC13.13.1 / AC13.13.2 / AC13.13.3 (EPIC-013).
"""

from __future__ import annotations

import hashlib
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

import pytest

from src.models import BankStatementStatus
from src.services.extraction import ExtractionService
from src.services.validation import (
    compute_confidence_score,
    route_by_threshold,
    validate_balance_explicit,
)

# Number of repeated runs/parses used to surface non-determinism. Small enough to
# stay fast in CI, large enough that order-dependent flakiness shows up reliably.
RUNS = 8

# --- Fixed, deterministic model payloads (one per routing class) -----------------

# Bank statement whose opening + net transactions == closing (balance valid).
_BANK_VALID = {
    "institution": "DBS",
    "account_last4": "1234",
    "currency": "SGD",
    "period_start": "2024-01-01",
    "period_end": "2024-01-31",
    "opening_balance": "1000.00",
    "closing_balance": "1500.00",
    "transactions": [
        {
            "date": "2024-01-10",
            "description": "Salary Deposit",
            "amount": "800.00",
            "direction": "IN",
            "reference": "SAL001",
            "balance_after": "1800.00",
        },
        {
            "date": "2024-01-20",
            "description": "Rent Payment",
            "amount": "300.00",
            "direction": "OUT",
            "reference": "RENT01",
            "balance_after": "1500.00",
        },
    ],
}

# Same bank statement but the closing balance does not reconcile (balance invalid)
# -> must route to PARSED (review) on every parse (#1141: no longer a UPLOADED
# dead-end; it enters review with a validation_error like the brokerage path).
_BANK_BALANCE_INVALID = {
    **_BANK_VALID,
    "closing_balance": "9999.99",
}

# Brokerage payload (carries ``positions``) -> must route to PARSED on every parse.
_BROKERAGE = {
    "institution": "Futu",
    "account_last4": "5678",
    "currency": "USD",
    "period_start": "2024-01-01",
    "period_end": "2024-01-31",
    "opening_balance": "0.00",
    "closing_balance": "0.00",
    "positions": [
        {"symbol": "AAPL", "quantity": "10", "market_value": "1900.00"},
        {"symbol": "TSLA", "quantity": "5", "market_value": "1000.00"},
    ],
    "transactions": [],
}


def _txn_identity(t) -> tuple:
    """Full identity of one AtomicTransaction.

    AC13.13 is about the resulting transaction *set* being identical, so the
    fingerprint must cover every field that distinguishes one row from another —
    including ``dedup_hash`` (the system's own uniqueness key) and ``balance_after``.
    Fingerprinting only amount/description/direction would miss real drift where
    dates, references, currency, or the dedup key change while those three stay
    fixed (or where two distinct rows share amount+description+direction).
    """
    return (
        str(t.txn_date),
        str(t.amount),
        str(getattr(t, "direction", "")),
        t.description or "",
        t.reference or "",
        t.currency or "",
        str(t.balance_after) if t.balance_after is not None else "",
        t.dedup_hash,
    )


def _outcome_signature(statement, transactions) -> tuple:
    """Stable, comparable fingerprint of everything #989 says drifts across uploads."""
    txn_sig = tuple(sorted(_txn_identity(t) for t in transactions))
    return (
        statement.confidence_score,
        statement.status,
        statement.validation_error,
        txn_sig,
    )


class TestScoringRoutingDeterminism:
    """AC13.13.1: the pure scoring/routing functions are deterministic."""

    @pytest.mark.parametrize(
        "payload",
        [_BANK_VALID, _BANK_BALANCE_INVALID, _BROKERAGE],
        ids=["bank_valid", "bank_balance_invalid", "brokerage"],
    )
    def test_scoring_and_routing_are_deterministic(self, payload):
        opening = Decimal(payload["opening_balance"])
        closing = Decimal(payload["closing_balance"])
        net = sum(
            (Decimal(t["amount"]) if t["direction"] == "IN" else -Decimal(t["amount"])) for t in payload["transactions"]
        )

        results = []
        for _ in range(RUNS):
            balance = validate_balance_explicit(opening, closing, net)
            score = compute_confidence_score(payload, balance)
            status = route_by_threshold(score, balance["balance_valid"])
            results.append((score, status, balance["balance_valid"]))

        first = results[0]
        assert all(r == first for r in results), f"Non-deterministic scoring/routing across {RUNS} runs: {set(results)}"


@pytest.mark.usefixtures("db", "test_user")
class TestRepeatedParseDeterminism:
    """AC13.13.2 / AC13.13.3: re-parsing identical model output is reproducible."""

    async def _parse_once(self, db, user_id, payload, tag: str):
        """Parse a statement with ``payload`` as the (mocked) model response.

        Each call uses unique file bytes so the dedup layer treats it as a fresh
        upload — isolating *scoring/routing* determinism from upload dedup.
        """
        service = ExtractionService()
        content = f"PDF-{tag}".encode()
        file_hash = hashlib.sha256(content).hexdigest()
        with patch.object(service, "extract_financial_data", return_value=payload):
            statement, transactions = await service.parse_document(
                file_path=Path(f"{tag}.pdf"),
                institution=payload.get("institution"),
                user_id=user_id,
                file_content=content,
                file_hash=file_hash,
                original_filename=f"{tag}.pdf",
                db=db,
            )
        await db.commit()
        return statement, transactions

    async def test_repeated_parse_yields_identical_confidence_status_validation(self, db, test_user):
        """AC13.13.2: identical model output -> identical confidence/status/validation."""
        signatures = []
        for i in range(RUNS):
            statement, transactions = await self._parse_once(db, test_user.id, _BANK_VALID, f"repro-{i}")
            signatures.append(_outcome_signature(statement, transactions))

        first = signatures[0]
        assert all(sig == first for sig in signatures), (
            f"Same model output produced different outcomes across {RUNS} parses: {set(signatures)}"
        )
        # Guard against a vacuous pass: the valid bank statement must actually score.
        assert first[0] > 0

    @pytest.mark.parametrize(
        "payload,expected_status",
        [
            # AC20.9.2 (#1352) supersedes the #1141 "balance-invalid -> PARSED/review"
            # resting state: a bank statement whose chain does not reconcile is now a
            # BLOCKING-gate quarantine to REJECTED. Brokerage still rests in PARSED.
            (_BANK_BALANCE_INVALID, BankStatementStatus.REJECTED),
            (_BROKERAGE, BankStatementStatus.PARSED),
        ],
        ids=["bank_balance_invalid->rejected", "brokerage->parsed"],
    )
    async def test_routing_is_consistent_per_payload_class(self, db, test_user, payload, expected_status):
        """AC13.13.3 / AC13.21.5 / AC20.9.2: each payload class routes to one stable status across N parses.

        Post-#1352 a balance-invalid bank statement is deterministically quarantined
        to REJECTED on every parse (the LP blocking gate); a brokerage statement still
        rests in PARSED (it reconciles via Layer-2 positions, not a balance chain).
        """
        statuses = []
        for i in range(RUNS):
            statement, _ = await self._parse_once(db, test_user.id, payload, f"route-{expected_status.value}-{i}")
            statuses.append(statement.status)

        assert set(statuses) == {expected_status}, (
            f"Routing drifted across {RUNS} parses: {set(statuses)} (expected always {expected_status})"
        )

    async def test_AC20_9_2_balance_invalid_parse_is_quarantined(self, db, test_user):
        """AC20.9.2 (#1352, supersedes AC13.21.2): a balance-invalid bank parse is quarantined.

        The prior #1141 reviewable resting state (`PARSED` + `pending_review`) is gone:
        an extraction whose balance chain does not reconcile cannot persist as trusted
        truth, so it lands in the `REJECTED` terminal state with a typed reason code and
        is flagged balance-invalid.
        """
        from src.models.statement_enums import Stage1Status

        statement, _ = await self._parse_once(db, test_user.id, _BANK_BALANCE_INVALID, "ac20-9-2")

        assert statement.status == BankStatementStatus.REJECTED
        assert statement.status != BankStatementStatus.PARSED
        assert statement.stage1_status == Stage1Status.REJECTED
        assert statement.balance_validated is False
        assert statement.validation_error
        assert "lp_balance_chain_unreconciled" in statement.validation_error
