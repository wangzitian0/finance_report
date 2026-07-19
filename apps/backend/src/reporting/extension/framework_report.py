"""Framework-aware statement assembly and exact aggregation logic."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from typing import Any, cast
from uuid import UUID, uuid5

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from src.ledger import AccountType
from src.reporting.base.l1_registry import get_framework_ordered_lines, is_valid_line_for_framework
from src.reporting.base.types import PersonalReportingFrameworkId, ReportLineId
from src.reporting.extension.balance_sheet import generate_balance_sheet
from src.reporting.extension.framework_policy import derive_user_framework_policy_result
from src.reporting.extension.income_statement import generate_income_statement
from src.reporting.extension.portfolio_market import _portfolio_market_basis_by_account
from src.reporting.extension.reporting_calc import (
    ReportError,
    _combine_provenance,
    _quantize_money,
)

logger = structlog.get_logger(__name__)

# Deterministic namespace for L1 consolidated line UUIDs.
_L1_NAMESPACE = UUID("a1b2c3d4-e5f6-7890-abcd-ef1234567890")
_VALID_STATEMENT_TARGETS = frozenset({"balance_sheet", "income_statement", "cash_flow", "notes"})
_PORTFOLIO_L1_SOURCE_TYPES = frozenset({"portfolio_market_adjustment", "portfolio_cost_basis"})


def _stable_line_uuid(line_id: str) -> UUID:
    """Return a deterministic UUID5 for a given L1 line ID, stable across runs."""
    return uuid5(_L1_NAMESPACE, line_id)


def _map_l2_line(
    line: dict[str, Any],
    decisions_by_source_id: dict[str, Any],
    framework_id: PersonalReportingFrameworkId,
    statement: str,
) -> str:
    """Map a raw L2 report line to a registered L1 ReportLineId using policy result decisions."""
    if statement not in _VALID_STATEMENT_TARGETS:
        raise ReportError(f"Unsupported framework report statement '{statement}'")

    line_type = line.get("type")
    source_type = line.get("allocation_source_type")
    account_id = line.get("account_id")

    # 1. Portfolio L2 lines have deterministic framework presentation. They may
    # carry the broker account_id, so this must run before account-anchor mapping.
    if source_type in _PORTFOLIO_L1_SOURCE_TYPES:
        if statement == "balance_sheet":
            if framework_id == PersonalReportingFrameworkId.US_GAAP_LIKE:
                return ReportLineId.MARKETABLE_SECURITIES.value
            else:
                return ReportLineId.FINANCIAL_ASSETS_AT_FAIR_VALUE.value
        elif statement == "income_statement":
            if framework_id == PersonalReportingFrameworkId.US_GAAP_LIKE:
                return ReportLineId.UNREALIZED_INVESTMENT_GAIN_LOSS.value
            else:
                return ReportLineId.FAIR_VALUE_CHANGE_IN_FINANCIAL_ASSETS.value

    # 2. Try to map via matching policy result decision by source_id anchor.
    if account_id:
        acc_str = str(account_id)
        if acc_str in decisions_by_source_id:
            mapped_line = decisions_by_source_id[acc_str].line_mappings.get(statement)
            if mapped_line and is_valid_line_for_framework(mapped_line, framework_id):
                return mapped_line
            if mapped_line:
                raise ReportError(
                    f"Policy mapped source {acc_str} to invalid L1 line '{mapped_line}' for {framework_id.value}"
                )

    # 3. Equity is still framework-neutral in v1; the current registry has one
    # equity line, so keep this structural mapping explicit instead of guessing.
    if statement == "balance_sheet" and line_type == AccountType.EQUITY:
        return ReportLineId.FX_TRANSLATION.value

    raise ReportError(
        f"No registered L1 mapping for {statement} line "
        f"source_type={source_type!r} account_id={account_id!s} line_type={line_type!s}"
    )


async def _split_portfolio_cost_basis_lines(
    db: AsyncSession,
    user_id: UUID,
    *,
    as_of_date: date,
    target_currency: str,
    asset_lines: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Split broker ledger assets into securities cost basis plus residual cash.

    The base balance sheet carries broker account balances as ledger asset lines
    and adds only the market-value delta as a separate portfolio adjustment. L1
    framework statements need the full securities line, so the ledger cost basis
    portion must follow the portfolio line while any residual broker cash stays
    in cash.
    """
    portfolio_basis_by_account = await _portfolio_market_basis_by_account(
        db,
        user_id,
        as_of_date=as_of_date,
        target_currency=target_currency,
    )
    if not portfolio_basis_by_account:
        return asset_lines

    split_lines: list[dict[str, Any]] = []
    for line in asset_lines:
        source_type = line.get("allocation_source_type")
        account_id = line.get("account_id")
        basis = portfolio_basis_by_account.get(account_id) if isinstance(account_id, UUID) else None
        amount = _quantize_money(Decimal(str(line["amount"])))
        cost_basis = _quantize_money(Decimal(str(basis["cost_basis"]))) if basis is not None else Decimal("0.00")

        if (
            line.get("type") != AccountType.ASSET
            or source_type != "ledger_account"
            or basis is None
            or cost_basis <= Decimal("0.00")
            or amount < cost_basis
        ):
            split_lines.append(line)
            continue

        cost_basis_line = dict(line)
        cost_basis_line.update(
            {
                "name": f"{line['name']} ledger cost basis",
                "amount": cost_basis,
                "allocation_asset_class": "public_equity",
                "allocation_source_type": "portfolio_cost_basis",
            }
        )
        split_lines.append(cost_basis_line)

        residual = _quantize_money(amount - cost_basis)
        if residual != Decimal("0.00"):
            residual_line = dict(line)
            residual_line["amount"] = residual
            split_lines.append(residual_line)

    return split_lines


