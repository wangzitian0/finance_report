"""Keep the traceability appendix builder linear and its output unchanged (#2583 S1).

Five GET endpoints build the appendix, and one of them is polled every 30 s.
The builder ran in O(n^2) per report line before #2583: about 2 s of CPU at
960 transactions, which blocked the single event loop.
"""

from __future__ import annotations

import json
import time
from datetime import date
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import UUID

import pytest

from src.audit import TraceDecisionRef, VersionedTraceRef
from src.extraction import StatementSourceType
from src.ledger import AccountType, Direction, JournalLineContribution, ResolvedJournalContribution
from src.pricing import (
    ManualValuationBasis,
    ManualValuationComponentType,
    ManualValuationLiquidityClass,
    PriceSource,
)
from src.reporting import PackageSectionContribution, build_personal_report_package_traceability_payload

GOLDEN_PATH = Path(__file__).resolve().parents[1] / "fixtures" / "traceability_appendix_golden.json"
LINEAR_CONTRIBUTIONS = 5000
LINEAR_BUDGET_SECONDS = 0.100
LINEAR_ATTEMPTS = 3
ALL_PERIOD_SECTIONS = (
    "traceability_appendix",
    "balance_sheet",
    "cash_flow",
    "income_statement",
    "annualized_income_long_term",
)


@pytest.fixture(autouse=True)
def patch_database_connection():
    """The builder is a pure function. These tests do not use the test database."""
    yield


def _decision(number: int) -> TraceDecisionRef:
    return TraceDecisionRef(
        decision_id=UUID(int=number),
        target=VersionedTraceRef(kind="package_input", id=f"target-{number}", version="1"),
        assertion=VersionedTraceRef(kind="package_input_assertion", id=f"assertion-{number}", version="1"),
    )


def _contribution(
    contribution_type: Any,
    section_ids: tuple[Any, ...],
    payload: Any,
    *,
    input_refs: tuple[str, ...],
    decision: TraceDecisionRef | None = None,
) -> PackageSectionContribution[Any]:
    return PackageSectionContribution(
        contribution_type=contribution_type,
        section_ids=section_ids,
        payload=payload,
        state="authoritative" if decision is not None else "unproven",
        decision=decision,
        input_refs=input_refs,
        reason_code=None if decision is not None else "missing_current_decision_anchor",
    )


def _journal(
    entry_number: int,
    lines: tuple[tuple[int, AccountType, str], ...],
    section_ids: tuple[Any, ...],
    *,
    decision: TraceDecisionRef | None = None,
) -> PackageSectionContribution[Any]:
    journal = ResolvedJournalContribution(
        entry_id=UUID(int=entry_number),
        entry_date=date(2026, 5, 31),
        lines=tuple(
            JournalLineContribution(
                line_id=UUID(int=line_number),
                account_id=UUID(int=line_number + 1000),
                account_type=account_type,
                direction=Direction.DEBIT,
                amount=Decimal(amount),
                currency="SGD",
            )
            for line_number, account_type, amount in lines
        ),
        state="authoritative" if decision is not None else "unproven",
        reason_code=None if decision is not None else "missing_current_decision_anchor",
        decision=decision,
    )
    return _contribution("ledger_command", section_ids, journal, input_refs=journal.input_refs, decision=decision)


