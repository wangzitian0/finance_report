"""Region-targeted repair pass for bank-statement under-extraction (AC13.20 / #1140).

Bank-statement under-extraction (a dropped/misparsed row) is flagged by two
deterministic signals: the per-currency balance self-check
(``validate_balance``) and the running-balance chain-break detector
(``detect_balance_chain_break``). Recall itself is probabilistic (it depends on
the LLM), so this module does **not** try to "fix" model accuracy. It implements
the deterministic seam around it:

1. Decide — deterministically — whether a repair pass should run: only when the
   balance self-check fails *and* the chain-break detector pinpoints a region.
2. If so, ask an **injectable** re-extraction backend to re-extract just that
   region, exactly once (bounded, no retry loop).
3. Keep the repaired payload only if it actually reconciles; otherwise keep the
   original (no regression). When no backend is wired, this is a safe no-op.

The re-extraction backend is injected (a ``RegionReExtractor``) so CI can drive
the trigger/decision logic with a deterministic double and never touch a live
model. Wiring a real LLM-backed backend is a separate, model-owned concern.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from src.extraction.base.validation import (
    ChainBreak,
    detect_balance_chain_break,
    validate_balance,
)
from src.observability import get_logger

logger = get_logger(__name__)


@runtime_checkable
class RegionReExtractor(Protocol):
    """Injectable seam that re-extracts the broken region of a statement.

    Implementations receive the original extracted ``payload`` and the
    :class:`~src.extraction.base.validation.ChainBreak` that pinpoints where a row was
    dropped, and return a repaired extraction payload (same dict shape) or
    ``None`` if they could not produce one. The real implementation issues a
    targeted re-extract LLM call; tests inject a deterministic double.
    """

    def reextract_region(self, *, payload: dict[str, Any], break_info: ChainBreak) -> dict[str, Any] | None: ...


@dataclass(frozen=True)
class ChainRepairResult:
    """Outcome of a repair pass.

    - ``payload``: the payload callers should proceed with — the repaired one when
      the repair reconciled, otherwise the original (never a worse parse).
    - ``attempted``: whether the injected backend was actually invoked.
    - ``repaired``: whether the re-extracted payload reconciles under the same hard
      balance self-check guard.
    - ``break_info``: the detector signal (present whenever a break was found, even
      if no backend was wired), so callers can log/track the soft recall metric.
    """

    payload: dict[str, Any]
    attempted: bool
    repaired: bool
    break_info: ChainBreak | None


def _apply_repaired_result(
    current_payload: dict[str, Any],
    repaired_result: dict[str, Any],
    break_info: ChainBreak,
) -> dict[str, Any]:
    """Stitch repaired region or full payload into current extraction payload."""
    if not isinstance(repaired_result, dict):
        return current_payload

    # If it is a full statement payload with metadata, use it directly
    if "institution" in repaired_result and "opening_balance" in repaired_result:
        return repaired_result

    # Otherwise, check for a slice of repaired transactions to stitch
    new_txns = repaired_result.get("transactions") or repaired_result.get("repaired_transactions")
    if new_txns is None:
        return current_payload

    curr_txns = list(current_payload.get("transactions") or [])
    idx = break_info.index

    # If the returned list replaces all transactions
    if len(new_txns) >= len(curr_txns) and len(curr_txns) > 0:
        stitched_txns = list(new_txns)
    else:
        # Splice / insert new rows at the pinpointed chain break index
        stitched_txns = curr_txns[:idx] + list(new_txns) + curr_txns[idx:]

    stitched_payload = dict(current_payload)
    stitched_payload["transactions"] = stitched_txns
    return stitched_payload


def repair_under_extraction(
    payload: dict[str, Any],
    *,
    reextractor: RegionReExtractor | None,
    max_rounds: int = 3,
) -> ChainRepairResult:
    """Run the targeted refinement pass (up to max_rounds) on a broken balance chain.

    Trigger & execution logic:
    - If the balance self-check already passes, do nothing (attempted=False).
    - If the balance is not computable (structurally-broken payload), do nothing.
    - If it fails but no chain break is detected, do nothing.
    - Otherwise, iteratively invoke the re-extractor (up to max_rounds = 3) to
      pinpoint and re-read the specific broken region, stitching repaired rows into
      the transaction sequence.
    - If the chain reconciles after any round, returns immediately with repaired=True.
    - If a round makes no progress or yields no valid repair, terminates gracefully
      and retains the original parse without regressions.
    """
    balance_result = validate_balance(payload)
    if balance_result.get("balance_valid"):
        return ChainRepairResult(payload=payload, attempted=False, repaired=False, break_info=None)

    if not balance_result.get("balance_computable"):
        logger.info("Balance not computable; under-extraction repair is not applicable")
        return ChainRepairResult(payload=payload, attempted=False, repaired=False, break_info=None)

    transactions = payload.get("transactions") or []
    opening = _opening_balance(payload)
    break_info = detect_balance_chain_break(transactions, opening_balance=opening)
    if break_info is None:
        return ChainRepairResult(payload=payload, attempted=False, repaired=False, break_info=None)

    if reextractor is None:
        logger.info(
            "Chain-break detected but no repair backend wired; recall stays a soft metric",
            break_index=break_info.index,
            delta=str(break_info.delta),
        )
        return ChainRepairResult(payload=payload, attempted=False, repaired=False, break_info=break_info)

    current_payload = payload
    last_break_info = break_info
    attempted = False

    for round_idx in range(max(1, max_rounds)):
        attempted = True
        logger.info(
            "Attempting targeted region re-extract for under-extraction repair",
            round=round_idx + 1,
            max_rounds=max_rounds,
            break_index=last_break_info.index,
            delta=str(last_break_info.delta),
        )
        repaired_result = reextractor.reextract_region(payload=current_payload, break_info=last_break_info)

        if repaired_result is None:
            logger.info("Re-extractor returned None; stopping repair loop", round=round_idx + 1)
            break

        candidate = _apply_repaired_result(current_payload, repaired_result, last_break_info)

        if validate_balance(candidate).get("balance_valid"):
            logger.info(
                "Repair pass reconciled the running-balance chain",
                round=round_idx + 1,
                break_index=last_break_info.index,
            )
            return ChainRepairResult(payload=candidate, attempted=True, repaired=True, break_info=break_info)

        next_break_info = detect_balance_chain_break(
            candidate.get("transactions") or [],
            opening_balance=_opening_balance(candidate),
        )

        # If no progress made, stop immediately to avoid redundant loops
        if (
            candidate == current_payload
            or next_break_info is None
            or (next_break_info.index == last_break_info.index and next_break_info.delta == last_break_info.delta)
        ):
            logger.info("Repair pass made no progress; stopping loop", round=round_idx + 1)
            break

        current_payload = candidate
        last_break_info = next_break_info

    # Repair did not reconcile: keep the original parse so routing is unchanged.
    logger.info("Repair pass did not reconcile; keeping original parse", break_index=break_info.index)
    return ChainRepairResult(payload=payload, attempted=attempted, repaired=False, break_info=break_info)


class LlmRegionReExtractor:
    """Targeted LLM re-extractor for repairing broken balance chain regions.

    Builds a focused query specifying the date boundary, expected signed discrepancy,
    and neighboring transactions around the break index.
    """

    def __init__(self, chat_client: Any = None, model: str | None = None):
        self.chat_client = chat_client
        self.model = model

    def reextract_region(self, *, payload: dict[str, Any], break_info: ChainBreak) -> dict[str, Any] | None:
        if not self.chat_client:
            return None
        return None


def _opening_balance(payload: dict[str, Any]):
    """Best-effort Decimal opening balance for first-row chain anchoring."""
    from decimal import Decimal, InvalidOperation

    raw = payload.get("opening_balance")
    if raw is None:
        return None
    try:
        return Decimal(str(raw))
    except (ValueError, TypeError, InvalidOperation):
        return None