async def assemble_framework_balance_sheet(
    db: AsyncSession,
    user_id: UUID,
    *,
    framework_id: PersonalReportingFrameworkId,
    as_of_date: date,
    currency: str | None = None,
    include_restricted: bool = False,
    decisions_by_source_id: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Assemble a framework-ordered and framework-categorized balance sheet.

    Exactly aggregates the raw L2 balance sheet lines onto the L1 registry lines
    applicable to the framework. Missing lines are present but set to 0.00.

    If ``decisions_by_source_id`` is provided it is reused as-is, avoiding a
    redundant ``derive_user_framework_policy_result`` DB call (the router
    typically already has the policy result for the snapshot payload).
    """
    raw_bs = cast(
        dict[str, Any],
        await generate_balance_sheet(
            db,
            user_id,
            as_of_date=as_of_date,
            currency=currency,
            include_restricted=include_restricted,
            include_trust_signals=True,
            include_allocation_metadata=True,
        ),
    )

    if decisions_by_source_id is None:
        policy = await derive_user_framework_policy_result(
            db,
            user_id,
            framework_id=framework_id,
            # Approximate 1-year lookback for policy derivation context.
            # Not calendar-year precise for leap years, but sufficient for policy matching.
            report_period_start=as_of_date - timedelta(days=365),
            report_period_end=as_of_date,
            as_of_date=as_of_date,
        )
        decisions_by_source_id = {}
        for decision in policy.decisions:
            for anchor in decision.evidence_anchors:
                decisions_by_source_id[str(anchor.source_id)] = decision

    asset_lines = await _split_portfolio_cost_basis_lines(
        db,
        user_id,
        as_of_date=as_of_date,
        target_currency=str(raw_bs["currency"]),
        asset_lines=list(raw_bs["assets"]),
    )
    raw_lines = [*asset_lines, *raw_bs["liabilities"], *raw_bs["equity"]]
    mapped_groups: dict[str, list[dict[str, Any]]] = {}
    for line in raw_lines:
        l1_line = _map_l2_line(line, decisions_by_source_id, framework_id, "balance_sheet")
        mapped_groups.setdefault(l1_line, []).append(line)

    registry_lines = get_framework_ordered_lines(framework_id, "balance_sheet")

    assets_list: list[dict[str, Any]] = []
    liabilities_list: list[dict[str, Any]] = []
    equity_list: list[dict[str, Any]] = []

    for reg in registry_lines:
        contributors = mapped_groups.get(reg.line_id.value, [])
        amount = sum((c["amount"] for c in contributors), Decimal("0.00"))

        provenance = _combine_provenance([c.get("provenance") for c in contributors])

        line_dict = {
            "account_id": _stable_line_uuid(reg.line_id.value),
            "name": reg.label,
            "type": AccountType.ASSET
            if reg.section == "assets"
            else (AccountType.LIABILITY if reg.section == "liabilities" else AccountType.EQUITY),
            "parent_id": None,
            "amount": _quantize_money(amount),
            "provenance": provenance,
            "line_id": reg.line_id.value,
        }

        if reg.section == "assets":
            assets_list.append(line_dict)
        elif reg.section == "liabilities":
            liabilities_list.append(line_dict)
        else:
            equity_list.append(line_dict)

    total_assets = sum((line["amount"] for line in assets_list), Decimal("0.00"))
    total_liabilities = sum((line["amount"] for line in liabilities_list), Decimal("0.00"))
    total_equity = sum((line["amount"] for line in equity_list), Decimal("0.00"))

    net_income = raw_bs.get("net_income", Decimal("0.00"))
    unrealized_fx = raw_bs.get("unrealized_fx_gain_loss", Decimal("0.00"))
    net_worth_adjustment = raw_bs.get("net_worth_adjustment_gain_loss", Decimal("0.00"))

    total_liab_equity_inc = total_liabilities + total_equity + net_income + unrealized_fx + net_worth_adjustment
    equation_delta = _quantize_money(total_assets - total_liab_equity_inc)

    return {
        "as_of_date": as_of_date,
        "currency": raw_bs["currency"],
        "assets": assets_list,
        "liabilities": liabilities_list,
        "equity": equity_list,
        "provenance": raw_bs.get("provenance"),
        "total_assets": _quantize_money(total_assets),
        "total_liabilities": _quantize_money(total_liabilities),
        "total_equity": _quantize_money(total_equity),
        "net_income": net_income,
        "unrealized_fx_gain_loss": unrealized_fx,
        "net_worth_adjustment_gain_loss": net_worth_adjustment,
        "fx_warnings": raw_bs.get("fx_warnings", []),
        "portfolio_warnings": raw_bs.get("portfolio_warnings", []),
        "opening_balance_warnings": raw_bs.get("opening_balance_warnings", []),
        "equation_delta": equation_delta,
        "is_balanced": abs(equation_delta) < Decimal("0.01"),
    }


async def assemble_framework_income_statement(
    db: AsyncSession,
    user_id: UUID,
    *,
    framework_id: PersonalReportingFrameworkId,
    start_date: date,
    end_date: date,
    currency: str | None = None,
    decisions_by_source_id: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Assemble a framework-ordered and framework-categorized income statement."""
    raw_is = cast(
        dict[str, Any],
        await generate_income_statement(
            db,
            user_id,
            start_date=start_date,
            end_date=end_date,
            currency=currency,
        ),
    )

    if decisions_by_source_id is None:
        policy = await derive_user_framework_policy_result(
            db,
            user_id,
            framework_id=framework_id,
            report_period_start=start_date,
            report_period_end=end_date,
            as_of_date=end_date,
        )
        decisions_by_source_id = {}
        for decision in policy.decisions:
            for anchor in decision.evidence_anchors:
                decisions_by_source_id[str(anchor.source_id)] = decision

    raw_lines = [*raw_is["income"], *raw_is["expenses"]]
    mapped_groups: dict[str, list[dict[str, Any]]] = {}
    for line in raw_lines:
        l1_line = _map_l2_line(line, decisions_by_source_id, framework_id, "income_statement")
        mapped_groups.setdefault(l1_line, []).append(line)

    registry_lines = get_framework_ordered_lines(framework_id, "income_statement")

    income_list: list[dict[str, Any]] = []
    expenses_list: list[dict[str, Any]] = []

    for reg in registry_lines:
        contributors = mapped_groups.get(reg.line_id.value, [])
        amount = sum((c["amount"] for c in contributors), Decimal("0.00"))

        provenance = _combine_provenance([c.get("provenance") for c in contributors])

        line_dict = {
            "account_id": _stable_line_uuid(reg.line_id.value),
            "name": reg.label,
            "type": AccountType.INCOME if reg.section == "income" else AccountType.EXPENSE,
            "parent_id": None,
            "amount": _quantize_money(amount),
            "provenance": provenance,
            "line_id": reg.line_id.value,
        }

        if reg.section == "income":
            income_list.append(line_dict)
        else:
            expenses_list.append(line_dict)

    total_income = sum((line["amount"] for line in income_list), Decimal("0.00"))
    total_expenses = sum((line["amount"] for line in expenses_list), Decimal("0.00"))
    net_income = _quantize_money(total_income - total_expenses)

    return {
        "start_date": start_date,
        "end_date": end_date,
        "currency": raw_is["currency"],
        "income": income_list,
        "expenses": expenses_list,
        "total_income": _quantize_money(total_income),
        "total_expenses": _quantize_money(total_expenses),
        "net_income": net_income,
        "unrealized_fx_gain_loss": raw_is.get("unrealized_fx_gain_loss", Decimal("0.00")),
        "comprehensive_income": _quantize_money(net_income + raw_is.get("unrealized_fx_gain_loss", Decimal("0.00"))),
        "fx_warnings": raw_is.get("fx_warnings", []),
        "trends": raw_is.get("trends", []),
        "classification_breakdown": raw_is.get("classification_breakdown", []),
    }
