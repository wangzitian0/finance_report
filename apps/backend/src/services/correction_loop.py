"""Correction feedback loop: turn human corrections into priors that lower the
low-confidence proportion (#931, Axiom B).

B3 (#919) measures the low-confidence-data proportion — the thermometer. This is
the furnace: every human correction that overrode an AI proposal (a
Manual-supersedes-Derived signal recorded in the append-only ``CorrectionLog``)
is labeled signal about where the system was wrong. Replayed as priors, a recurring
correction grounds future instances of the same pattern so they are no longer
low-confidence — measurably driving the north-star proportion down.

Scope of this slice: the corpus (derived from the provenance substrate, not a
sidecar) and the deterministic measurable replay. Wiring the priors into live
extraction/classification generation, and calibrating the promotion-gate
thresholds (#930) from the corpus, are follow-ups; the runtime that dispatches AI
attempts is a separate EPIC.
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.correction import CorrectionLog

_QUANT = Decimal("0.00001")


def _normalize_key(text: str | None) -> str:
    """Collapse a transaction pattern to a stable prior key."""
    return " ".join((text or "").lower().split())


@dataclass(frozen=True)
class CorrectionRecord:
    """One labeled correction derived from provenance: a human overrode an AI proposal."""

    key: str
    corrected_category: str
    proposed_category: str | None


@dataclass(frozen=True)
class ReplayResult:
    """The measurable outcome of replaying the corpus against a held-out split."""

    holdout_size: int
    grounded: int
    proportion_before: Decimal
    proportion_after: Decimal

    @property
    def reduced(self) -> bool:
        return self.proportion_after < self.proportion_before


def build_corpus_from_corrections(corrections: Iterable[CorrectionLog]) -> list[CorrectionRecord]:
    """Derive the correction corpus from ``CorrectionLog``, keyed by the transaction pattern.

    No sidecar: the corpus is a projection of the existing append-only correction
    store (the provenance-tagged Manual-supersedes-Derived signal), not a separate
    source of truth. Corrections with no usable pattern are skipped.
    """
    records: list[CorrectionRecord] = []
    for correction in corrections:
        # Normalize each candidate independently: a whitespace-only description must
        # fall back to original_category rather than yield an empty key.
        key = _normalize_key(correction.transaction_description) or _normalize_key(correction.original_category)
        if not key:
            continue
        records.append(
            CorrectionRecord(
                key=key,
                corrected_category=correction.corrected_category,
                proposed_category=correction.original_category,
            )
        )
    return records


def replay_low_confidence_reduction(
    corpus: Sequence[CorrectionRecord],
    *,
    train_ratio: Decimal = Decimal("0.5"),
) -> ReplayResult:
    """Held-out replay: build priors from a train split and measure the held-out proportion.

    Each held-out correction is, by definition, a low-confidence proposal the AI
    got wrong. A held-out item whose key was already corrected in the train split
    is grounded by the prior — its answer is known — so it is no longer
    low-confidence. The proportion strictly drops exactly when correction patterns
    recur, which is the loop measurably improving (and never an invented gain when
    they do not).
    """
    ordered = list(corpus)
    split = int(len(ordered) * train_ratio)
    prior_keys = {record.key for record in ordered[:split]}
    holdout = ordered[split:]

    holdout_size = len(holdout)
    grounded = sum(1 for record in holdout if record.key in prior_keys)
    low_after = holdout_size - grounded

    def _proportion(count: int) -> Decimal:
        return (Decimal(count) / Decimal(holdout_size)).quantize(_QUANT) if holdout_size else Decimal("0")

    return ReplayResult(
        holdout_size=holdout_size,
        grounded=grounded,
        proportion_before=_proportion(holdout_size),
        proportion_after=_proportion(low_after),
    )


class CorrectionLoopService:
    """Builds the correction corpus from the provenance substrate."""

    async def build_corpus(self, db: AsyncSession, user_id: UUID) -> list[CorrectionRecord]:
        """Project a user's append-only corrections into the replayable corpus."""
        result = await db.execute(
            select(CorrectionLog)
            .where(CorrectionLog.user_id == user_id)
            # id breaks created_at ties so the corpus order — and the replay split — is deterministic.
            .order_by(CorrectionLog.created_at, CorrectionLog.id)
        )
        return build_corpus_from_corrections(result.scalars().all())
