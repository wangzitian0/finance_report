"""Manual-valuation snapshot service (split from services/assets.py, #1677/#1610)."""

import re
from bisect import bisect_right
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any, cast
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import aggregate_order_by
from sqlalchemy.ext.asyncio import AsyncSession

from src.audit import normalize_currency_code
from src.audit.money import to_money
from src.observability import get_logger
from src.pricing.base.errors import NoObservationError, PricingError
from src.pricing.base.manual_valuation import (
    ManualValuationBasis,
    ManualValuationComponentType,
    ManualValuationFact,
    ManualValuationLiquidityClass,
)
from src.pricing.extension.manual import record_manual_valuation
from src.pricing.orm.manual_valuation import ManualValuationSnapshot
from src.schemas.provenance import DataProvenance

logger = get_logger(__name__)

ASSET_QUANTITY_UNIT = "units"
_LIABILITY_CLS = ManualValuationLiquidityClass.LIABILITY.value
_RESTRICTED_LIQUIDITY_CLASSES = frozenset(
    {ManualValuationLiquidityClass.RESTRICTED.value, ManualValuationLiquidityClass.ILLIQUID.value}
)
_LIABILITY_AFFIXES = ("mortgage", "loan", "balance", "liability", "payable", "debt", "financing")
_ASSET_PREFIXES = ("property", "real estate", "home", "house", "residence")


class ValuationServiceError(Exception):
    """Valuation service failure."""


@dataclass
class ValuationComponentItem:
    """Latest manual valuation component included in net worth views."""

    id: UUID
    component_type: str
    liquidity_class: str
    as_of_date: date
    value: Decimal
    currency: str
    source: str
    provenance: DataProvenance = "manual"


@dataclass
class ValuationComponentsResult:
    """Aggregated latest manual valuation components with missing-date gap warnings (#1796)."""

    items: list[ValuationComponentItem]
    total_assets: Decimal
    total_liabilities: Decimal
    net_worth_delta: Decimal
    warnings: list[dict[str, str]] = field(default_factory=list)
    excluded_items: list[ValuationComponentItem] = field(default_factory=list)
    unrecorded_assets: list[ValuationComponentItem] = field(default_factory=list)


def _stem_keys(text: str) -> set[str]:
    norm = " ".join(re.sub(r"[^a-z0-9]+", " ", text.lower()).split())
    if not norm:
        return set()
    keys = {norm}
    words = [w for w in norm.split() if w not in _LIABILITY_AFFIXES]
    if words:
        stripped = " ".join(words)
        keys.add(stripped)
        for prefix in _ASSET_PREFIXES:
            if stripped.startswith(f"{prefix} ") and len(stripped) > len(prefix) + 1:
                keys.add(stripped[len(prefix) + 1 :].strip())
    return {k for k in keys if k}


def _financed_asset_of_liability(
    source: str,
    assets: Sequence[ValuationComponentItem],
    *,
    allow_class_fallback: bool = False,
) -> ValuationComponentItem | None:
    liability_keys = _stem_keys(source)
    if liability_keys:
        for asset in assets:
            if liability_keys & _stem_keys(asset.source):
                return asset
    if allow_class_fallback:
        real_estate = [a for a in assets if _manual_valuation_allocation_asset_class(a.component_type) == "real_estate"]
        if real_estate and all(a.liquidity_class in _RESTRICTED_LIQUIDITY_CLASSES for a in real_estate):
            return real_estate[0]
    return None


def _is_restricted_financed_liability(
    source: str,
    assets: Sequence[ValuationComponentItem],
    *,
    is_mortgage: bool = False,
) -> bool:
    financed = _financed_asset_of_liability(source, assets, allow_class_fallback=is_mortgage)
    return financed is not None and financed.liquidity_class in _RESTRICTED_LIQUIDITY_CLASSES


def _candidate_assets(*item_groups: Sequence[ValuationComponentItem]) -> list[ValuationComponentItem]:
    return [item for group in item_groups for item in group if item.liquidity_class != _LIABILITY_CLS]


