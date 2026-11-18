from __future__ import annotations

import sys
import time
from contextlib import contextmanager
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from uuid import UUID

import pytest

from src.audit import TraceDecisionRef, VersionedTraceRef
from src.extraction import StatementSourceType
from src.ledger import AccountType, Direction, JournalLineContribution, ResolvedJournalContribution
from src.pricing import ManualValuationBasis, ManualValuationComponentType, ManualValuationLiquidityClass, PriceSource
from src.reporting import PackageSectionContribution, build_personal_report_package_traceability_payload

LINEAR_CONTRIBUTIONS = 5000
LINEAR_BUDGET_SECONDS = 0.1
ALL_SECTIONS = (
    "traceability_appendix",
    "balance_sheet",
    "cash_flow",
    "income_statement",
    "annualized_income_long_term",
)


@pytest.fixture(autouse=True)
def patch_database_connection():
    yield


def _dec(n: int) -> TraceDecisionRef:
    return TraceDecisionRef(
        decision_id=UUID(int=n),
        target=VersionedTraceRef("package_input", f"t-{n}", "1"),
        assertion=VersionedTraceRef("package_input_assertion", f"a-{n}", "1"),
    )


def _contrib(kind: str, secs: tuple[str, ...], payload, *, refs: tuple[str, ...], dec: TraceDecisionRef | None = None):
    return PackageSectionContribution(
        contribution_type=kind,
        section_ids=secs,
        payload=payload,
        state="authoritative" if dec else "unproven",
        decision=dec,
        input_refs=refs,
        reason_code=None if dec else "missing_current_decision_anchor",
    )


def _journal(
    n: int,
    lines: tuple[tuple[int, AccountType, str], ...],
    secs: tuple[str, ...],
    *,
    dec: TraceDecisionRef | None = None,
):
    j = ResolvedJournalContribution(
        entry_id=UUID(int=n),
        entry_date=date(2026, 5, 31),
        lines=tuple(
            JournalLineContribution(
                line_id=UUID(int=ln),
                account_id=UUID(int=ln + 1000),
                account_type=at,
                direction=Direction.DEBIT,
                amount=Decimal(amt),
                currency="SGD",
            )
            for ln, at, amt in lines
        ),
        state="authoritative" if dec else "unproven",
        reason_code=None if dec else "missing_current_decision_anchor",
        decision=dec,
    )
    return _contrib("ledger_command", secs, j, refs=j.input_refs, dec=dec)


@contextmanager
def _without_line_tracer():
    tracer = sys.gettrace()
    sys.settrace(None)
    try:
        yield
    finally:
        sys.settrace(tracer)


async def test_AC_reporting_package_traceability_5_structure_and_ordering() -> None:
    empty = await build_personal_report_package_traceability_payload(contributions=())
    assert empty["lines"] and all(
        not (line.get("ledger_anchor") or {}).get("details") and not line.get("input_refs") for line in empty["lines"]
    )
    filtered = await build_personal_report_package_traceability_payload(
        contributions=(_journal(501, ((502, AccountType.LIABILITY, "7.00"),), ("income_statement",)),)
    )
    assert all(not (line.get("ledger_anchor") or {}).get("details") for line in filtered["lines"])

    stmt_a = _contrib(
        "statement_source",
        ALL_SECTIONS,
        SimpleNamespace(source_result=SimpleNamespace(source_type=StatementSourceType.BANK, statement_currency="SGD")),
        refs=("statement_result:0003", "statement_result:0001"),
        dec=_dec(101),
    )
    mixed = await build_personal_report_package_traceability_payload(
        contributions=(
            stmt_a,
            stmt_a,
            _contrib(
                "statement_source",
                ("traceability_appendix", "balance_sheet"),
                SimpleNamespace(source_result=None),
                refs=("statement_result:0001", "statement_result:0002"),
            ),
            _contrib(
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
                refs=("manual_valuation:0010",),
                dec=_dec(102),
            ),
            _contrib(
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
                refs=("market_valuation:0011",),
            ),
            _contrib(
                "opening_position",
                ("balance_sheet", "cash_flow", "traceability_appendix"),
                SimpleNamespace(account_id=UUID(int=201), amount=Decimal("1000.00"), currency="SGD"),
                refs=(f"opening_position:{UUID(int=201)}",),
                dec=_dec(103),
            ),
            _journal(
                301,
                ((409, AccountType.ASSET, "100.00"), (408, AccountType.INCOME, "100.00")),
                ALL_SECTIONS,
                dec=_dec(104),
            ),
            _journal(302, ((403, AccountType.EXPENSE, "25.50"), (404, AccountType.ASSET, "25.50")), ALL_SECTIONS),
            _journal(303, ((405, AccountType.LIABILITY, "60.00"),), ("balance_sheet", "cash_flow"), dec=_dec(105)),
            _journal(304, ((409, AccountType.ASSET, "999.00"),), ("balance_sheet",)),
        )
    )
    lines = {line["line_id"]: line for line in mixed["lines"]}
    assets_ledger = lines["balance_sheet.total_assets"]["ledger_anchor"]
    assert next(d for d in assets_ledger["details"] if d["identifier"] == f"journal_line:{UUID(int=409)}")[
        "amount"
    ] == Decimal("100.00")
    assert (
        assets_ledger["identifiers"] == sorted(assets_ledger["identifiers"])
        and [d["identifier"] for d in assets_ledger["details"]] != assets_ledger["identifiers"]
    )
    assert lines["annualized_income_long_term.restricted_fair_value_total"]["anchor_count"] >= 1


async def test_AC_reporting_package_traceability_6_builder_is_linear_in_contributions() -> None:
    contribs = tuple(
        _journal(10000 + i, ((20000 + i, AccountType.ASSET, "1.00"),), ("balance_sheet",))
        for i in range(LINEAR_CONTRIBUTIONS)
    )
    timings: list[float] = []
    for _ in range(3):
        with _without_line_tracer():
            t0 = time.perf_counter()
            payload = await build_personal_report_package_traceability_payload(contributions=contribs)
            timings.append(time.perf_counter() - t0)
        if timings[-1] < LINEAR_BUDGET_SECONDS:
            break
    assets = {line["line_id"]: line for line in payload["lines"]}["balance_sheet.total_assets"]
    assert (
        len(assets["ledger_anchor"]["details"]),
        len(assets["ledger_anchor"]["identifiers"]),
        assets["anchor_count"],
    ) == (LINEAR_CONTRIBUTIONS, LINEAR_CONTRIBUTIONS, LINEAR_CONTRIBUTIONS)
    assert min(timings) < LINEAR_BUDGET_SECONDS
