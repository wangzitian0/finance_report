"""Render the package traceability appendix from typed contribution inputs.

The appendix is a display projection of the same contribution set that feeds
the package manifest.  It must not rediscover source membership from another
package's ORM or turn a provenance label into an authority decision.
"""

from __future__ import annotations

from copy import deepcopy
from decimal import Decimal
from typing import Any

from src.reporting.base.package_contribution import PackageSectionContribution
from src.reporting.base.report_package_contract import PERSONAL_REPORT_PACKAGE_TRACEABILITY


def _dedupe_identifiers(values: list[str]) -> list[str]:
    return sorted({value for value in values if value})


def _dedupe_details(values: list[dict[str, str | Decimal | None]]) -> list[dict[str, str | Decimal | None]]:
    seen: set[str] = set()
    details: list[dict[str, str | Decimal | None]] = []
    for value in values:
        identifier = str(value.get("identifier") or "")
        if not identifier or identifier in seen:
            continue
        seen.add(identifier)
        details.append(value)
    return details


def _add_anchor_details(
    lines_by_id: dict[str, dict[str, Any]],
    line_id: str,
    anchor_name: str,
    details: list[dict[str, str | Decimal | None]],
) -> None:
    """Attach deduplicated contribution details and maintain the visible count."""
    line = lines_by_id.get(line_id)
    if line is None:
        return
    anchor = line[anchor_name]
    anchor["details"] = _dedupe_details([*anchor.get("details", []), *details])
    anchor["identifiers"] = _dedupe_identifiers(
        [*anchor.get("identifiers", []), *(str(detail["identifier"]) for detail in anchor["details"])]
    )
    line["anchor_count"] = len(line["source_anchor"].get("identifiers", [])) + len(
        line["ledger_anchor"].get("identifiers", [])
    )


def _append_blocker(line: dict[str, Any], blocker_code: str) -> None:
    line["blocker_codes"] = sorted({*line.get("blocker_codes", []), blocker_code})


def _review_state(contribution: PackageSectionContribution[Any]) -> str:
    return "current_authoritative_decision" if contribution.is_authoritative else "unproven"


def _statement_details(contribution: PackageSectionContribution[Any]) -> list[dict[str, str | Decimal | None]]:
    source = contribution.payload.source_result
    source_type = source.source_type.value if source is not None else "statement_result"
    return [
        {
            "identifier": input_ref,
            "source_kind": "statement_extraction_result",
            "source_id": input_ref.partition(":")[2],
            "source_type": source_type,
            "amount": None,
            "currency": source.statement_currency if source is not None else None,
            "review_state": _review_state(contribution),
            "decision_id": str(contribution.decision_id) if contribution.decision_id else None,
            "contribution_basis": "current_statement_result",
            "reason_code": contribution.reason_code,
        }
        for input_ref in contribution.input_refs
    ]


def _valuation_details(contribution: PackageSectionContribution[Any]) -> list[dict[str, str | Decimal | None]]:
    valuation = contribution.payload
    source_type = valuation.source.value if valuation.source is not None else "valuation_observation"
    return [
        {
            "identifier": input_ref,
            "source_kind": "pricing_valuation_observation",
            "source_id": input_ref.partition(":")[2],
            "source_type": source_type,
            "amount": valuation.value,
            "currency": valuation.currency,
            "review_state": _review_state(contribution),
            "decision_id": str(contribution.decision_id) if contribution.decision_id else None,
            "contribution_basis": "resolved_pricing_valuation",
            "reason_code": contribution.reason_code,
            "component_type": valuation.component_type,
            "valuation_basis": valuation.valuation_basis or "unspecified",
            "liquidity_class": valuation.liquidity_class,
        }
        for input_ref in contribution.input_refs
    ]


def _journal_details(
    contribution: PackageSectionContribution[Any],
    *,
    line_id: str,
) -> list[dict[str, str | Decimal | None]]:
    """Render ledger-owned line values without resolving their polymorphic source id."""
    account_type_for_line = {
        "income_statement.total_income": "income",
        "income_statement.total_expenses": "expense",
        "cash_flow.net_cash_flow": "asset",
        "annualized_income_long_term.annualized_total": "income",
    }.get(line_id)
    details: list[dict[str, str | Decimal | None]] = []
    for journal_line in contribution.payload.lines:
        account_type = journal_line.account_type.value.lower()
        if account_type_for_line is not None and account_type != account_type_for_line:
            continue
        details.append(
            {
                "identifier": f"journal_line:{journal_line.line_id}",
                "source_kind": "journal_line",
                "source_id": str(journal_line.line_id),
                "source_type": "decision_anchored_journal",
                "amount": journal_line.amount,
                "currency": journal_line.currency,
                "review_state": _review_state(contribution),
                "decision_id": str(contribution.decision_id) if contribution.decision_id else None,
                "contribution_basis": "ledger_line_amount",
                "journal_entry_id": str(contribution.payload.entry_id),
                "account_id": str(journal_line.account_id),
                "account_type": account_type,
                "reason_code": contribution.reason_code,
            }
        )
    return details


def _details_for_line(
    contribution: PackageSectionContribution[Any],
    *,
    line_id: str,
) -> tuple[str, list[dict[str, str | Decimal | None]]]:
    if contribution.contribution_type == "statement_source":
        return "source_anchor", _statement_details(contribution)
    if contribution.contribution_type == "valuation":
        return "source_anchor", _valuation_details(contribution)
    return "ledger_anchor", _journal_details(contribution, line_id=line_id)


async def build_personal_report_package_traceability_payload(
    *,
    contributions: tuple[PackageSectionContribution[Any], ...],
) -> dict[str, Any]:
    """Build an appendix strictly from package-facing contribution DTOs.

    An unproven contribution remains visible, with its reason, but the caller
    must fold it into readiness separately.  This renderer cannot grant trust.
    """
    payload = deepcopy(PERSONAL_REPORT_PACKAGE_TRACEABILITY)
    lines_by_id = {line["line_id"]: line for line in payload["lines"]}
    for line in payload["lines"]:
        line_id = line["line_id"]
        section_id = line["section_id"]
        for contribution in contributions:
            if section_id not in contribution.section_ids:
                continue
            anchor_name, details = _details_for_line(contribution, line_id=line_id)
            _add_anchor_details(lines_by_id, line_id, anchor_name, details)
            if not contribution.is_authoritative:
                _append_blocker(line, "unproven_package_input")

    notes_line = lines_by_id["notes.non_compliance_statement"]
    _add_anchor_details(
        lines_by_id,
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
    notes_line["anchor_count"] = len(notes_line["source_anchor"]["identifiers"])
    return payload