def split_net_worth_scope(
    items: Sequence[ValuationComponentItem],
    *,
    include_restricted: bool,
    unrecorded_assets: Sequence[ValuationComponentItem] = (),
) -> tuple[list[ValuationComponentItem], list[ValuationComponentItem]]:
    """Partition manual valuations inside and outside restricted-holdings scope (#2645, #2659)."""
    if include_restricted:
        return list(items), []
    candidate_assets = _candidate_assets(items, unrecorded_assets)
    included: list[ValuationComponentItem] = []
    excluded: list[ValuationComponentItem] = []
    for item in items:
        is_excluded = item.liquidity_class in _RESTRICTED_LIQUIDITY_CLASSES or (
            item.liquidity_class == _LIABILITY_CLS
            and _is_restricted_financed_liability(
                item.source,
                candidate_assets,
                is_mortgage=item.component_type == ManualValuationComponentType.MORTGAGE_BALANCE.value,
            )
        )
        (excluded if is_excluded else included).append(item)
    return included, excluded


_DEFAULT_LIQUIDITY_CLASS: dict[ManualValuationComponentType, ManualValuationLiquidityClass] = {
    ManualValuationComponentType.PROPERTY_VALUE: ManualValuationLiquidityClass.ILLIQUID,
    ManualValuationComponentType.MORTGAGE_BALANCE: ManualValuationLiquidityClass.LIABILITY,
    ManualValuationComponentType.CPF_BALANCE: ManualValuationLiquidityClass.RESTRICTED,
    ManualValuationComponentType.RETIREMENT_ACCOUNT: ManualValuationLiquidityClass.RESTRICTED,
    ManualValuationComponentType.SOCIAL_SECURITY_PERSONAL_ACCOUNT: ManualValuationLiquidityClass.RESTRICTED,
    ManualValuationComponentType.LONG_TERM_BENEFIT_ASSET: ManualValuationLiquidityClass.RESTRICTED,
    ManualValuationComponentType.LONG_TERM_SAVINGS: ManualValuationLiquidityClass.RESTRICTED,
    ManualValuationComponentType.TAX_PAYABLE: ManualValuationLiquidityClass.LIABILITY,
    ManualValuationComponentType.TAX_REFUND: ManualValuationLiquidityClass.LIQUID,
    ManualValuationComponentType.INSURANCE_CASH_VALUE: ManualValuationLiquidityClass.RESTRICTED,
    ManualValuationComponentType.ESOP: ManualValuationLiquidityClass.RESTRICTED,
    ManualValuationComponentType.RSU: ManualValuationLiquidityClass.RESTRICTED,
    ManualValuationComponentType.STOCK_OPTIONS: ManualValuationLiquidityClass.RESTRICTED,
    ManualValuationComponentType.OTHER_ASSET: ManualValuationLiquidityClass.LIQUID,
    ManualValuationComponentType.OTHER_LIABILITY: ManualValuationLiquidityClass.LIABILITY,
}

_ASSET_CLASS_BY_COMPONENT: dict[str, str] = {
    ManualValuationComponentType.PROPERTY_VALUE.value: "real_estate",
    ManualValuationComponentType.MORTGAGE_BALANCE.value: "real_estate",
    ManualValuationComponentType.CPF_BALANCE.value: "retirement_and_benefit_assets",
    ManualValuationComponentType.RETIREMENT_ACCOUNT.value: "retirement_and_benefit_assets",
    ManualValuationComponentType.SOCIAL_SECURITY_PERSONAL_ACCOUNT.value: "retirement_and_benefit_assets",
    ManualValuationComponentType.LONG_TERM_BENEFIT_ASSET.value: "retirement_and_benefit_assets",
    ManualValuationComponentType.LONG_TERM_SAVINGS.value: "retirement_and_benefit_assets",
    ManualValuationComponentType.INSURANCE_CASH_VALUE.value: "retirement_and_benefit_assets",
    ManualValuationComponentType.TAX_REFUND.value: "cash",
    ManualValuationComponentType.TAX_PAYABLE.value: "liability",
    ManualValuationComponentType.OTHER_LIABILITY.value: "liability",
    **{t.value: "restricted_comp" for t in ManualValuationComponentType.restricted_compensation_types()},
}