def _mixed_contributions() -> tuple[PackageSectionContribution[Any], ...]:
    """Cover every contribution type, duplicates, first-occurrence conflicts and empty filters.

    Detail insertion order differs from sorted identifier order on purpose.
    """
    statement_a = _contribution(
        "statement_source",
        ALL_PERIOD_SECTIONS,
        SimpleNamespace(source_result=SimpleNamespace(source_type=StatementSourceType.BANK, statement_currency="SGD")),
        input_refs=("statement_result:0003", "statement_result:0001"),
        decision=_decision(101),
    )
    statement_b = _contribution(
        "statement_source",
        ("traceability_appendix", "balance_sheet"),
        SimpleNamespace(source_result=None),
        input_refs=("statement_result:0001", "statement_result:0002"),
    )
    property_valuation = _contribution(
        "valuation",
        ("balance_sheet", "annualized_income_long_term", "traceability_appendix"),
        SimpleNamespace(
            source=PriceSource.MANUAL,
            value=Decimal("850000.00"),
            currency="SGD",
            component_type=ManualValuationComponentType.PROPERTY_VALUE,
            valuation_basis=ManualValuationBasis.MARKET_APPRAISAL,
            liquidity_class=ManualValuationLiquidityClass.ILLIQUID,
        ),
        input_refs=("manual_valuation:0010",),
        decision=_decision(102),
    )
    security_valuation = _contribution(
        "valuation",
        ("balance_sheet", "investment_performance", "traceability_appendix"),
        SimpleNamespace(
            source=None,
            value=Decimal("1234.5600"),
            currency="USD",
            component_type=None,
            valuation_basis=None,
            liquidity_class=ManualValuationLiquidityClass.LIQUID,
        ),
        input_refs=("market_valuation:0011",),
    )
    opening = _contribution(
        "opening_position",
        ("balance_sheet", "cash_flow", "traceability_appendix"),
        SimpleNamespace(account_id=UUID(int=201), amount=Decimal("1000.00"), currency="SGD"),
        input_refs=(f"opening_position:{UUID(int=201)}",),
        decision=_decision(103),
    )
    return (
        statement_a,
        statement_a,
        statement_b,
        property_valuation,
        security_valuation,
        opening,
        _journal(
            301,
            ((409, AccountType.ASSET, "100.00"), (408, AccountType.INCOME, "100.00")),
            ALL_PERIOD_SECTIONS,
            decision=_decision(104),
        ),
        _journal(302, ((403, AccountType.EXPENSE, "25.50"), (404, AccountType.ASSET, "25.50")), ALL_PERIOD_SECTIONS),
        _journal(
            303, ((405, AccountType.LIABILITY, "60.00"),), ("balance_sheet", "cash_flow"), decision=_decision(105)
        ),
        _journal(304, ((409, AccountType.ASSET, "999.00"),), ("balance_sheet",)),
    )


def _canonical(value: Any) -> str:
    """Serialize with key order kept, and with the Python type of each non-JSON value."""
    return json.dumps(value, indent=1, default=lambda item: f"{type(item).__name__}:{item}") + "\n"


async def _golden_payloads() -> dict[str, Any]:
    return {
        "empty": await build_personal_report_package_traceability_payload(contributions=()),
        "mixed": await build_personal_report_package_traceability_payload(contributions=_mixed_contributions()),
        # A liability-only journal on the income lines: both ledger anchors get empty detail lists.
        "filtered_empty": await build_personal_report_package_traceability_payload(
            contributions=(_journal(501, ((502, AccountType.LIABILITY, "7.00"),), ("income_statement",)),),
        ),
    }


async def test_AC_reporting_package_traceability_5_output_equals_pre_change_golden() -> None:
    """AC-reporting.package-traceability.5: the linear builder returns the pre-#2583 output byte for byte.

    The golden file is the output of the quadratic builder at main 83352b22.
    It fixes detail order (first occurrence wins), sorted identifiers, anchor
    counts, blocker codes, key order and value types.
    """
    payloads = await _golden_payloads()
    mixed_lines = {line["line_id"]: line for line in payloads["mixed"]["lines"]}
    assets_ledger = mixed_lines["balance_sheet.total_assets"]["ledger_anchor"]
    first_line_409 = next(d for d in assets_ledger["details"] if d["identifier"] == f"journal_line:{UUID(int=409)}")
    assert first_line_409["amount"] == Decimal("100.00")
    assert assets_ledger["identifiers"] == sorted(assets_ledger["identifiers"])
    assert [d["identifier"] for d in assets_ledger["details"]] != assets_ledger["identifiers"]

    assert _canonical(payloads) == GOLDEN_PATH.read_text()


async def test_AC_reporting_package_traceability_6_builder_is_linear_in_contributions() -> None:
    """AC-reporting.package-traceability.6: 5000 contributions on one report line build in less than 100 ms."""
    contributions = tuple(
        _journal(10_000 + number, ((20_000 + number, AccountType.ASSET, "1.00"),), ("balance_sheet",))
        for number in range(LINEAR_CONTRIBUTIONS)
    )

    timings: list[float] = []
    for _ in range(LINEAR_ATTEMPTS):
        started = time.perf_counter()
        payload = await build_personal_report_package_traceability_payload(contributions=contributions)
        timings.append(time.perf_counter() - started)
        if timings[-1] < LINEAR_BUDGET_SECONDS:
            break

    assets = {line["line_id"]: line for line in payload["lines"]}["balance_sheet.total_assets"]
    assert len(assets["ledger_anchor"]["details"]) == LINEAR_CONTRIBUTIONS
    assert len(assets["ledger_anchor"]["identifiers"]) == LINEAR_CONTRIBUTIONS
    assert assets["anchor_count"] == LINEAR_CONTRIBUTIONS
    assert min(timings) < LINEAR_BUDGET_SECONDS, f"builder took {[round(t * 1000, 1) for t in timings]} ms"
