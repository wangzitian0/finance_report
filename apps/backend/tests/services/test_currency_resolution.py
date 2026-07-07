"""Ingest-boundary currency resolution + promotion gate (EPIC-012 AC12.40, #1341).

Phase E of the currency strong-type invariant: a transaction's currency is
established AT INGEST (attached when determinable, otherwise flagged
``currency_unresolved`` and routed to human review), a reviewer specifies it with
an ISO-4217-validated value (audited who/when), and the promotion gate refuses to
turn an unresolved transaction into a JournalLine.

These proofs are DB-free: they exercise the decision logic and the promotion-gate
guard directly, so they run in PR CI without a database.
"""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from uuid import uuid4

import pytest
from common.testing.ac_proof import ac_proof

from src.audit.money import InvalidCurrencyError
from src.extraction.extension.currency_resolution import (
    UNRESOLVED_PLACEHOLDER,
    CurrencyUnresolvedError,
    resolve_ingest_currency,
    resolve_transaction_currency,
)
from src.extraction.extension.review_queue import create_entry_from_txn

pytestmark = pytest.mark.no_db


# --- AC12.40.1: attach an explicit currency when determinable -----------------


@ac_proof(proof_id="test_ingest_attaches_explicit_currency", ac_ids=["AC12.40.1"], ci_tier="pr_ci", issue="#1341")
@pytest.mark.parametrize(
    ("candidates", "expected"),
    [
        (("USD",), "USD"),
        (("usd ",), "USD"),  # normalized (strip + upper) by Currency
        ((None, "SGD"), "SGD"),  # fall through to the statement currency
        (("ZZZ", "EUR"), "EUR"),  # skip an invalid code, take the next valid one
    ],
)
def test_AC12_40_1_attaches_explicit_currency(candidates, expected):
    """AC-audit.40.1: AC12.40.1: the first valid ISO-4217 candidate is attached, normalized."""
    resolved = resolve_ingest_currency(*candidates)
    assert resolved.code == expected
    assert resolved.unresolved is False


# --- AC12.40.2: unknown/ambiguous -> flagged currency_unresolved --------------


@ac_proof(proof_id="test_ingest_flags_unresolved", ac_ids=["AC12.40.2"], ci_tier="pr_ci", issue="#1341")
@pytest.mark.parametrize(
    "candidates",
    [
        (),  # no candidates at all
        (None,),  # missing transaction currency
        (None, None),  # missing transaction + statement currency
        ("ZZZ",),  # not an ISO-4217 code
        ("US", ""),  # too short / empty -> neither is valid
    ],
)
def test_AC12_40_2_flags_unresolved_instead_of_silent_default(candidates):
    """AC-audit.40.2: AC12.40.2: no valid currency -> flagged unresolved with a non-trusted placeholder.

    Critically it must NOT silently default to a base currency like SGD.
    """
    resolved = resolve_ingest_currency(*candidates)
    assert resolved.unresolved is True
    assert resolved.code == UNRESOLVED_PLACEHOLDER
    assert resolved.code != "SGD"


@ac_proof(proof_id="test_unresolved_placeholder_is_not_valid", ac_ids=["AC12.40.2"], ci_tier="pr_ci", issue="#1341")
def test_AC12_40_2_placeholder_cannot_masquerade_as_real_currency():
    """AC12.40.2: the placeholder is rejected by Currency(), so it can never look resolved."""
    from src.audit.money import Currency

    with pytest.raises(InvalidCurrencyError):
        Currency(UNRESOLVED_PLACEHOLDER)


# --- AC12.40.4: promotion gate blocks currency_unresolved items ----------------


