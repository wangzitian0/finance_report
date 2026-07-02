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

from src.observability import get_logger
from src.services.validation import (
    ChainBreak,
    detect_balance_chain_break,
    validate_balance,
)

logger = get_logger(__name__)


@runtime_checkable
class RegionReExtractor(Protocol):
    """Injectable seam that re-extracts the broken region of a statement.

    Implementations receive the original extracted ``payload`` and the
    :class:`~src.services.validation.ChainBreak` that pinpoints where a row was
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


def repair_under_extraction(
    payload: dict[str, Any],
    *,
    reextractor: RegionReExtractor | None,
) -> ChainRepairResult:
    """Run the deterministic repair-pass hook once on a possibly under-extracted parse.

    Trigger logic (all deterministic):

    - If the balance self-check already passes, do nothing (``attempted=False``).
    - If the balance is not even *computable* (a structurally-broken payload with
      non-numeric/missing amounts), do nothing — the self-check delta is
      meaningless, so a region re-extraction has nothing valid to target. Treat it
      as "not repairable" rather than entering the re-extraction path.
    - If it fails but the chain-break detector finds no region, do nothing — the
      mismatch is not the dropped-row shape this pass repairs.
    - Otherwise, if a backend is injected, call it **exactly once** to re-extract
      the broken region. Keep the result only if it reconciles; otherwise keep the
      original payload.
    - With no backend injected, this is a safe no-op that still reports the
      detector signal so callers can log/track recall.
    """
    balance_result = validate_balance(payload)
    if balance_result.get("balance_valid"):
        return ChainRepairResult(payload=payload, attempted=False, repaired=False, break_info=None)

    if not balance_result.get("balance_computable"):
        # Structurally-broken payload (non-numeric/missing amounts): the balance
        # delta is undefined, so the chain-break detector cannot pinpoint a
        # meaningful region. Re-extraction would be pointless/possibly harmful;
        # short-circuit to a safe "not repairable" no-op.
        logger.info("Balance not computable; under-extraction repair is not applicable")
        return ChainRepairResult(payload=payload, attempted=False, repaired=False, break_info=None)

    transactions = payload.get("transactions") or []
    opening = _opening_balance(payload)
    break_info = detect_balance_chain_break(transactions, opening_balance=opening)
    if break_info is None:
        # Balance mismatch without a pinpointed chain break: not this hook's job
        # (could be a header/opening-balance issue, FX, etc.). Leave it alone.
        return ChainRepairResult(payload=payload, attempted=False, repaired=False, break_info=None)

    if reextractor is None:
        logger.info(
            "Chain-break detected but no repair backend wired; recall stays a soft metric",
            break_index=break_info.index,
            delta=str(break_info.delta),
        )
        return ChainRepairResult(payload=payload, attempted=False, repaired=False, break_info=break_info)

    logger.info(
        "Attempting region-targeted re-extract for under-extraction repair",
        break_index=break_info.index,
        delta=str(break_info.delta),
    )
    repaired_payload = reextractor.reextract_region(payload=payload, break_info=break_info)

    if repaired_payload is not None and validate_balance(repaired_payload).get("balance_valid"):
        logger.info("Repair pass reconciled the running-balance chain", break_index=break_info.index)
        return ChainRepairResult(payload=repaired_payload, attempted=True, repaired=True, break_info=break_info)

    # Repair did not reconcile: keep the original parse so routing is unchanged.
    logger.info("Repair pass did not reconcile; keeping original parse", break_index=break_info.index)
    return ChainRepairResult(payload=payload, attempted=True, repaired=False, break_info=break_info)


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
