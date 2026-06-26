"""Manual valuation report-line adjustment (legacy net-worth side-channel)."""

from __future__ import annotations

from datetime import date
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from src.logger import get_logger
from src.models.account import AccountType
from src.models.layer3 import (
    ManualValuationComponentType,
    ManualValuationLiquidityClass,
)
from src.services.assets import AssetService
from src.services.fx import (
    FxRateError,
    convert_amount,
)
from src.services.reporting._core import _valuation_line_name
from src.services.reporting_calc import (
    ReportError,
    _quantize_money,
)

logger = get_logger(__name__)


def _manual_valuation_allocation_asset_class(component_type: str) -> str:
    if component_type in {
        ManualValuationComponentType.PROPERTY_VALUE.value,
        ManualValuationComponentType.MORTGAGE_BALANCE.value,
    }:
        return "real_estate"
    if component_type in {
        ManualValuationComponentType.CPF_BALANCE.value,
        ManualValuationComponentType.RETIREMENT_ACCOUNT.value,
        ManualValuationComponentType.SOCIAL_SECURITY_PERSONAL_ACCOUNT.value,
        ManualValuationComponentType.LONG_TERM_BENEFIT_ASSET.value,
        ManualValuationComponentType.LONG_TERM_SAVINGS.value,
        ManualValuationComponentType.INSURANCE_CASH_VALUE.value,
    }:
        return "retirement_and_benefit_assets"
    if component_type in {
        ManualValuationComponentType.ESOP.value,
        ManualValuationComponentType.RSU.value,
        ManualValuationComponentType.STOCK_OPTIONS.value,
    }:
        return "restricted_comp"
    if component_type == ManualValuationComponentType.TAX_REFUND.value:
        return "cash"
    if component_type in {
        ManualValuationComponentType.TAX_PAYABLE.value,
        ManualValuationComponentType.OTHER_LIABILITY.value,
    }:
        return "liability"
    return "other"


async def _build_manual_valuation_lines(
    db: AsyncSession,
    user_id: UUID,
    *,
    as_of_date: date,
    target_currency: str,
    include_restricted: bool = True,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Build balance sheet lines from latest manual valuation components."""
    components = await AssetService().get_latest_valuation_components(
        db,
        user_id,
        as_of_date=as_of_date,
        include_restricted=include_restricted,
    )
    asset_lines: list[dict[str, Any]] = []
    liability_lines: list[dict[str, Any]] = []

    for component in components.items:
        amount = component.value
        source_currency = component.currency.upper()
        if source_currency != target_currency:
            try:
                amount = await convert_amount(
                    db,
                    amount=amount,
                    currency=source_currency,
                    target_currency=target_currency,
                    rate_date=as_of_date,
                    lazy_load=True,
                )
            except FxRateError as exc:
                raise ReportError(str(exc)) from exc

        is_liability = component.liquidity_class == ManualValuationLiquidityClass.LIABILITY.value
        line = {
            "account_id": component.id,
            "name": _valuation_line_name(component.source, component.component_type),
            "type": AccountType.LIABILITY if is_liability else AccountType.ASSET,
            "parent_id": None,
            "amount": _quantize_money(amount),
            # Manual valuations are user-supplied, explicitly trusted data (vision:
            # "manual data is explicitly trusted"), mirroring source_type=manual.
            "confidence_tier": "TRUSTED",
            "provenance": "manual",
            "source_currency": source_currency,
            "allocation_asset_class": _manual_valuation_allocation_asset_class(component.component_type),
            "allocation_liquidity_class": component.liquidity_class,
            "allocation_source_type": "manual_valuation",
        }
        if is_liability:
            liability_lines.append(line)
        else:
            asset_lines.append(line)

    asset_lines.sort(key=lambda line: line["name"].lower())
    liability_lines.sort(key=lambda line: line["name"].lower())
    return asset_lines, liability_lines