def _manual_valuation_fact(snapshot: ManualValuationSnapshot) -> ManualValuationFact:
    return ManualValuationFact(
        id=snapshot.id,
        component_type=snapshot.component_type,
        liquidity_class=snapshot.liquidity_class,
        as_of_date=snapshot.as_of_date,
        value=Decimal(snapshot.value),
        currency=snapshot.currency,
        source=snapshot.source,
        valuation_basis=snapshot.valuation_basis,
        notes=snapshot.notes,
        reminder_date=snapshot.reminder_date,
        created_at=snapshot.created_at,
    )


async def list_current_manual_valuation_facts(
    db: AsyncSession,
    user_id: UUID,
    *,
    as_of_date: date,
    component_types: tuple[ManualValuationComponentType, ...] | None = None,
    liquidity_class: ManualValuationLiquidityClass | None = None,
) -> list[ManualValuationFact]:
    """Return current pricing facts without leaking the persistence ORM adapter."""
    query = (
        select(ManualValuationSnapshot)
        .where(
            ManualValuationSnapshot.user_id == user_id,
            ManualValuationSnapshot.as_of_date <= as_of_date,
            ManualValuationSnapshot.superseded_by_id.is_(None),
        )
        .order_by(ManualValuationSnapshot.as_of_date.desc(), ManualValuationSnapshot.created_at.desc())
    )
    if component_types is not None:
        query = query.where(ManualValuationSnapshot.component_type.in_(component_types))
    if liquidity_class is not None:
        query = query.where(ManualValuationSnapshot.liquidity_class == liquidity_class)
    latest_by_key: dict[tuple[ManualValuationComponentType, str, str], ManualValuationFact] = {}
    for row in (await db.scalars(query)).all():
        latest_by_key.setdefault((row.component_type, row.source, row.currency), _manual_valuation_fact(row))
    return list(latest_by_key.values())


