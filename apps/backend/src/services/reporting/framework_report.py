"""Framework-aware statement assembly and exact aggregation logic."""

from __future__ import annotations

import structlog
from datetime import date, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from src.models.account import AccountType
from src.schemas.reporting import PersonalReportingFrameworkId, ReportLineId
from src.services.framework_policy import derive_user_framework_policy_result
from src.services.reporting.balance_sheet import generate_balance_sheet
from src.services.reporting.income_statement import generate_income_statement
from src.services.reporting.l1_registry import get_framework_ordered_lines, is_valid_line_for_framework
from src.services.reporting_calc import _combine_provenance, _quantize_money, _worst_confidence_tier

logger = structlog.get_logger(__name__)


def _map_l2_line(
    line: dict[str, Any],
    decisions_by_source_id: dict[str, Any],
    framework_id: PersonalReportingFrameworkId,
    statement: str,
) -> str:
    """Map a raw L2 report line to a registered L1 ReportLineId using policy result decisions."""
    line_type = line.get("type")
    source_type = line.get("allocation_source_type")
    account_id = line.get("account_id")

    # 1. Try to map via matching policy result decision by source_id anchor
    if account_id:
        acc_str = str(account_id)
        if acc_str in decisions_by_source_id:
            mapped_line = decisions_by_source_id[acc_str].line_mappings.get(statement)
            if mapped_line and is_valid_line_for_framework(mapped_line, framework_id):
                return mapped_line

    # 2. Try to map portfolio adjustments
    if source_type == "portfolio_market_adjustment":
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

    # 3. Fallback logic based on section/type
    if statement == "balance_sheet":
        if line_type == AccountType.ASSET:
            return ReportLineId.CASH_AND_CASH_EQUIVALENTS.value
        elif line_type == AccountType.LIABILITY:
            return ReportLineId.FINANCIAL_LIABILITIES.value
        else:
            return ReportLineId.FX_TRANSLATION.value
    elif statement == "income_statement":
        if line_type == AccountType.INCOME:
            return ReportLineId.DIVIDENDS_AND_INTEREST.value
        else:
            return ReportLineId.INVESTMENT_FEES.value
    elif statement == "cash_flow":
        if line_type == AccountType.EXPENSE:
            return ReportLineId.INVESTING_FEES.value
        else:
            return ReportLineId.ENDING_CASH.value

    logger.warning(
        "unmapped_l2_line_fallback",
        statement=statement,
        line_type=str(line_type),
        source_type=source_type,
        msg="L2 line did not match any known statement; defaulting to cash",
    )
    return ReportLineId.CASH_AND_CASH_EQUIVALENTS.value


async def assemble_framework_balance_sheet(
    db: AsyncSession,
    user_id: UUID,
    *,
    framework_id: PersonalReportingFrameworkId,
    as_of_date: date,
    currency: str | None = None,
    include_restricted: bool = False,
) -> dict[str, Any]:
    """Assemble a framework-ordered and framework-categorized balance sheet.

    Exactly aggregates the raw L2 balance sheet lines onto the L1 registry lines
    applicable to the framework. Missing lines are present but set to 0.00.
    """
    raw_bs = await generate_balance_sheet(
        db,
        user_id,
        as_of_date=as_of_date,
        currency=currency,
        include_restricted=include_restricted,
        include_trust_signals=True,
        include_allocation_metadata=True,
    )

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

    raw_lines = [*raw_bs["assets"], *raw_bs["liabilities"], *raw_bs["equity"]]
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

        confidence_tier = _worst_confidence_tier([c.get("confidence_tier") for c in contributors])
        provenance = _combine_provenance([c.get("provenance") for c in contributors])

        line_dict = {
            "account_id": UUID(int=0),  # Synthetic L1 consolidated line ID
            "name": reg.label,
            "type": AccountType.ASSET
            if reg.section == "assets"
            else (AccountType.LIABILITY if reg.section == "liabilities" else AccountType.EQUITY),
            "parent_id": None,
            "amount": _quantize_money(amount),
            "confidence_tier": confidence_tier,
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
        "confidence_tier": raw_bs.get("confidence_tier"),
        "provenance": raw_bs.get("provenance"),
        "total_assets": _quantize_money(total_assets),
        "total_liabilities": _quantize_money(total_liabilities),
        "total_equity": _quantize_money(total_equity),
        "net_income": net_income,
        "unrealized_fx_gain_loss": unrealized_fx,
        "net_worth_adjustment_gain_loss": net_worth_adjustment,
        "fx_warnings": raw_bs.get("fx_warnings", []),
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
) -> dict[str, Any]:
    """Assemble a framework-ordered and framework-categorized income statement."""
    raw_is = await generate_income_statement(
        db,
        user_id,
        start_date=start_date,
        end_date=end_date,
        currency=currency,
    )

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

        confidence_tier = _worst_confidence_tier([c.get("confidence_tier") for c in contributors])
        provenance = _combine_provenance([c.get("provenance") for c in contributors])

        line_dict = {
            "account_id": UUID(int=0),
            "name": reg.label,
            "type": AccountType.INCOME if reg.section == "income" else AccountType.EXPENSE,
            "parent_id": None,
            "amount": _quantize_money(amount),
            "confidence_tier": confidence_tier,
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
