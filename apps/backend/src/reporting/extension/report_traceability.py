"""Render the package traceability appendix from typed contribution inputs."""

from __future__ import annotations

from copy import deepcopy
from decimal import Decimal
from typing import Any

from src.reporting.base.package_contribution import PackageSectionContribution
from src.reporting.base.report_package_contract import PERSONAL_REPORT_PACKAGE_TRACEABILITY

_CollectedDetails = dict[tuple[str, str], dict[str, dict[str, str | Decimal | None]]]
_LINE_ACCOUNT_TYPES = {
    "income_statement.total_income": "income",
    "income_statement.total_expenses": "expense",
    "cash_flow.net_cash_flow": "asset",
    "annualized_income_long_term.annualized_total": "income",
}


def _collect_anchor_details(
    collected: _CollectedDetails, line_id: str, anchor_name: str, details: list[dict[str, str | Decimal | None]]
) -> None:
    by_id = collected.setdefault((line_id, anchor_name), {})
    for detail in details:
        if (ident := str(detail.get("identifier") or "")) and ident not in by_id:
            by_id[ident] = detail


def _write_anchor_details(lines_by_id: dict[str, dict[str, Any]], collected: _CollectedDetails) -> None:
    for (line_id, anchor_name), by_id in collected.items():
        anchor = lines_by_id[line_id][anchor_name]
        anchor["details"] = list(by_id.values())
        anchor["identifiers"] = sorted(by_id)
    for line_id in dict.fromkeys(line_id for line_id, _ in collected):
        line = lines_by_id[line_id]
        line["anchor_count"] = len(line["source_anchor"].get("identifiers", [])) + len(
            line["ledger_anchor"].get("identifiers", [])
        )


def _detail(
    c: PackageSectionContribution[Any],
    *,
    identifier: str,
    source_kind: str,
    source_id: str,
    source_type: str,
    amount: Decimal | None,
    currency: str | None,
    basis: str,
    reason_after_extra: bool = False,
    **extra: str | Decimal | None,
) -> dict[str, str | Decimal | None]:
    base: dict[str, str | Decimal | None] = {
        "identifier": identifier,
        "source_kind": source_kind,
        "source_id": source_id,
        "source_type": source_type,
        "amount": amount,
        "currency": currency,
        "review_state": "current_authoritative_decision" if c.is_authoritative else "unproven",
        "decision_id": str(c.decision_id) if c.decision_id else None,
        "contribution_basis": basis,
    }
    if reason_after_extra:
        return {**base, **extra, "reason_code": c.reason_code}
    return {**base, "reason_code": c.reason_code, **extra}


def _details_for_line(
    c: PackageSectionContribution[Any], *, line_id: str
) -> tuple[str, list[dict[str, str | Decimal | None]]]:
    if c.contribution_type == "statement_source":
        src = c.payload.source_result
        stype = src.source_type.value if src is not None else "statement_result"
        ccy = src.statement_currency if src is not None else None
        return "source_anchor", [
            _detail(
                c,
                identifier=ref,
                source_kind="statement_extraction_result",
                source_id=ref.partition(":")[2],
                source_type=stype,
                amount=None,
                currency=ccy,
                basis="current_statement_result",
            )
            for ref in c.input_refs
        ]
    if c.contribution_type == "valuation":
        val = c.payload
        stype = val.source.value if val.source is not None else "valuation_observation"
        return "source_anchor", [
            _detail(
                c,
                identifier=ref,
                source_kind="pricing_valuation_observation",
                source_id=ref.partition(":")[2],
                source_type=stype,
                amount=val.value,
                currency=val.currency,
                basis="resolved_pricing_valuation",
                component_type=val.component_type,
                valuation_basis=val.valuation_basis or "unspecified",
                liquidity_class=val.liquidity_class,
            )
            for ref in c.input_refs
        ]
    if c.contribution_type == "opening_position":
        pos = c.payload
        return "ledger_anchor", [
            _detail(
                c,
                identifier=c.input_refs[0],
                source_kind="opening_position",
                source_id=str(pos.account_id),
                source_type="ledger_opening_position",
                amount=pos.amount,
                currency=pos.currency,
                basis="initial_stock",
            )
        ]
    expected_type = _LINE_ACCOUNT_TYPES.get(line_id)
    return "ledger_anchor", [
        _detail(
            c,
            identifier=f"journal_line:{jl.line_id}",
            source_kind="journal_line",
            source_id=str(jl.line_id),
            source_type="decision_anchored_journal",
            amount=jl.amount,
            currency=jl.currency,
            basis="ledger_line_amount",
            reason_after_extra=True,
            journal_entry_id=str(c.payload.entry_id),
            account_id=str(jl.account_id),
            account_type=jl.account_type.value.lower(),
        )
        for jl in c.payload.lines
        if expected_type is None or jl.account_type.value.lower() == expected_type
    ]


async def build_personal_report_package_traceability_payload(
    *, contributions: tuple[PackageSectionContribution[Any], ...]
) -> dict[str, Any]:
    payload = deepcopy(PERSONAL_REPORT_PACKAGE_TRACEABILITY)
    lines_by_id = {line["line_id"]: line for line in payload["lines"]}
    collected: _CollectedDetails = {}
    for line in payload["lines"]:
        line_id, section_id = line["line_id"], line["section_id"]
        for c in contributions:
            if section_id in c.section_ids:
                anchor_name, details = _details_for_line(c, line_id=line_id)
                _collect_anchor_details(collected, line_id, anchor_name, details)
                if not c.is_authoritative:
                    line["blocker_codes"] = sorted({*line.get("blocker_codes", []), "unproven_package_input"})

    _collect_anchor_details(
        collected,
        "notes.non_compliance_statement",
        "source_anchor",
        [
            {
                "identifier": "package_contract:personal-financial-report-package",
                "source_kind": "package_contract",
                "source_id": "personal-financial-report-package",
                "source_type": "static_contract",
                "amount": None,
                "currency": None,
                "review_state": "not_applicable",
                "decision_id": None,
                "contribution_basis": "static_disclosure_contract",
                "reason_code": None,
            }
        ],
    )
    _write_anchor_details(lines_by_id, collected)
    lines_by_id["notes.non_compliance_statement"]["anchor_count"] = len(
        lines_by_id["notes.non_compliance_statement"]["source_anchor"]["identifiers"]
    )
    for line in payload["lines"]:
        sa = line["source_anchor"]
        if sa["state"] == "available" and not sa.get("details"):
            sa["state"] = "unavailable"
            sa["unavailable_reason"] = "no_selected_source_contribution"
    return payload
