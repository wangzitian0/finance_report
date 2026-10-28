"""The advisor context keeps its facts and suggestions while it does less work (#2583 S7).

The golden file holds the output of ``main`` at ``61760e8a``, before the S7 change.
The fixture runs the real reads: no read of the advisor context is replaced by a fake.
It covers both readiness paths of the advisor. In the first state, the app shell has
derived workflow readiness and no input changed after that. In the second state, an
input changed after the derivation, so a stored readiness must not be used.
"""

from __future__ import annotations

import json
import re
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.advisor import AIAdvisorService
from src.extraction import TransactionDirection
from src.extraction.orm.layer2 import AtomicTransaction
from src.reconciliation import ReconciliationMatch, ReconciliationStatus
from src.workflow import stored_package_readiness
from tests.e2e.test_statement_corpus_journeys import attach_reviewed_corpus_semantics
from tests.factories import seed_parsed_statement

GOLDEN_PATH = Path(__file__).resolve().parents[1] / "fixtures" / "advisor_context_golden.json"

_UUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
_DATETIME_RE = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:[+-]\d{2}:\d{2}|Z)?")


def normalized(value: Any) -> Any:
    """Replace identifiers, timestamps and the run date, which change between runs."""
    text = json.dumps(value, sort_keys=True, default=str)
    text = _UUID_RE.sub("<uuid>", text)
    text = _DATETIME_RE.sub("<datetime>", text)
    text = text.replace(date.today().isoformat(), "<today>")
    return json.loads(text)


def normalized_financial_context(context: dict[str, str]) -> dict[str, Any]:
    """Normalize the ``/chat`` context. The embedded advisor context is parsed first."""
    return normalized({**context, "advisor_context": json.loads(context["advisor_context"])})


async def _seed_statement(client, db: AsyncSession, user_id: UUID, *, name: str, approve: bool) -> str:
    today = date.today()
    seeded = await seed_parsed_statement(
        db,
        user_id,
        institution="DBS",
        original_filename=f"{name}.pdf",
        opening_balance=Decimal("1000.00"),
        transactions=[
            {
                "description": f"Salary {name}",
                "amount": Decimal("3000.00"),
                "direction": TransactionDirection.IN,
                "date": today,
            },
            {
                "description": f"Grocer {name}",
                "amount": Decimal("42.25"),
                "direction": TransactionDirection.OUT,
                "date": today,
            },
            {
                "description": f"Cafe {name}",
                "amount": Decimal("7.50"),
                "direction": TransactionDirection.OUT,
                "date": today,
            },
        ],
    )
    seeded.statement.period_start = today
    seeded.statement.period_end = today
    await attach_reviewed_corpus_semantics(db, user_id, seeded.transactions)
    await db.commit()
    statement_id = str(seeded.id)
    if approve:
        await approve_statement(client, statement_id)
        reconciliation = await client.post("/reconciliation/runs", json={"statement_id": statement_id})
        assert reconciliation.status_code == 200, reconciliation.text
    return statement_id


async def approve_statement(client, statement_id: str) -> None:
    review = await client.get(f"/statements/{statement_id}/review")
    assert review.status_code == 200, review.text
    conflicts = (await client.get(f"/review/conflicts/{statement_id}")).json()
    if conflicts.get("duplicates") or conflicts.get("transfer_pairs"):
        resolved = await client.post(
            f"/review/conflicts/{statement_id}/resolve",
            json={"action": "confirm_distinct", "note": "advisor equivalence fixture"},
        )
        assert resolved.status_code == 200, resolved.text
    approved = await client.post(f"/statements/{statement_id}/review/approve", json={"create_account_if_missing": True})
    assert approved.status_code == 200, approved.text


async def _add_pending_reconciliation_match(db: AsyncSession, user_id: UUID) -> None:
    transaction = AtomicTransaction(
        user_id=user_id,
        txn_date=date.today(),
        description="Unconfirmed transfer",
        amount=Decimal("15.00"),
        direction=TransactionDirection.OUT,
        currency="SGD",
        dedup_hash="advisor-equivalence-pending-match",
        source_documents=[],
    )
    db.add(transaction)
    await db.flush()
    db.add(ReconciliationMatch(atomic_txn_id=transaction.id, status=ReconciliationStatus.PENDING_REVIEW))
    await db.commit()


