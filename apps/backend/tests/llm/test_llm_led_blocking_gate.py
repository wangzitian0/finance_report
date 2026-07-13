"""LLM-LED tier blocking invariant gate (EPIC-020 AC-extraction.2009.2-.7, #1352).

EPIC-020 AC20.9.1 locks the ``event → L2`` layer to the **LLM-LED** tier: code may
reject the LLM's extraction, never author it. These tests prove the balance-chain
and within-document dedup-conservation invariants are now **blocking runtime gates**
— an internally-inconsistent extraction is quarantined to the ``rejected`` terminal
state and cannot persist as trusted financial truth — rather than the prior
"detector that only logged + routed to parsed/review" behavior (#1141).

The gate decision is a pure function (no LLM, no DB); the parse-path wiring is
exercised through ``ExtractionService.parse_document`` with the LLM mocked, asserting
the resulting statement status / reason. AC-extraction.2009.2's trusted-output absence is proven
against the ``report_readiness`` trusted-input predicate, which already excludes
``rejected``.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from sqlalchemy import select

from src.extraction.extension._llm_led_gate import (
    LlmLedQuarantineReason,
    evaluate_llm_led_extraction_gate,
)
from src.extraction.extension.service import ExtractionService
from src.extraction.orm.layer2 import AtomicTransaction
from src.extraction.orm.statement_enums import BankStatementStatus, Stage1Status
from src.extraction.orm.statement_summary import StatementSummary


@pytest.fixture
def service() -> ExtractionService:
    return ExtractionService()


def _bank_payload(*, opening: str, closing: str, txns: list[dict]) -> dict:
    return {
        "institution": "UOB",
        "account_last4": "6789",
        "currency": "SGD",
        "period_start": "2025-01-01",
        "period_end": "2025-01-31",
        "opening_balance": opening,
        "closing_balance": closing,
        "transactions": txns,
    }


async def _parse(service: ExtractionService, tmp_path, payload: dict):
    pdf = tmp_path / "stmt.pdf"
    pdf.write_bytes(b"dummy")
    with patch.object(service, "extract_financial_data", new=AsyncMock(return_value=payload)):
        return await service.parse_document(pdf, institution="UOB", user_id=uuid4(), file_content=pdf.read_bytes())


# --- AC-extraction.2009.2: balance-chain failure is a blocking gate ---------------------------


class TestBalanceChainBlockingGate:
    async def test_AC20_9_2_imbalanced_bank_extraction_is_quarantined_not_parsed(self, service, tmp_path):
        """[AC-extraction.2009.2] A bank statement whose chain does not reconcile is REJECTED."""
        # opening 1000, one IN of 100 => chain closing should be 1100; emit 9999 (>> tolerance).
        payload = _bank_payload(
            opening="1000.00",
            closing="9999.00",
            txns=[{"date": "2025-01-15", "description": "Salary", "amount": "100.00", "direction": "IN"}],
        )
        stmt, _events = await _parse(service, tmp_path, payload)

        assert stmt.status == BankStatementStatus.REJECTED
        assert stmt.status != BankStatementStatus.PARSED
        assert stmt.balance_validated is False
        # Terminal stage1 marker, not pending review.
        assert stmt.stage1_status == Stage1Status.REJECTED
        assert LlmLedQuarantineReason.BALANCE_CHAIN_UNRECONCILED.value in (stmt.validation_error or "")

    async def test_AC20_9_2_quarantined_extraction_absent_from_trusted_report_input(self, service, tmp_path):
        """[AC-extraction.2009.2] The quarantine status is excluded from trusted report input.

        report_readiness counts only PARSED/APPROVED statements as report input;
        REJECTED is a 'failed_parsing' blocker. Proving the quarantine status is
        REJECTED therefore proves it never reaches trusted report/query output.
        """
        payload = _bank_payload(
            opening="500.00",
            closing="100000.00",
            txns=[{"date": "2025-01-10", "description": "Fee", "amount": "5.00", "direction": "OUT"}],
        )
        stmt, _events = await _parse(service, tmp_path, payload)

        trusted_input_statuses = {BankStatementStatus.PARSED, BankStatementStatus.APPROVED}
        assert stmt.status not in trusted_input_statuses
        assert stmt.status == BankStatementStatus.REJECTED


# --- AC-extraction.2009.3: independent dedup gate, distinct reason -----------------------------


class TestDedupConservationBlockingGate:
    async def test_AC20_9_3_within_doc_dedup_collapse_is_quarantined(self, service, tmp_path):
        """[AC-extraction.2009.3] A within-document dedup collapse quarantines the extraction.

        Two genuinely-distinct rows that hash identically within one parse are the
        #1254 silent-row-loss shape, detected by ``count_within_document_dedup_collapse``.
        The per-document occurrence_index disambiguator (the #1254 *fix*) means a clean
        payload no longer collapses, so to exercise the BLOCKING gate independently of
        the balance chain we simulate the detector firing (a residual collapse slipping
        past the disambiguator). The balance chain here reconciles, so dedup is the only
        failing invariant — proving it is an independent gate with its own reason code.
        """
        # Balanced chain: opening 0 + 50 + 60 = 110 => reconciles cleanly.
        payload = _bank_payload(
            opening="0.00",
            closing="110.00",
            txns=[
                {"date": "2025-01-05", "description": "DEP A", "amount": "50.00", "direction": "IN"},
                {"date": "2025-01-06", "description": "DEP B", "amount": "60.00", "direction": "IN"},
            ],
        )
        pdf = tmp_path / "stmt.pdf"
        pdf.write_bytes(b"dummy")
        with (
            patch.object(service, "extract_financial_data", new=AsyncMock(return_value=payload)),
            patch(
                "src.extraction.extension.service.count_within_document_dedup_collapse",
                return_value=1,
            ),
        ):
            stmt, _events = await service.parse_document(
                pdf, institution="UOB", user_id=uuid4(), file_content=pdf.read_bytes()
            )

        assert stmt.status == BankStatementStatus.REJECTED
        assert LlmLedQuarantineReason.DEDUP_CONSERVATION_VIOLATION.value in (stmt.validation_error or "")

    def test_AC20_9_3_dedup_reason_code_distinct_from_balance(self):
        """[AC-extraction.2009.3] The dedup reason code is DISTINCT from the balance reason code."""
        dedup = evaluate_llm_led_extraction_gate(
            is_brokerage=False, balance_evaluable=True, balance_valid=True, within_doc_collapse=1
        )
        balance = evaluate_llm_led_extraction_gate(
            is_brokerage=False, balance_evaluable=True, balance_valid=False, within_doc_collapse=0
        )
        assert dedup.reason == LlmLedQuarantineReason.DEDUP_CONSERVATION_VIOLATION
        assert balance.reason == LlmLedQuarantineReason.BALANCE_CHAIN_UNRECONCILED
        assert dedup.reason != balance.reason


# --- AC-extraction.2009.4: fail-closed when the invariant cannot be evaluated ------------------


class TestFailClosedGate:
    async def test_AC20_9_4_unevaluable_balance_fails_closed_not_parsed(self, service, tmp_path):
        """[AC-extraction.2009.4] A bank statement missing a closing balance never reaches parsed.

        Fail-closed: a bank statement that lacks a closing balance cannot have its
        balance invariant evaluated. The parse path refuses it (a hard parse error)
        rather than substituting a zero-default that would silently 'pass' the chain
        — it never lands in PARSED/trusted state. The typed-reason quarantine for the
        unevaluable case is asserted directly on the pure gate below.
        """
        from src.extraction.extension.service import ExtractionError

        payload = _bank_payload(
            opening="1000.00",
            closing="",
            txns=[{"date": "2025-01-15", "description": "Salary", "amount": "100.00", "direction": "IN"}],
        )
        payload.pop("closing_balance")  # truly absent closing balance
        with pytest.raises(ExtractionError):
            await _parse(service, tmp_path, payload)

    def test_AC20_9_4_unevaluable_is_pure_gate_decision(self):
        """[AC-extraction.2009.4] The pure gate quarantines on balance_evaluable=False (bank)."""
        verdict = evaluate_llm_led_extraction_gate(
            is_brokerage=False, balance_evaluable=False, balance_valid=False, within_doc_collapse=0
        )
        assert verdict.quarantined is True
        assert verdict.reason == LlmLedQuarantineReason.BALANCE_INVARIANT_UNEVALUABLE


# --- AC-extraction.2009.5: the old "imbalanced -> parsed/review" path is gone ------------------


class TestOldPathRemoved:
    async def test_AC20_9_5_imbalanced_no_longer_routes_to_parsed_review(self, service, tmp_path):
        """[AC-extraction.2009.5] Regression: a true balance-chain failure no longer yields PARSED."""
        payload = _bank_payload(
            opening="2000.00",
            closing="500.00",  # chain would require -1500 net; only +200 emitted
            txns=[{"date": "2025-01-20", "description": "Refund", "amount": "200.00", "direction": "IN"}],
        )
        stmt, _events = await _parse(service, tmp_path, payload)

        # The pre-#1352 behavior was PARSED + pending_review; that must be gone.
        assert stmt.status is not BankStatementStatus.PARSED
        assert stmt.stage1_status is not Stage1Status.PENDING_REVIEW


# --- AC-extraction.2009.6: no false reject of a valid extraction ------------------------------


class TestNoFalseReject:
    async def test_AC20_9_6_valid_extraction_passes_gate_unchanged(self, service, tmp_path):
        """[AC-extraction.2009.6] A balanced, dedup-consistent bank statement is NOT quarantined."""
        payload = _bank_payload(
            opening="1000.00",
            closing="1100.00",
            txns=[{"date": "2025-01-15", "description": "Salary", "amount": "100.00", "direction": "IN"}],
        )
        stmt, _events = await _parse(service, tmp_path, payload)

        assert stmt.status != BankStatementStatus.REJECTED
        assert stmt.status in {BankStatementStatus.PARSED, BankStatementStatus.APPROVED, BankStatementStatus.UPLOADED}
        assert stmt.balance_validated is True

    def test_AC20_9_6_valid_pure_gate_passes(self):
        """[AC-extraction.2009.6] The pure gate passes a valid, evaluable, conserved extraction."""
        verdict = evaluate_llm_led_extraction_gate(
            is_brokerage=False, balance_evaluable=True, balance_valid=True, within_doc_collapse=0
        )
        assert verdict.quarantined is False
        assert verdict.reason is None

    def test_AC20_9_6_brokerage_balance_not_gated(self):
        """[AC-extraction.2009.6] Brokerage payloads are exempt from the balance gate (#981)."""
        verdict = evaluate_llm_led_extraction_gate(
            is_brokerage=True, balance_evaluable=False, balance_valid=False, within_doc_collapse=0
        )
        assert verdict.quarantined is False

    def test_AC20_9_6_inferred_csv_marker_exempt_from_balance_gate(self):
        """[AC-extraction.2009.6] An explicitly-flagged inferred-CSV review marker is not a false reject.

        The CSV-without-source-balances path (AC-extraction.2.5) is a known-incomplete review
        marker, not a true balance mismatch, so the balance gate exempts it — but the
        dedup gate still applies.
        """
        passes = evaluate_llm_led_extraction_gate(
            is_brokerage=False,
            balance_evaluable=True,
            balance_valid=False,
            within_doc_collapse=0,
            balance_gate_exempt=True,
        )
        assert passes.quarantined is False
        # The dedup gate is NOT exempted.
        dedup = evaluate_llm_led_extraction_gate(
            is_brokerage=False,
            balance_evaluable=True,
            balance_valid=False,
            within_doc_collapse=1,
            balance_gate_exempt=True,
        )
        assert dedup.reason == LlmLedQuarantineReason.DEDUP_CONSERVATION_VIOLATION


# --- AC-extraction.2009.7: distinct observable reason + metric, no PII -------------------------


class TestObservability:
    def test_AC20_9_7_each_failure_mode_has_distinct_reason_and_metric(self):
        """[AC-extraction.2009.7] Each failure mode maps to a distinct reason code AND metric kind."""
        from src.observability import INVARIANT_VIOLATION_KINDS

        verdicts = [
            evaluate_llm_led_extraction_gate(
                is_brokerage=False, balance_evaluable=True, balance_valid=False, within_doc_collapse=0
            ),
            evaluate_llm_led_extraction_gate(
                is_brokerage=False, balance_evaluable=True, balance_valid=True, within_doc_collapse=2
            ),
            evaluate_llm_led_extraction_gate(
                is_brokerage=False, balance_evaluable=False, balance_valid=True, within_doc_collapse=0
            ),
        ]
        reasons = {v.reason for v in verdicts}
        metrics = {v.metric_kind for v in verdicts}
        assert len(reasons) == 3, "each failure mode must have a distinct reason code"
        assert len(metrics) == 3, "each failure mode must have a distinct metric kind"
        # Each metric kind must be registered in the bounded telemetry vocabulary.
        for metric in metrics:
            assert metric in INVARIANT_VIOLATION_KINDS

    def test_AC20_9_7_gate_reason_codes_carry_no_pii(self):
        """[AC-extraction.2009.7] Reason codes / messages carry no institution name or account id."""
        forbidden = ("UOB", "6789", "SGD", "DBS")
        for reason in LlmLedQuarantineReason:
            verdict = evaluate_llm_led_extraction_gate(
                is_brokerage=False,
                balance_evaluable=(reason is not LlmLedQuarantineReason.BALANCE_INVARIANT_UNEVALUABLE),
                balance_valid=(reason is not LlmLedQuarantineReason.BALANCE_CHAIN_UNRECONCILED),
                within_doc_collapse=(1 if reason is LlmLedQuarantineReason.DEDUP_CONSERVATION_VIOLATION else 0),
            )
            blob = f"{verdict.reason.value} {verdict.message} {verdict.metric_kind}"
            for token in forbidden:
                assert token not in blob


# --- AC20.9.8: quarantine persists the terminal status (no stuck "parsing") -------


class TestQuarantinePersistsStatus:
    async def test_AC20_9_8_quarantined_statement_persists_rejected_not_stuck_parsing(
        self, service, tmp_path, db, test_user
    ):
        """AC-extraction.2009.8: [AC20.9.8] A db-backed quarantine writes status=rejected to the row (#1452).

        The chain-break / LLM-LED quarantine path previously skipped the
        persistence write entirely, so the pre-created upload row stayed in
        `parsing` forever even though the reject verdict was computed. The
        envelope must now persist as REJECTED while still writing no Layer-2
        financial rows.
        """
        file_hash = "qa1452" + uuid4().hex
        envelope = StatementSummary(
            user_id=test_user.id,
            file_hash=file_hash,
            institution="UOB",
            currency="SGD",
            status=BankStatementStatus.PARSING,
        )
        db.add(envelope)
        await db.flush()
        envelope_id = envelope.id

        payload = _bank_payload(
            opening="1000.00",
            closing="9999.00",
            txns=[{"date": "2025-01-15", "description": "Salary", "amount": "100.00", "direction": "IN"}],
        )
        pdf = tmp_path / "stmt.pdf"
        pdf.write_bytes(b"dummy")
        with patch.object(service, "extract_financial_data", new=AsyncMock(return_value=payload)):
            await service.parse_document(
                pdf,
                institution="UOB",
                user_id=test_user.id,
                file_content=pdf.read_bytes(),
                file_hash=file_hash,
                db=db,
            )
        await db.commit()

        persisted = await db.get(StatementSummary, envelope_id)
        assert persisted.status == BankStatementStatus.REJECTED
        # A quarantined extraction must not persist any Layer-2 financial rows.
        txns = (
            (await db.execute(select(AtomicTransaction).where(AtomicTransaction.user_id == test_user.id)))
            .scalars()
            .all()
        )
        assert txns == []
