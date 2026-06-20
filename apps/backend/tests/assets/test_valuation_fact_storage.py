"""Atomic valuation fact + classification storage tests (#1222, EPIC-011 AC11.22).

Storage-only proofs: persistence + dedup, contract-bound stable fields, the
append-only versioning invariant, and that the legacy manual valuation model is
left untouched. No LLM / adapter / report behaviour is exercised here.
"""

from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from src.constants.valuation_taxonomy import (
    EconomicSide,
    LiquidityClass,
    ValuationL1,
    ValuationL2,
    ValuationRole,
)
from src.models.layer3 import ManualValuationComponentType, ManualValuationSnapshot
from src.models.user import User
from src.models.valuation import (
    AtomicValuationFact,
    ValuationClassification,
    ValuationReviewStatus,
)


def _fact(user_id, *, dedup_hash="hash-1", amount="1000.00"):
    return AtomicValuationFact(
        user_id=user_id,
        as_of_date=date(2026, 5, 31),
        amount=Decimal(amount),
        currency="SGD",
        raw_label="CPF Ordinary Account",
        issuer="CPF Board",
        jurisdiction="SG",
        scheme_name="Central Provident Fund",
        source_document_anchor={"document_id": str(uuid4()), "page": 1},
        raw_payload={"line": "OA balance", "value": amount},
        evidence_spans=[{"page": 1, "bbox": [0, 0, 10, 10]}],
        dedup_hash=dedup_hash,
    )


def _classification(fact_id, user_id, **overrides):
    base = dict(
        valuation_fact_id=fact_id,
        user_id=user_id,
        l1=ValuationL1.RETIREMENT_AND_BENEFIT,
        l2=ValuationL2.MANDATORY_RETIREMENT,
        economic_side=EconomicSide.ASSET,
        valuation_role=ValuationRole.NET_WORTH_COMPONENT,
        liquidity_class=LiquidityClass.RESTRICTED,
        confidence=Decimal("0.9500"),
        rationale="Statutory retirement balance.",
        model_version="glm-4.6v",
        prompt_version="valuation-classify-v1",
    )
    base.update(overrides)
    return ValuationClassification(**base)


async def test_atomic_valuation_fact_persists_and_dedup_hash_is_unique_per_user(db, test_user):
    """AC11.22.1: fact persists with Decimal amount + metadata; dedup is per-user."""
    fact = _fact(test_user.id)
    db.add(fact)
    await db.commit()
    await db.refresh(fact)

    assert fact.amount == Decimal("1000.00")
    assert fact.currency == "SGD"
    assert fact.raw_label == "CPF Ordinary Account"
    assert fact.jurisdiction == "SG"
    assert fact.evidence_spans[0]["page"] == 1
    assert fact.dedup_hash == "hash-1"

    # Same (user, dedup_hash) is rejected — idempotent ingestion.
    with pytest.raises(IntegrityError):
        async with db.begin_nested():
            db.add(_fact(test_user.id, dedup_hash="hash-1"))
            await db.flush()

    # Same hash for a *different* user is allowed.
    other = User(email=f"other-{uuid4()}@example.com", hashed_password="x")
    db.add(other)
    await db.flush()
    db.add(_fact(other.id, dedup_hash="hash-1"))
    await db.commit()


async def test_valuation_classification_persists_stable_fields_and_rejects_out_of_contract_codes(db, test_user):
    """AC11.22.2: stable fields persist; codes outside the contract are rejected."""
    fact = _fact(test_user.id)
    db.add(fact)
    await db.flush()

    clf = _classification(fact.id, test_user.id)
    db.add(clf)
    await db.commit()
    await db.refresh(clf)

    assert clf.l1 is ValuationL1.RETIREMENT_AND_BENEFIT
    assert clf.l2 is ValuationL2.MANDATORY_RETIREMENT
    assert clf.economic_side is EconomicSide.ASSET
    assert clf.valuation_role is ValuationRole.NET_WORTH_COMPONENT
    assert clf.liquidity_class is LiquidityClass.RESTRICTED
    assert clf.confidence == Decimal("0.9500")
    # Defaults: review gate starts pending, version starts at 1.
    assert clf.review_status is ValuationReviewStatus.PENDING
    assert clf.version == 1
    assert clf.model_version == "glm-4.6v"

    # A jurisdiction/scheme-specific code (e.g. "cpf") is not a stable taxonomy
    # value, so it is rejected at persistence.
    with pytest.raises(SQLAlchemyError):
        async with db.begin_nested():
            bad = _classification(fact.id, test_user.id, l1="cpf")
            db.add(bad)
            await db.flush()


async def test_valuation_classification_is_append_only_per_fact(db, test_user):
    """AC11.22.3: reclassification appends a version; history is preserved."""
    fact = _fact(test_user.id)
    db.add(fact)
    await db.flush()

    v1 = _classification(fact.id, test_user.id, l2=ValuationL2.MANDATORY_RETIREMENT)
    db.add(v1)
    await db.commit()
    await db.refresh(v1)

    # Two current (non-superseded) heads for one fact are rejected.
    with pytest.raises(IntegrityError):
        async with db.begin_nested():
            db.add(_classification(fact.id, test_user.id))
            await db.flush()

    # Proper reclassification uses the ordered hand-off (matching the manual
    # snapshot pattern) so neither the self-FK nor the partial unique index is
    # ever violated: park the new row under the prior head, demote the old head,
    # then promote the new row.
    v2 = _classification(
        fact.id,
        test_user.id,
        l2=ValuationL2.VOLUNTARY_RETIREMENT,
        version=2,
        superseded_by_id=v1.id,
    )
    db.add(v2)
    await db.flush()
    v1.superseded_by_id = v2.id
    await db.flush()
    v2.superseded_by_id = None
    await db.commit()

    rows = (
        (await db.execute(select(ValuationClassification).where(ValuationClassification.valuation_fact_id == fact.id)))
        .scalars()
        .all()
    )
    assert len(rows) == 2  # prior model output not destroyed
    heads = [r for r in rows if r.superseded_by_id is None]
    assert len(heads) == 1 and heads[0].id == v2.id
    assert heads[0].l2 is ValuationL2.VOLUNTARY_RETIREMENT


async def test_valuation_classification_rejects_cross_user_fact_reference(db, test_user):
    """AC11.22.5: same-owner composite FK rejects another user's fact reference."""
    fact = _fact(test_user.id)
    db.add(fact)
    other = User(email=f"other-{uuid4()}@example.com", hashed_password="x")
    db.add(other)
    await db.flush()

    # A classification owned by `other` cannot reference test_user's fact: the
    # (user_id, valuation_fact_id) composite FK has no matching fact row.
    with pytest.raises(IntegrityError):
        async with db.begin_nested():
            db.add(_classification(fact.id, other.id))
            await db.flush()


def test_manual_valuation_model_is_unchanged_by_storage_addition():
    """AC11.22.4: legacy manual valuation model + enum values are untouched."""
    # No legacy enum value removed (regression guard for the strangler approach).
    legacy_values = {e.value for e in ManualValuationComponentType}
    assert {
        "property_value",
        "mortgage_balance",
        "cpf_balance",
        "retirement_account",
        "social_security_personal_account",
        "insurance_cash_value",
        "esop",
        "rsu",
        "stock_options",
        "other_asset",
        "other_liability",
    } <= legacy_values
    assert ManualValuationSnapshot.__tablename__ == "manual_valuation_snapshots"