async def build_advisor_states(client, db: AsyncSession, user_id: UUID) -> dict[str, Any]:
    """Return the advisor outputs in the two readiness states.

    The golden file holds the ``advisor_context`` and ``financial_context`` of each state.
    ``stored_readiness_reusable`` records which readiness path the state took.
    """
    await _seed_statement(client, db, user_id, name="approved", approve=True)
    pending_statement_id = await _seed_statement(client, db, user_id, name="pending", approve=False)
    await _add_pending_reconciliation_match(db, user_id)

    # The app shell reads the workflow status on each page. The read derives and stores readiness.
    status = await client.get("/workflow/status")
    assert status.status_code == 200, status.text
    service = AIAdvisorService()
    stored_state = {
        "stored_readiness_reusable": await stored_package_readiness(db, user_id=user_id) is not None,
        "advisor_context": await service.get_advisor_context(db, user_id),
        "financial_context": await service.get_financial_context(db, user_id),
    }

    # An input changes after the derivation: the stored readiness is now stale.
    await approve_statement(client, pending_statement_id)
    changed_state = {
        "stored_readiness_reusable": await stored_package_readiness(db, user_id=user_id) is not None,
        "advisor_context": await service.get_advisor_context(db, user_id),
        "financial_context": await service.get_financial_context(db, user_id),
    }
    return {"stored_readiness_current": stored_state, "stored_readiness_stale": changed_state}


def normalized_states(states: dict[str, Any]) -> dict[str, Any]:
    return {
        name: {
            "advisor_context": normalized(state["advisor_context"]),
            "financial_context": normalized_financial_context(state["financial_context"]),
        }
        for name, state in states.items()
    }


async def test_AC_advisor_context_5_context_and_suggestions_equal_the_pre_change_output(
    client, db: AsyncSession, test_user
) -> None:
    """AC-advisor.context.5: on real data, ``get_advisor_context`` and ``get_financial_context``
    return the same facts and suggestions as before #2583 S7, in both readiness states.
    ``get_advisor_suggestions`` returns the suggestions of ``get_advisor_context``."""
    states = await build_advisor_states(client, db, test_user.id)
    golden = json.loads(GOLDEN_PATH.read_text())

    # Each state takes the readiness path that its name states.
    assert states["stored_readiness_current"]["stored_readiness_reusable"] is True
    assert states["stored_readiness_stale"]["stored_readiness_reusable"] is False
    assert normalized_states(states) == golden

    # The fixture reaches the suggestion rules that read each fact group.
    tiers = {item["confidence_tier"] for item in states["stored_readiness_stale"]["advisor_context"]["suggestions"]}
    assert {"blocked", "review_required", "stale"} <= tiers
    pending_review = states["stored_readiness_stale"]["advisor_context"]["cash_flow"]["pending_review"]
    assert pending_review == "1"

    service = AIAdvisorService()
    suggestions = await service.get_advisor_suggestions(db, test_user.id)
    assert suggestions == (await service.get_advisor_context(db, test_user.id))["suggestions"]
    assert normalized(suggestions) == golden["stored_readiness_stale"]["advisor_context"]["suggestions"]


_RECONCILIATION_SUMMARY_KEYS = {"unmatched_count", "match_rate", "pending_review"}


@pytest.mark.no_db
def test_AC_advisor_context_5_suggestion_rules_read_only_reconciliation_summary_fields() -> None:
    """AC-advisor.context.5: ``get_advisor_suggestions`` passes only the reconciliation fields of
    the financial summary. The suggestion rules must not read another summary field, so the
    suggestions stay equal when every other field changes or is missing."""
    golden = json.loads(GOLDEN_PATH.read_text())["stored_readiness_stale"]["advisor_context"]
    summary = golden["financial_summary"]
    other_keys = set(summary) - _RECONCILIATION_SUMMARY_KEYS
    assert other_keys, "the golden summary must hold fields outside reconciliation"
    reconciliation = {key: summary[key] for key in _RECONCILIATION_SUMMARY_KEYS}
    facts = {
        "readiness": {
            "state": "blocked",
            "label": "Blocked",
            "action_href": "/reports?tab=package",
            "blocking_count": 2,
            "blockers": [{"code": "cash_identity_missing"}],
            "input_coverage": {},
        },
        "workflow": golden["workflow"],
        "market_data": golden["market_data"],
        "portfolio": {
            "available": True,
            "active_positions_count": 1,
            "total_market_value": "10.00",
            "currency": "SGD",
        },
    }
    service = AIAdvisorService()

    def suggestions_for(financial_summary: dict[str, str]) -> list[dict[str, Any]]:
        context = service._assemble_advisor_facts(financial_summary, **facts)
        return [item.model_dump() for item in service._build_advisor_suggestions(context)]

    expected = suggestions_for(reconciliation)
    assert {item["confidence_tier"] for item in expected} == {"blocked", "review_required", "stale", "deterministic"}
    for value in ("N/A", "", "SGD 0.00", "SGD -999999.00", "SGD 999999.00", "LOW", "UNAVAILABLE"):
        assert suggestions_for({**{key: value for key in other_keys}, **reconciliation}) == expected, value
    # Each field gets its own value, so a rule that compares two fields also sees a change.
    for offset in range(len(other_keys)):
        distinct = {key: f"SGD {(index + offset) * 1000 - 3000}.00" for index, key in enumerate(sorted(other_keys))}
        assert suggestions_for({**distinct, **reconciliation}) == expected, distinct
    assert suggestions_for(summary) == expected