@ac_proof(proof_id="test_promotion_gate_blocks_unresolved", ac_ids=["AC12.40.4"], ci_tier="pr_ci", issue="#1341")
async def test_AC12_40_4_promotion_gate_blocks_unresolved_currency():
    """AC-audit.40.4: AC12.40.4: an unresolved transaction cannot be promoted to a JournalLine.

    The guard fires before any DB access, so ``db=None`` is sufficient to prove the
    block: if the guard were absent the call would instead fail trying to use the DB.
    """
    user_id = uuid4()
    txn = SimpleNamespace(
        id=uuid4(),
        user_id=user_id,
        currency_unresolved=True,
        currency=UNRESOLVED_PLACEHOLDER,
        txn_date=date(2024, 1, 1),
    )

    with pytest.raises(CurrencyUnresolvedError):
        await create_entry_from_txn(None, txn, user_id=user_id)  # type: ignore[arg-type]


@ac_proof(proof_id="test_promotion_gate_allows_resolved", ac_ids=["AC12.40.4"], ci_tier="pr_ci", issue="#1341")
async def test_AC12_40_4_promotion_gate_passes_guard_when_resolved():
    """AC12.40.4: a resolved transaction passes the currency guard (it then proceeds to DB work).

    With ``currency_unresolved=False`` the guard must NOT raise; the call moves past
    the guard and only then needs the DB, so we assert it does not raise the
    currency error specifically.
    """
    user_id = uuid4()
    txn = SimpleNamespace(
        id=uuid4(),
        user_id=user_id,
        currency_unresolved=False,
        currency="USD",
        txn_date=date(2024, 1, 1),
        source_documents=[],
    )

    with pytest.raises(Exception) as exc_info:
        await create_entry_from_txn(None, txn, user_id=user_id)  # type: ignore[arg-type]
    # It must fail for a reason OTHER than the currency guard (the guard was passed).
    assert not isinstance(exc_info.value, CurrencyUnresolvedError)


# --- AC12.40.3: reviewer specifies currency, audited (who/when/value) ----------


class _FakeResult:
    def __init__(self, obj):
        self._obj = obj

    def scalar_one_or_none(self):
        return self._obj


class _FakeSession:
    """Minimal async session that returns a preset transaction and records flush()."""

    def __init__(self, txn):
        self._txn = txn
        self.flushed = False

    async def execute(self, _stmt):
        return _FakeResult(self._txn)

    async def flush(self):
        self.flushed = True


@ac_proof(proof_id="test_reviewer_resolves_currency_audited", ac_ids=["AC12.40.3"], ci_tier="pr_ci", issue="#1341")
async def test_AC12_40_3_reviewer_resolves_currency_with_audit():
    """AC-audit.40.3: AC12.40.3: a reviewer sets an ISO-4217 currency; who/when/value are recorded."""
    user_id = uuid4()
    txn = SimpleNamespace(
        id=uuid4(),
        user_id=user_id,
        currency=UNRESOLVED_PLACEHOLDER,
        currency_unresolved=True,
        currency_resolved_by=None,
        currency_resolved_at=None,
    )
    session = _FakeSession(txn)

    result = await resolve_transaction_currency(session, txn.id, user_id=user_id, currency="usd ")

    assert result.currency == "USD"  # validated + normalized via Currency
    assert result.currency_unresolved is False
    assert result.currency_resolved_by == user_id  # who
    assert result.currency_resolved_at is not None  # when
    assert session.flushed is True


@ac_proof(proof_id="test_reviewer_rejects_bad_currency", ac_ids=["AC12.40.3"], ci_tier="pr_ci", issue="#1341")
async def test_AC12_40_3_reviewer_currency_must_be_iso_4217():
    """AC12.40.3: an invalid code is rejected and nothing is written (still unresolved)."""
    user_id = uuid4()
    txn = SimpleNamespace(
        id=uuid4(),
        user_id=user_id,
        currency=UNRESOLVED_PLACEHOLDER,
        currency_unresolved=True,
        currency_resolved_by=None,
        currency_resolved_at=None,
    )
    session = _FakeSession(txn)

    with pytest.raises(InvalidCurrencyError):
        await resolve_transaction_currency(session, txn.id, user_id=user_id, currency="ZZZ")

    # Nothing mutated: the row is still flagged unresolved and un-audited.
    assert txn.currency_unresolved is True
    assert txn.currency_resolved_by is None
    assert txn.currency_resolved_at is None
