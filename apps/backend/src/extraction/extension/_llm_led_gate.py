"""LLM-LED tier (event→L2) blocking invariant gate (EPIC-020 AC-extraction.2009.2-.7, #1352).

EPIC-020 AC20.9.1 locks the ``event → L2`` layer to the **LLM-LED** tier: the LLM
emits the parsed statement and deterministic CODE does enum + balance/dedup sanity
and **may reject, never author**. Before #1352 the balance-chain and within-document
dedup-conservation checks were mere *detectors* — an internally-inconsistent
extraction still routed to ``parsed``/review and persisted as reviewable financial
truth (per #1141). This module turns those two invariants into a **blocking runtime
gate**: when a deterministic invariant fails, the extraction is quarantined to the
existing ``rejected`` terminal state (already excluded from trusted report input by
``report_readiness``) carrying a typed reason code, and its Layer-2 rows are NOT
written. The gate disposes; the LLM only proposes.

The decision is a pure function over already-computed signals so it is exhaustively
unit-testable without an LLM or a DB. It reuses the promotion gate
(:func:`evaluate_promotion`) as the single deterministic trust boundary (#930): a
failed :class:`InvariantResult` is a ``REJECTED`` verdict regardless of confidence.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from src.services.promotion_gate import (
    STATEMENT_BALANCE_TOLERANCE,
    InvariantResult,
    PromotionDecision,
    evaluate_promotion,
)


class LlmLedQuarantineReason(str, Enum):
    """Typed, queryable reason an LLM-LED extraction was quarantined.

    Each value is a distinct reason code (AC-extraction.2009.7) carrying NO institution name or
    account identifier (PII-free) — only the invariant class that failed.
    """

    BALANCE_CHAIN_UNRECONCILED = "llm_led_balance_chain_unreconciled"
    DEDUP_CONSERVATION_VIOLATION = "llm_led_dedup_conservation_violation"
    BALANCE_INVARIANT_UNEVALUABLE = "llm_led_balance_invariant_unevaluable"


# Map each quarantine reason to its distinct, bounded metric kind (AC-extraction.2009.7). These
# are the *blocking-gate* counters, deliberately distinct from the pre-existing
# detection-only kinds ("balance_mismatch", "chain_break", "dedup_within_doc_collapse")
# so a quarantine (truth blocked) is queryable apart from a logged-only detection.
QUARANTINE_METRIC_KIND: dict[LlmLedQuarantineReason, str] = {
    LlmLedQuarantineReason.BALANCE_CHAIN_UNRECONCILED: "llm_led_gate_quarantine_balance",
    LlmLedQuarantineReason.DEDUP_CONSERVATION_VIOLATION: "llm_led_gate_quarantine_dedup",
    LlmLedQuarantineReason.BALANCE_INVARIANT_UNEVALUABLE: "llm_led_gate_quarantine_unevaluable",
}

# Human-readable, PII-free validation_error text per reason. Kept terminal-state
# specific so the review surface shows *why* an extraction was blocked, not a raw
# enum value.
QUARANTINE_MESSAGE: dict[LlmLedQuarantineReason, str] = {
    LlmLedQuarantineReason.BALANCE_CHAIN_UNRECONCILED: (
        "Extraction blocked: the running-balance chain does not reconcile "
        "(opening + inflows - outflows != closing). The parsed figures are internally "
        "inconsistent and cannot be trusted; re-upload a clearer source."
    ),
    LlmLedQuarantineReason.DEDUP_CONSERVATION_VIOLATION: (
        "Extraction blocked: within-document dedup conservation failed (two distinct rows "
        "collapsed into one). The transaction set is incomplete and cannot be trusted; "
        "re-upload a clearer source."
    ),
    LlmLedQuarantineReason.BALANCE_INVARIANT_UNEVALUABLE: (
        "Extraction blocked: the balance invariant could not be evaluated because an "
        "opening or closing balance is missing. Fail-closed: the extraction cannot be "
        "trusted without a verifiable balance chain."
    ),
}


@dataclass(frozen=True)
class LpGateVerdict:
    """The LLM-LED gate's decision for one extraction.

    ``quarantined`` is the single load-bearing flag; ``reason`` / ``message`` /
    ``metric_kind`` are populated only when quarantined.
    """

    quarantined: bool
    reason: LlmLedQuarantineReason | None = None

    @property
    def message(self) -> str | None:
        return QUARANTINE_MESSAGE[self.reason] if self.reason is not None else None

    @property
    def metric_kind(self) -> str | None:
        return QUARANTINE_METRIC_KIND[self.reason] if self.reason is not None else None


# The single "passes the gate" verdict (no allocation per pass-through call).
_PASS = LpGateVerdict(quarantined=False)


def evaluate_llm_led_extraction_gate(
    *,
    is_brokerage: bool,
    balance_evaluable: bool,
    balance_valid: bool,
    within_doc_collapse: int,
    balance_gate_exempt: bool = False,
) -> LpGateVerdict:
    """Decide whether an LLM-LED (event→L2) extraction must be quarantined.

    Pure, deterministic, Decimal-safe (it consumes already-computed boolean/int
    signals). Returns a quarantine verdict with a typed reason, or the pass-through
    verdict when every gated invariant holds.

    Order and independence (AC-extraction.2009.3): the dedup-conservation gate is evaluated
    INDEPENDENTLY of the balance gate and reported with a DISTINCT reason code. It
    is checked first so a statement that fails *both* still surfaces the dedup
    violation (a silently-lost row makes the balance signal untrustworthy anyway).

    Tier scope:

    - **Dedup conservation** applies to every document class: a within-document
      collapse means rows were silently lost, which no class can tolerate.
    - **Balance-chain** reconciliation gates **bank statements only**. Brokerage
      payloads reconcile via Layer-2 position snapshots, not a running-balance
      chain (#981), so ``is_brokerage`` exempts them from the balance gate (their
      NAV self-check remains the detection-time signal it already was).

    ``balance_evaluable`` is the fail-closed input (AC-extraction.2009.4): ``False`` means the
    balance invariant could not be computed (e.g. a bank statement missing an
    opening or closing balance), which quarantines rather than passing on the
    zero-default chain. It is ignored for brokerage payloads.

    ``balance_gate_exempt`` exempts the *balance* gate (only) for an extraction that
    is already a known-incomplete, explicitly-flagged review marker rather than a
    true balance mismatch — specifically the inferred-from-CSV-transactions path,
    which carries no source opening/closing balance and is routed to review with its
    own note (AC3.2.5). Such a statement is not silently passing, so blocking it
    would be a false reject; the dedup gate still applies to it.
    """
    # Independent dedup-conservation gate (AC-extraction.2009.3) — all document classes.
    if within_doc_collapse > 0:
        return LpGateVerdict(
            quarantined=True,
            reason=LlmLedQuarantineReason.DEDUP_CONSERVATION_VIOLATION,
        )

    # Balance-chain gate (AC-extraction.2009.2 / .4) — bank statements only, and never for an
    # explicitly-flagged incomplete review marker.
    if not is_brokerage and not balance_gate_exempt:
        if not balance_evaluable:
            return LpGateVerdict(
                quarantined=True,
                reason=LlmLedQuarantineReason.BALANCE_INVARIANT_UNEVALUABLE,
            )
        # Route the decision through the promotion gate so the deterministic trust
        # boundary (#930) is the single disposer: a failed invariant => REJECTED.
        verdict = evaluate_promotion(
            [
                InvariantResult(
                    name="llm_led_balance_chain",
                    passed=balance_valid,
                    tolerance=STATEMENT_BALANCE_TOLERANCE,
                ),
            ],
            confidence_rank=0,
            min_confidence=0,
        )
        if verdict.decision is PromotionDecision.REJECTED:
            return LpGateVerdict(
                quarantined=True,
                reason=LlmLedQuarantineReason.BALANCE_CHAIN_UNRECONCILED,
            )

    return _PASS
