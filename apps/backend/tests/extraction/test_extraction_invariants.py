"""tier LLM-LED proof: deterministic invariants over LLM-extracted statement data.

EPIC-026 phase 2 — the extraction ACs in EPIC-003 are tier **LLM-LED**: the LLM emits
the parsed statement, and deterministic CODE only validates / gatekeeps it (it can
reject or flag, never produce). Per the tier->proof matrix
(``common/authority/readme.md``), an LLM-LED AC is proven by an
**invariant/property** test of that gatekeeper, NOT by an exact golden assertion
on the LLM output (which is non-reproducible).

These tests assert the two invariants that catch the #1254-class money bug
regardless of what the LLM emits:

1. **Balance-chain invariant** — for any parsed statement,
   ``opening + ΣIN − ΣOUT ≈ closing`` (within tolerance). This is the
   deterministic oracle `validate_balance` applies to the LLM's output; it holds
   as a property across a generated space of statements, and FAILS exactly when
   the chain is broken (the #1254 detector, expressed as a property).
2. **Dedup row/count conservation** — two genuinely-distinct same-date/same-amount
   rows must never collapse into one (the #1254 dedup root cause). The
   conservation property is owned by AC-extraction.122.1
   (`test_AC13_22_1_same_balance_distinct_rows_do_not_collapse` in
   `extraction/test_deduplication.py`); here we assert the same conservation
   property holds across a generated space of repeat-counts via the public
   `DeduplicationService.calculate_transaction_hash` seam.

No LLM and no DB: the LLM output is the *input* to these properties; the code
under test is the deterministic gate, which is what an LLM-LED AC's proof must cover.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import UUID

from src.extraction.base.validation import BALANCE_TOLERANCE, validate_balance
from src.extraction.extension.deduplication import DeduplicationService
from src.models.layer2 import TransactionDirection


def _make_statement(opening: Decimal, ins: list[Decimal], outs: list[Decimal]) -> dict:
    """A statement whose closing balance is computed to satisfy the chain exactly."""
    net = sum(ins, Decimal("0")) - sum(outs, Decimal("0"))
    txns = [{"amount": str(a), "direction": "IN"} for a in ins]
    txns += [{"amount": str(a), "direction": "OUT"} for a in outs]
    return {
        "opening_balance": str(opening),
        "closing_balance": str(opening + net),
        "transactions": txns,
    }


# A deterministic, varied space of statements standing in for what an LLM might
# emit. Each is constructed to satisfy the chain exactly so the invariant must
# hold; the broken-chain cases below assert it FAILS when it should.
_BALANCED_CASES = [
    (Decimal("0.00"), [Decimal("100.00")], []),
    (Decimal("1000.00"), [Decimal("200.00"), Decimal("50.00")], [Decimal("75.00")]),
    (Decimal("-50.00"), [Decimal("500.00")], [Decimal("499.99")]),
    (Decimal("9999.99"), [], [Decimal("9999.99")]),
    (
        Decimal("123.45"),
        [Decimal("10.10"), Decimal("20.20"), Decimal("30.30")],
        [Decimal("5.05"), Decimal("15.15")],
    ),
    (Decimal("1000000.00"), [Decimal("0.01")] * 50, [Decimal("0.02")] * 25),
]


class TestBalanceChainInvariantLP:
    """AC-extraction.1.1 / AC-extraction.5.7 / AC-extraction.5.19 (tier LLM-LED): the balance-chain invariant."""

    def test_balance_chain_invariant_holds_for_consistent_statements(self):
        """opening + ΣIN − ΣOUT ≈ closing holds across the generated space.

        [AC-extraction.1.1] [AC-extraction.5.7] LLM-LED invariant: whatever the LLM emits, a statement
        whose chain is internally consistent passes the deterministic balance
        gate. The property is asserted over many shapes, not one golden fixture.
        """
        for opening, ins, outs in _BALANCED_CASES:
            extracted = _make_statement(opening, ins, outs)
            result = validate_balance(extracted)
            net = sum(ins, Decimal("0")) - sum(outs, Decimal("0"))
            expected_closing = opening + net
            assert result["balance_valid"] is True, f"chain should validate for opening={opening} net={net}: {result}"
            # The code recomputes the chain independently of the LLM's closing.
            assert Decimal(str(extracted["closing_balance"])) == expected_closing

    def test_balance_chain_invariant_detects_broken_chain(self):
        """A closing that breaks the chain by more than tolerance is rejected.

        [AC-extraction.5.19] LLM-LED invariant (the #1254 detector): if the LLM emits a closing
        balance that does not reconcile with the row sum, the deterministic gate
        FLAGS it — code gatekeeps the LLM output instead of trusting it.
        """
        for opening, ins, outs in _BALANCED_CASES:
            extracted = _make_statement(opening, ins, outs)
            consistent_closing = Decimal(str(extracted["closing_balance"]))
            # Perturb the closing well beyond tolerance: the gate must catch it.
            extracted["closing_balance"] = str(consistent_closing + BALANCE_TOLERANCE + Decimal("1.00"))
            result = validate_balance(extracted)
            assert result["balance_valid"] is False, f"broken chain must be flagged for opening={opening}: {result}"

    def test_balance_chain_tolerance_is_symmetric(self):
        """Rounding within tolerance passes in either direction (property, not golden).

        [AC-extraction.1.1] LLM-LED invariant: the gate tolerates sub-cent rounding the LLM may
        introduce, symmetrically above and below the computed closing.
        """
        base = _make_statement(Decimal("1000.00"), [Decimal("100.00")], [])
        computed = Decimal(str(base["closing_balance"]))
        for delta in (BALANCE_TOLERANCE, -BALANCE_TOLERANCE):
            base["closing_balance"] = str(computed + delta)
            assert validate_balance(base)["balance_valid"] is True


class TestDedupConservationLP:
    """AC-extraction.5.19 (tier LLM-LED): row/count conservation — distinct rows never collapse.

    The canonical conservation property lives in AC-extraction.122.1
    (`test_AC13_22_1_same_balance_distinct_rows_do_not_collapse`). This asserts
    the same #1254 root-cause property across a generated range of repeat counts:
    N genuinely-distinct same-date/same-amount/same-balance rows must yield N
    distinct dedup hashes (no silent collapse), while re-uploading the same row
    still collapses (idempotent).
    """

    _USER = UUID("00000000-0000-0000-0000-000000000001")

    def _hash(self, occurrence_index: int, balance_after: Decimal | None) -> str:
        return DeduplicationService.calculate_transaction_hash(
            user_id=self._USER,
            txn_date=date(2025, 1, 15),
            amount=Decimal("100.00"),
            direction=TransactionDirection.IN,
            description="SALARY",
            reference=None,
            balance_after=balance_after,
            occurrence_index=occurrence_index,
        )

    def test_distinct_same_amount_rows_never_collapse(self):
        """N distinct same-date/same-amount rows -> N distinct hashes (#1254).

        [AC-extraction.5.19] LLM-LED conservation property across repeat counts 1..12.
        """
        for n in range(1, 13):
            for balance_after in (None, Decimal("100.00")):
                hashes = {self._hash(i, balance_after) for i in range(n)}
                assert len(hashes) == n, (
                    f"{n} distinct rows collapsed to {len(hashes)} (balance_after={balance_after}) — #1254 regression"
                )

    def test_identical_row_reupload_is_idempotent(self):
        """The same row (same occurrence index) hashes identically — true dups collapse.

        [AC-extraction.5.19] LLM-LED conservation: dedup must still collapse genuine re-uploads,
        so conservation does not become "never dedup anything".
        """
        for balance_after in (None, Decimal("100.00")):
            assert self._hash(0, balance_after) == self._hash(0, balance_after)
            assert self._hash(3, balance_after) == self._hash(3, balance_after)