class ValuationService:
    """Manual-valuation snapshot operations."""

    async def create_valuation_snapshot(
        self,
        db: AsyncSession,
        user_id: UUID,
        *,
        component_type: ManualValuationComponentType,
        as_of_date: date,
        value: Decimal,
        currency: str,
        source: str,
        valuation_basis: ManualValuationBasis | None = None,
        notes: str | None = None,
        liquidity_class: ManualValuationLiquidityClass | None = None,
        recurrence_days: int | None = None,
        reminder_date: date | None = None,
    ) -> ManualValuationSnapshot:
        """Record through the sole decision-backed manual valuation command."""
        observation = await record_manual_valuation(
            db,
            user_id,
            component_type=component_type,
            liquidity_class=liquidity_class or _DEFAULT_LIQUIDITY_CLASS[component_type],
            as_of=as_of_date,
            value=value,
            currency=currency,
            source=source,
            valuation_basis=valuation_basis,
            notes=notes,
            recurrence_days=recurrence_days,
            reminder_date=reminder_date,
        )
        snapshot = await self.get_valuation_snapshot(db, user_id, observation.id)
        if snapshot is None:  # pragma: no cover
            raise ValuationServiceError("decision-backed valuation write did not produce a snapshot")
        return snapshot

    async def list_valuation_snapshots(
        self,
        db: AsyncSession,
        user_id: UUID,
        *,
        as_of_date: date | None = None,
        component_type: ManualValuationComponentType | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[Sequence[ManualValuationSnapshot], int]:
        """List current non-superseded manual valuation snapshots for a user."""
        filters = [ManualValuationSnapshot.user_id == user_id, ManualValuationSnapshot.superseded_by_id.is_(None)]
        if as_of_date is not None:
            filters.append(ManualValuationSnapshot.as_of_date <= as_of_date)
        if component_type is not None:
            filters.append(ManualValuationSnapshot.component_type == component_type)

        total = (await db.scalar(select(func.count()).select_from(ManualValuationSnapshot).where(*filters))) or 0
        rows = (
            await db.scalars(
                select(ManualValuationSnapshot)
                .where(*filters)
                .order_by(ManualValuationSnapshot.as_of_date.desc(), ManualValuationSnapshot.created_at.desc())
                .limit(limit)
                .offset(offset)
            )
        ).all()
        return rows, total

    async def get_valuation_snapshot(
        self,
        db: AsyncSession,
        user_id: UUID,
        snapshot_id: UUID,
    ) -> ManualValuationSnapshot | None:
        return await db.scalar(
            select(ManualValuationSnapshot).where(
                ManualValuationSnapshot.user_id == user_id,
                ManualValuationSnapshot.id == snapshot_id,
            )
        )

    async def update_valuation_snapshot(
        self,
        db: AsyncSession,
        user_id: UUID,
        snapshot_id: UUID,
        *,
        values: dict,
    ) -> ManualValuationSnapshot | None:
        """Append a correction through the sole decision-backed write command."""
        snapshot = await self.get_valuation_snapshot(db, user_id, snapshot_id)
        if not snapshot:
            return None
        if snapshot.superseded_by_id is not None:
            raise ValuationServiceError("Cannot edit a superseded valuation version; submit a correction instead")

        for field_name in ("component_type", "as_of_date", "source"):
            requested = values.get(field_name)
            if requested is not None and requested != getattr(snapshot, field_name):
                raise ValuationServiceError(
                    f"Cannot change valuation {field_name} in place; record a separate valuation instead"
                )

        value = to_money(cast(Decimal, values["value"])) if values.get("value") is not None else snapshot.value
        currency = cast(str, values["currency"]) if values.get("currency") is not None else snapshot.currency

        def _val(key: str) -> Any:
            return values[key] if key in values else getattr(snapshot, key)

        observation = await record_manual_valuation(
            db,
            user_id,
            component_type=snapshot.component_type,
            liquidity_class=values.get("liquidity_class") or snapshot.liquidity_class,
            as_of=snapshot.as_of_date,
            value=value,
            currency=currency,
            source=snapshot.source,
            valuation_basis=_val("valuation_basis"),
            notes=_val("notes"),
            recurrence_days=_val("recurrence_days"),
            reminder_date=_val("reminder_date"),
        )
        corrected = await self.get_valuation_snapshot(db, user_id, observation.id)
        if corrected is None:  # pragma: no cover
            raise ValuationServiceError("decision-backed valuation correction did not produce a snapshot")
        return corrected

    async def delete_valuation_snapshot(self, db: AsyncSession, user_id: UUID, snapshot_id: UUID) -> bool:
        """Reject destructive deletion of an immutable decision-backed input."""
        if await self.get_valuation_snapshot(db, user_id, snapshot_id) is None:
            return False
        raise ValuationServiceError(
            "Cannot delete a decision-backed valuation snapshot; submit a correcting valuation instead"
        )

    async def get_latest_valuation_components(
        self,
        db: AsyncSession,
        user_id: UUID,
        *,
        as_of_date: date,
        include_restricted: bool = True,
    ) -> ValuationComponentsResult:
        """Get latest manual valuation components for net worth aggregation."""
        latest_subquery = (
            select(
                ManualValuationSnapshot.id,
                func.row_number()
                .over(
                    partition_by=[
                        ManualValuationSnapshot.component_type,
                        ManualValuationSnapshot.source,
                        ManualValuationSnapshot.currency,
                    ],
                    order_by=[ManualValuationSnapshot.as_of_date.desc(), ManualValuationSnapshot.created_at.desc()],
                )
                .label("rn"),
            )
            .where(
                ManualValuationSnapshot.user_id == user_id,
                ManualValuationSnapshot.as_of_date <= as_of_date,
                ManualValuationSnapshot.superseded_by_id.is_(None),
            )
            .subquery()
        )
        snapshots = (
            await db.scalars(
                select(ManualValuationSnapshot)
                .join(latest_subquery, ManualValuationSnapshot.id == latest_subquery.c.id)
                .where(latest_subquery.c.rn == 1)
                .order_by(ManualValuationSnapshot.component_type, ManualValuationSnapshot.source)
            )
        ).all()

        latest_liquidity = aggregate_order_by(
            ManualValuationSnapshot.liquidity_class,
            ManualValuationSnapshot.as_of_date.desc(),
            ManualValuationSnapshot.created_at.desc(),
        )
        gap_list = list(
            await db.execute(
                select(
                    ManualValuationSnapshot.component_type,
                    ManualValuationSnapshot.source,
                    func.min(ManualValuationSnapshot.as_of_date).label("earliest_as_of_date"),
                    func.array_agg(latest_liquidity)[1].label("latest_liquidity_class"),
                )
                .where(ManualValuationSnapshot.user_id == user_id, ManualValuationSnapshot.superseded_by_id.is_(None))
                .group_by(ManualValuationSnapshot.component_type, ManualValuationSnapshot.source)
                .having(func.min(ManualValuationSnapshot.as_of_date) > as_of_date)
                .order_by(ManualValuationSnapshot.component_type, ManualValuationSnapshot.source)
            )
        )
        current_items = [
            ValuationComponentItem(
                id=s.id,
                component_type=s.component_type.value,
                liquidity_class=s.liquidity_class.value,
                as_of_date=s.as_of_date,
                value=to_money(s.value),
                currency=s.currency,
                source=s.source,
                provenance="manual",
            )
            for s in snapshots
        ]
        unrecorded_assets = [
            ValuationComponentItem(
                id=UUID(int=0),
                component_type=row.component_type.value,
                liquidity_class=row.latest_liquidity_class.value,
                as_of_date=row.earliest_as_of_date,
                value=Decimal("0.00"),
                currency="SGD",
                source=row.source,
                provenance="manual",
            )
            for row in gap_list
            if row.latest_liquidity_class.value != _LIABILITY_CLS
        ]
        items, excluded_items = split_net_worth_scope(
            current_items,
            include_restricted=include_restricted,
            unrecorded_assets=unrecorded_assets,
        )
        candidate_assets = _candidate_assets(current_items, unrecorded_assets)
        warnings: list[dict[str, str]] = [
            {
                "type": "valuation_component_not_yet_recorded",
                "component_type": row.component_type.value,
                "source": row.source,
                "as_of_date": as_of_date.isoformat(),
                "earliest_as_of_date": row.earliest_as_of_date.isoformat(),
                "message": (
                    f"Manual valuation '{row.source}' ({row.component_type.value}) has no "
                    f"snapshot on or before {as_of_date.isoformat()} (earliest is "
                    f"{row.earliest_as_of_date.isoformat()}); it is excluded from these totals."
                ),
            }
            for row in gap_list
            if include_restricted
            or (
                row.latest_liquidity_class.value not in _RESTRICTED_LIQUIDITY_CLASSES
                and not (
                    row.latest_liquidity_class.value == _LIABILITY_CLS
                    and _is_restricted_financed_liability(
                        row.source,
                        candidate_assets,
                        is_mortgage=row.component_type == ManualValuationComponentType.MORTGAGE_BALANCE,
                    )
                )
            )
        ]
        total_assets = to_money(
            sum((item.value for item in items if item.liquidity_class != _LIABILITY_CLS), Decimal("0"))
        )
        total_liabilities = to_money(
            sum((item.value for item in items if item.liquidity_class == _LIABILITY_CLS), Decimal("0"))
        )
        return ValuationComponentsResult(
            items=items,
            total_assets=total_assets,
            total_liabilities=total_liabilities,
            net_worth_delta=to_money(total_assets - total_liabilities),
            warnings=warnings,
            excluded_items=excluded_items,
            unrecorded_assets=unrecorded_assets,
        )


def _valuation_line_name(component_name: str, component_type: str) -> str:
    return f"Valuation: {component_name} ({component_type.replace('_', ' ')})"


def _manual_valuation_allocation_asset_class(component_type: str) -> str:
    return _ASSET_CLASS_BY_COMPONENT.get(component_type, "other")


def _manual_valuation_line(component: ValuationComponentItem, amount: Decimal | None) -> dict[str, Any]:
    """Build one balance-sheet line dict using plain string account types to preserve pricing isolation."""
    is_liability = component.liquidity_class == _LIABILITY_CLS
    return {
        "account_id": component.id,
        "name": _valuation_line_name(component.source, component.component_type),
        "type": "LIABILITY" if is_liability else "ASSET",
        "parent_id": None,
        "amount": None if amount is None else to_money(amount),
        "provenance": "manual",
        "source_currency": component.currency.upper(),
        "allocation_asset_class": _manual_valuation_allocation_asset_class(component.component_type),
        "allocation_liquidity_class": component.liquidity_class,
        "allocation_source_type": "manual_valuation",
    }


def _split_manual_valuation_lines(
    lines: Sequence[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    by_name = lambda line: line["name"].lower()  # noqa: E731
    return (
        sorted((line for line in lines if line["type"] == "ASSET"), key=by_name),
        sorted((line for line in lines if line["type"] == "LIABILITY"), key=by_name),
    )


async def build_manual_valuation_lines(
    db: AsyncSession,
    user_id: UUID,
    *,
    as_of_date: date,
    target_currency: str,
    include_restricted: bool = True,
    warnings: list[dict[str, str]] | None = None,
    excluded_lines: list[dict[str, Any]] | None = None,
    liability_lines: list[dict[str, Any]] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Build balance sheet lines from latest manual valuation components (#2659)."""
    from src.pricing.extension.fx import convert_amount

    target_currency = target_currency.upper()
    components = await ValuationService().get_latest_valuation_components(
        db,
        user_id,
        as_of_date=as_of_date,
        include_restricted=include_restricted,
    )
    if warnings is not None:
        warnings.extend(components.warnings)

    async def line_of(component: ValuationComponentItem) -> dict[str, Any]:
        amount = component.value
        source_currency = component.currency.upper()
        if source_currency != target_currency:
            amount = await convert_amount(
                db,
                amount=amount,
                currency=source_currency,
                target_currency=target_currency,
                rate_date=as_of_date,
                lazy_load=True,
            )
        return _manual_valuation_line(component, amount)

    lines = [await line_of(component) for component in components.items]
    if excluded_lines is not None:
        for component in components.excluded_items:
            try:
                excluded_lines.append(await line_of(component))
            except PricingError as exc:
                excluded_lines.append(
                    {
                        **_manual_valuation_line(component, None),
                        "conversion_warning": {
                            "type": (
                                "missing_fx_rate_excluded_holding"
                                if isinstance(exc, NoObservationError)
                                else "fx_conversion_failed_excluded_holding"
                            ),
                            "component_type": component.component_type,
                            "source": component.source,
                            "currency": component.currency.upper(),
                            "target_currency": target_currency,
                            "as_of_date": as_of_date.isoformat(),
                            "message": str(exc),
                        },
                    }
                )
    if not include_restricted and liability_lines:
        candidate_assets = _candidate_assets(components.items, components.excluded_items, components.unrecorded_assets)
        kept: list[dict[str, Any]] = []
        for line in liability_lines:
            financed = _financed_asset_of_liability(str(line.get("name", "")), candidate_assets)
            if financed is not None and financed.liquidity_class in _RESTRICTED_LIQUIDITY_CLASSES:
                if excluded_lines is not None:
                    excluded_lines.append(
                        {
                            **line,
                            "allocation_asset_class": _manual_valuation_allocation_asset_class(financed.component_type),
                        }
                    )
            else:
                kept.append(line)
        liability_lines[:] = kept
    return _split_manual_valuation_lines(lines)


async def build_manual_valuation_lines_series(
    db: AsyncSession,
    user_id: UUID,
    *,
    as_of_dates: Sequence[date],
    target_currency: str,
    include_restricted: bool = True,
    ledger_liability_names: Mapping[UUID, str] | None = None,
    excluded_ledger_ids_by_date: dict[date, set[UUID]] | None = None,
) -> dict[date, tuple[list[dict[str, Any]], list[dict[str, Any]]]]:
    """Return manual-valuation balance-sheet lines for each date in ``as_of_dates``."""
    from src.pricing.extension.fx import _convert_money_amount, get_exchange_rate, get_exchange_rate_series

    target_currency = target_currency.upper()
    ordered = sorted(set(as_of_dates))
    if not ordered:
        return {}
    snapshot_dates = sorted(
        (
            await db.scalars(
                select(ManualValuationSnapshot.as_of_date)
                .distinct()
                .where(
                    ManualValuationSnapshot.user_id == user_id,
                    ManualValuationSnapshot.superseded_by_id.is_(None),
                    ManualValuationSnapshot.as_of_date <= ordered[-1],
                )
            )
        ).all()
    )
    selected_snapshot_date = {
        d: snapshot_dates[pos - 1] if (pos := bisect_right(snapshot_dates, d)) else None for d in ordered
    }

    components_by_snapshot_date: dict[date, list[ValuationComponentItem]] = {}
    candidate_assets_by_snapshot_date: dict[date, list[ValuationComponentItem]] = {}
    svc = ValuationService()
    for snapshot_date in sorted({v for v in selected_snapshot_date.values() if v is not None}):
        components = await svc.get_latest_valuation_components(
            db,
            user_id,
            as_of_date=snapshot_date,
            include_restricted=include_restricted,
        )
        components_by_snapshot_date[snapshot_date] = components.items
        candidate_assets_by_snapshot_date[snapshot_date] = _candidate_assets(
            components.items, components.excluded_items, components.unrecorded_assets
        )

    if not include_restricted and ledger_liability_names and excluded_ledger_ids_by_date is not None:
        fallback_assets = next(iter(candidate_assets_by_snapshot_date.values()), [])
        if not fallback_assets and not snapshot_dates:
            earliest = await svc.get_latest_valuation_components(
                db, user_id, as_of_date=ordered[0], include_restricted=False
            )
            fallback_assets = _candidate_assets(earliest.items, earliest.excluded_items, earliest.unrecorded_assets)
        for as_of_date in ordered:
            snap_date = selected_snapshot_date[as_of_date]
            assets_for_date = candidate_assets_by_snapshot_date[snap_date] if snap_date is not None else fallback_assets
            excluded_ledger_ids_by_date[as_of_date] = {
                acc_id
                for acc_id, name in ledger_liability_names.items()
                if _is_restricted_financed_liability(name, assets_for_date)
            }

    def components_on(as_of_date: date) -> list[ValuationComponentItem]:
        snap_date = selected_snapshot_date[as_of_date]
        return components_by_snapshot_date[snap_date] if snap_date is not None else []

    dates_by_currency: dict[str, list[date]] = {}
    for as_of_date in ordered:
        for component in components_on(as_of_date):
            source_currency = component.currency.upper()
            if source_currency != target_currency:
                dates_by_currency.setdefault(source_currency, []).append(as_of_date)
    rates_by_currency = {
        cur: await get_exchange_rate_series(db, cur, target_currency, rate_dates, lazy_load=True)
        for cur, rate_dates in dates_by_currency.items()
    }

    target_code = normalize_currency_code(target_currency)
    series: dict[date, tuple[list[dict[str, Any]], list[dict[str, Any]]]] = {}
    for as_of_date in ordered:
        lines: list[dict[str, Any]] = []
        for component in components_on(as_of_date):
            amount = component.value
            source_currency = component.currency.upper()
            if source_currency != target_currency:
                rate = rates_by_currency[source_currency].get(as_of_date) or await get_exchange_rate(
                    db, source_currency, target_currency, as_of_date, lazy_load=True
                )
                source_code = normalize_currency_code(source_currency)
                if source_code != target_code:
                    amount = _convert_money_amount(amount, source_code, target_code, rate)
            lines.append(_manual_valuation_line(component, amount))
        series[as_of_date] = _split_manual_valuation_lines(lines)
    return series
