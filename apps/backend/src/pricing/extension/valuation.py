"""Manual-valuation snapshot service (split from services/assets.py, #1677/#1610).

Valuation snapshots and their versioned read models are pricing-owned facts
(#1610 ruling 2); the position/depreciation half lives in
``src.portfolio.extension.positions``.
"""

from bisect import bisect_right
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any, cast
from uuid import UUID

from sqlalchemy import Select, func, select
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


class ValuationServiceError(Exception):
    """Valuation service failure (was ValuationServiceError, #1677)."""


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
    """Aggregated latest manual valuation components.

    ``warnings`` discloses (component_type, source) combinations that exist for
    the user but have no snapshot on or before the requested ``as_of_date`` —
    their value is absent from the totals, and without the disclosure a
    historical total would silently read as complete (#1796, Axiom B).
    """

    items: list[ValuationComponentItem]
    total_assets: Decimal
    total_liabilities: Decimal
    net_worth_delta: Decimal
    warnings: list[dict[str, str]] = field(default_factory=list)
    # The current components that the scope excludes (#2645). The totals above do not include them.
    excluded_items: list[ValuationComponentItem] = field(default_factory=list)


# A scope without restricted holdings excludes the assets of these liquidity classes.
_RESTRICTED_LIQUIDITY_CLASSES = frozenset(
    {ManualValuationLiquidityClass.RESTRICTED.value, ManualValuationLiquidityClass.ILLIQUID.value}
)


def split_net_worth_scope(
    items: Sequence[ValuationComponentItem],
    *,
    include_restricted: bool,
) -> tuple[list[ValuationComponentItem], list[ValuationComponentItem]]:
    """Return the manual valuations inside and outside one restricted-holdings scope (#2645).

    This function is the only definition of the scope. The full scope holds each
    component. The scope without restricted holdings excludes each restricted or
    illiquid asset valuation. It also excludes each liability valuation whose
    allocation class (``_manual_valuation_allocation_asset_class``, a fixed map
    from the component type) is the class of an excluded asset. Only
    ``mortgage_balance`` shares a class with an asset type (``real_estate``), so
    a mortgage valuation leaves with an excluded property valuation.

    Limits (#2659). There is no link from one liability to one asset:
    - A ledger liability account, for example a mortgage kept as a loan account,
      always counts. Only manual valuations take part in the scope.
    - When one property valuation is excluded, every mortgage valuation leaves,
      also the mortgage of a property valuation that is set to liquid.
    - The rule reads the components current on the as-of date. A mortgage valuation
      that is older than its property valuation counts until the property date.
    """
    if include_restricted:
        return list(items), []
    excluded_classes = {
        _manual_valuation_allocation_asset_class(item.component_type)
        for item in items
        if item.liquidity_class in _RESTRICTED_LIQUIDITY_CLASSES
    }
    included: list[ValuationComponentItem] = []
    excluded: list[ValuationComponentItem] = []
    for item in items:
        is_excluded = item.liquidity_class in _RESTRICTED_LIQUIDITY_CLASSES or (
            item.liquidity_class == ManualValuationLiquidityClass.LIABILITY.value
            and _manual_valuation_allocation_asset_class(item.component_type) in excluded_classes
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


def _manual_valuation_fact(snapshot: ManualValuationSnapshot) -> ManualValuationFact:
    """Detach a pricing persistence row before it crosses the package boundary."""
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
    """Return current pricing facts without leaking the legacy ORM adapter."""
    query = (
        select(ManualValuationSnapshot)
        .where(ManualValuationSnapshot.user_id == user_id)
        .where(ManualValuationSnapshot.as_of_date <= as_of_date)
        .where(ManualValuationSnapshot.superseded_by_id.is_(None))
        .order_by(ManualValuationSnapshot.as_of_date.desc(), ManualValuationSnapshot.created_at.desc())
    )
    if component_types is not None:
        query = query.where(ManualValuationSnapshot.component_type.in_(component_types))
    if liquidity_class is not None:
        query = query.where(ManualValuationSnapshot.liquidity_class == liquidity_class)
    rows = (await db.execute(query)).scalars().all()
    latest_by_key: dict[tuple[ManualValuationComponentType, str, str], ManualValuationFact] = {}
    for row in rows:
        key = (row.component_type, row.source, row.currency)
        if key not in latest_by_key:
            latest_by_key[key] = _manual_valuation_fact(row)
    return list(latest_by_key.values())


def _valuation_key_query(
    user_id: UUID,
    *,
    component_type: ManualValuationComponentType,
    source: str,
    as_of_date: date,
) -> Select[tuple[ManualValuationSnapshot]]:
    """Base select for a manual-valuation version-chain key.

    Matches the partial unique index identity (user_id, component_type, source,
    as_of_date); callers append head/order/lock clauses.
    """
    return (
        select(ManualValuationSnapshot)
        .where(ManualValuationSnapshot.user_id == user_id)
        .where(ManualValuationSnapshot.component_type == component_type)
        .where(ManualValuationSnapshot.source == source)
        .where(ManualValuationSnapshot.as_of_date == as_of_date)
    )


class ValuationService:
    """Manual-valuation snapshot operations (was AssetService's valuation half)."""

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
        if snapshot is None:  # pragma: no cover - the command flushes before returning.
            raise ValuationServiceError("decision-backed valuation write did not produce a snapshot")
        return snapshot

    async def _current_valuation_head(
        self,
        db: AsyncSession,
        user_id: UUID,
        *,
        component_type: ManualValuationComponentType,
        source: str,
        as_of_date: date,
    ) -> ManualValuationSnapshot | None:
        """Return the current (non-superseded) version for a valuation key, if any.

        The key matches the partial unique index exactly
        (user_id, component_type, source, as_of_date) — currency is a corrigible
        attribute of the fact, not part of its version-chain identity.
        """
        result = await db.execute(
            _valuation_key_query(user_id, component_type=component_type, source=source, as_of_date=as_of_date)
            .where(ManualValuationSnapshot.superseded_by_id.is_(None))
            .with_for_update()
        )
        return result.scalar_one_or_none()

    async def list_valuation_versions(
        self,
        db: AsyncSession,
        user_id: UUID,
        *,
        component_type: ManualValuationComponentType,
        source: str,
        as_of_date: date,
    ) -> Sequence[ManualValuationSnapshot]:
        """Return the full append-only version history for a valuation key, newest first.

        Keyed by the same identity as the head index
        (user_id, component_type, source, as_of_date), so a correction that also
        changes currency is still part of one history chain.
        """
        result = await db.execute(
            _valuation_key_query(user_id, component_type=component_type, source=source, as_of_date=as_of_date).order_by(
                ManualValuationSnapshot.version.desc()
            )
        )
        return result.scalars().all()

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
        """List manual valuation snapshots for a user."""
        # Only current heads (superseded_by_id IS NULL); superseded history rows
        # are reachable via list_valuation_versions, not the default listing.
        query = (
            select(ManualValuationSnapshot)
            .where(ManualValuationSnapshot.user_id == user_id)
            .where(ManualValuationSnapshot.superseded_by_id.is_(None))
        )
        count_query = (
            select(func.count())
            .select_from(ManualValuationSnapshot)
            .where(ManualValuationSnapshot.user_id == user_id)
            .where(ManualValuationSnapshot.superseded_by_id.is_(None))
        )
        if as_of_date is not None:
            query = query.where(ManualValuationSnapshot.as_of_date <= as_of_date)
            count_query = count_query.where(ManualValuationSnapshot.as_of_date <= as_of_date)
        if component_type is not None:
            query = query.where(ManualValuationSnapshot.component_type == component_type)
            count_query = count_query.where(ManualValuationSnapshot.component_type == component_type)

        count_result = await db.execute(count_query)
        total = count_result.scalar() or 0

        result = await db.execute(
            query.order_by(ManualValuationSnapshot.as_of_date.desc(), ManualValuationSnapshot.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return result.scalars().all(), total

    async def get_valuation_snapshot(
        self,
        db: AsyncSession,
        user_id: UUID,
        snapshot_id: UUID,
    ) -> ManualValuationSnapshot | None:
        """Get a manual valuation snapshot by id."""
        result = await db.execute(
            select(ManualValuationSnapshot)
            .where(ManualValuationSnapshot.user_id == user_id)
            .where(ManualValuationSnapshot.id == snapshot_id)
        )
        return result.scalar_one_or_none()

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

        identity_changes = {
            "component_type": snapshot.component_type,
            "as_of_date": snapshot.as_of_date,
            "source": snapshot.source,
        }
        for identity_field, current in identity_changes.items():
            requested = values.get(identity_field)
            if requested is not None and requested != current:
                raise ValuationServiceError(
                    f"Cannot change valuation {identity_field} in place; record a separate valuation instead"
                )

        value = snapshot.value
        if values.get("value") is not None:
            value = to_money(cast(Decimal, values["value"]))
        currency = snapshot.currency
        if values.get("currency") is not None:
            currency = cast(str, values["currency"])

        observation = await record_manual_valuation(
            db,
            user_id,
            component_type=snapshot.component_type,
            liquidity_class=values.get("liquidity_class") or snapshot.liquidity_class,
            as_of=snapshot.as_of_date,
            value=value,
            currency=currency,
            source=snapshot.source,
            valuation_basis=(values["valuation_basis"] if "valuation_basis" in values else snapshot.valuation_basis),
            notes=values["notes"] if "notes" in values else snapshot.notes,
            recurrence_days=(values["recurrence_days"] if "recurrence_days" in values else snapshot.recurrence_days),
            reminder_date=values["reminder_date"] if "reminder_date" in values else snapshot.reminder_date,
        )
        corrected = await self.get_valuation_snapshot(db, user_id, observation.id)
        if corrected is None:  # pragma: no cover - the command flushes before returning.
            raise ValuationServiceError("decision-backed valuation correction did not produce a snapshot")
        return corrected

    async def delete_valuation_snapshot(self, db: AsyncSession, user_id: UUID, snapshot_id: UUID) -> bool:
        """Reject destructive deletion of an immutable decision-backed input."""
        snapshot = await self.get_valuation_snapshot(db, user_id, snapshot_id)
        if snapshot is None:
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
                    order_by=[
                        ManualValuationSnapshot.as_of_date.desc(),
                        ManualValuationSnapshot.created_at.desc(),
                    ],
                )
                .label("rn"),
            )
            .where(ManualValuationSnapshot.user_id == user_id)
            .where(ManualValuationSnapshot.as_of_date <= as_of_date)
            .where(ManualValuationSnapshot.superseded_by_id.is_(None))
            .subquery()
        )

        result = await db.execute(
            select(ManualValuationSnapshot)
            .join(latest_subquery, ManualValuationSnapshot.id == latest_subquery.c.id)
            .where(latest_subquery.c.rn == 1)
            .order_by(ManualValuationSnapshot.component_type, ManualValuationSnapshot.source)
        )
        snapshots = result.scalars().all()

        # Disclose combos whose only snapshots postdate as_of_date: they are
        # absent from the totals below, and "we did not own it yet" vs "we had
        # not recorded it yet" is inherently ambiguous for a manual component
        # (#1796) — so the gap is warned about, never guessed at. A view that
        # excludes restricted/illiquid components must not have their existence
        # disclosed by a warning either, so the combo's latest liquidity class
        # rides along and is filtered under include_restricted=False.
        latest_liquidity = aggregate_order_by(
            ManualValuationSnapshot.liquidity_class,
            ManualValuationSnapshot.as_of_date.desc(),
            ManualValuationSnapshot.created_at.desc(),
        )
        gap_rows = await db.execute(
            select(
                ManualValuationSnapshot.component_type,
                ManualValuationSnapshot.source,
                func.min(ManualValuationSnapshot.as_of_date).label("earliest_as_of_date"),
                func.array_agg(latest_liquidity)[1].label("latest_liquidity_class"),
            )
            .where(ManualValuationSnapshot.user_id == user_id)
            .where(ManualValuationSnapshot.superseded_by_id.is_(None))
            .group_by(ManualValuationSnapshot.component_type, ManualValuationSnapshot.source)
            .having(func.min(ManualValuationSnapshot.as_of_date) > as_of_date)
            .order_by(ManualValuationSnapshot.component_type, ManualValuationSnapshot.source)
        )
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
            for row in gap_rows
            if include_restricted or row.latest_liquidity_class not in _RESTRICTED_LIQUIDITY_CLASSES
        ]

        items, excluded_items = split_net_worth_scope(
            [
                ValuationComponentItem(
                    id=snapshot.id,
                    component_type=snapshot.component_type.value,
                    liquidity_class=snapshot.liquidity_class.value,
                    as_of_date=snapshot.as_of_date,
                    value=to_money(snapshot.value),
                    currency=snapshot.currency,
                    source=snapshot.source,
                    provenance="manual",
                )
                for snapshot in snapshots
            ],
            include_restricted=include_restricted,
        )
        liability = ManualValuationLiquidityClass.LIABILITY.value
        total_assets = to_money(sum((item.value for item in items if item.liquidity_class != liability), Decimal("0")))
        total_liabilities = to_money(
            sum((item.value for item in items if item.liquidity_class == liability), Decimal("0"))
        )
        return ValuationComponentsResult(
            items=items,
            total_assets=total_assets,
            total_liabilities=total_liabilities,
            net_worth_delta=to_money(total_assets - total_liabilities),
            warnings=warnings,
            excluded_items=excluded_items,
        )


# ── Balance-sheet lines from manual valuations (absorbed from
# services/reporting/manual_valuation.py, #1610 P2 / AC-pricing.manualvaluation.3).
# Pricing owns the facts (ManualValuationSnapshot) and the FX conversion; an
# FX miss propagates as the pricing error family and the reporting caller owns
# the mapping to its own ReportError. ──


def _valuation_line_name(component_name: str, component_type: str) -> str:
    label = component_type.replace("_", " ")
    return f"Valuation: {component_name} ({label})"


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
    if component_type in {t.value for t in ManualValuationComponentType.restricted_compensation_types()}:
        return "restricted_comp"
    if component_type == ManualValuationComponentType.TAX_REFUND.value:
        return "cash"
    if component_type in {
        ManualValuationComponentType.TAX_PAYABLE.value,
        ManualValuationComponentType.OTHER_LIABILITY.value,
    }:
        return "liability"
    return "other"


def _manual_valuation_line(component: ValuationComponentItem, amount: Decimal | None) -> dict[str, Any]:
    """Build one balance-sheet line from a component and its target-currency amount.

    ``amount`` is None only for an excluded component with no FX rate (see
    ``build_manual_valuation_lines``). An included line always has an amount.
    """
    is_liability = component.liquidity_class == ManualValuationLiquidityClass.LIABILITY.value
    return {
        "account_id": component.id,
        "name": _valuation_line_name(component.source, component.component_type),
        # Plain string, not ledger.AccountType: pricing must not depend on
        # ledger (target dep table, migration-standard.md); AccountType is a
        # str-Enum, so "ASSET"/"LIABILITY" compare/serialize identically to
        # the enum members every consumer of this line dict expects.
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
    asset_lines = sorted((line for line in lines if line["type"] == "ASSET"), key=lambda line: line["name"].lower())
    liability_lines = sorted(
        (line for line in lines if line["type"] == "LIABILITY"), key=lambda line: line["name"].lower()
    )
    return asset_lines, liability_lines


async def build_manual_valuation_lines(
    db: AsyncSession,
    user_id: UUID,
    *,
    as_of_date: date,
    target_currency: str,
    include_restricted: bool = True,
    warnings: list[dict[str, str]] | None = None,
    excluded_lines: list[dict[str, Any]] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Build balance sheet lines from latest manual valuation components.

    ``warnings`` is an optional accumulator (same pattern as the portfolio
    market-adjustment builder): components whose only snapshot postdates
    ``as_of_date`` are absent from the lines, and the caller's report should
    disclose that instead of presenting a silently incomplete total (#1796).

    ``excluded_lines`` is an optional accumulator too. It receives one line in
    ``target_currency`` for each component that the scope excludes
    (``split_net_worth_scope``), so the caller can name what it left out (#2645).
    The totals do not depend on an excluded line. Thus a pricing-family FX error
    on an excluded component does not raise: its line has the amount None and a
    ``conversion_warning`` that names the component, the currency pair and the
    error type. Any other error still raises.

    Raises the pricing error family
    (:class:`~src.pricing.base.errors.PricingError`) when a required FX rate
    is unavailable even after the lazy crawler fallback — the reporting
    caller maps that to its own ``ReportError`` at the boundary.
    """
    # Deferred import: extension/fx.py is a sibling composed by market_data;
    # importing it at module scope would tighten the intra-extension import
    # order for no gain.
    from src.pricing.extension.fx import convert_amount

    # Normalize once up front (matches source_currency's .upper() below) so an
    # already-equal pair (e.g. caller passes lowercase) never triggers a
    # needless FX conversion call.
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
                            # NoObservationError: no stored or fetched rate. Any other
                            # pricing error: the rate exists but the conversion failed.
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
    return _split_manual_valuation_lines(lines)


async def build_manual_valuation_lines_series(
    db: AsyncSession,
    user_id: UUID,
    *,
    as_of_dates: Sequence[date],
    target_currency: str,
    include_restricted: bool = True,
) -> dict[date, tuple[list[dict[str, Any]], list[dict[str, Any]]]]:
    """Return the ``build_manual_valuation_lines`` lines for each date in ``as_of_dates``.

    The lines are equal to one ``build_manual_valuation_lines`` call per date.
    The warnings are not returned. The selected components change only on a
    date that holds a current snapshot. Thus the components are read once per
    such date, not once per requested date. The FX rates are read once per
    source currency. An FX miss raises the pricing error family, as the
    single-date builder does.
    """
    from src.pricing.extension.fx import _convert_money_amount, get_exchange_rate, get_exchange_rate_series

    target_currency = target_currency.upper()
    ordered = sorted(set(as_of_dates))
    if not ordered:
        return {}
    snapshot_dates = sorted(
        (
            await db.execute(
                select(ManualValuationSnapshot.as_of_date)
                .distinct()
                .where(ManualValuationSnapshot.user_id == user_id)
                .where(ManualValuationSnapshot.superseded_by_id.is_(None))
                .where(ManualValuationSnapshot.as_of_date <= ordered[-1])
            )
        )
        .scalars()
        .all()
    )
    selected_snapshot_date: dict[date, date | None] = {}
    for as_of_date in ordered:
        position = bisect_right(snapshot_dates, as_of_date)
        selected_snapshot_date[as_of_date] = snapshot_dates[position - 1] if position else None

    components_by_snapshot_date: dict[date, list[ValuationComponentItem]] = {}
    for snapshot_date in sorted({value for value in selected_snapshot_date.values() if value is not None}):
        components = await ValuationService().get_latest_valuation_components(
            db,
            user_id,
            as_of_date=snapshot_date,
            include_restricted=include_restricted,
        )
        components_by_snapshot_date[snapshot_date] = components.items

    def components_on(as_of_date: date) -> list[ValuationComponentItem]:
        snapshot_date = selected_snapshot_date[as_of_date]
        return components_by_snapshot_date[snapshot_date] if snapshot_date is not None else []

    dates_by_currency: dict[str, list[date]] = {}
    for as_of_date in ordered:
        for component in components_on(as_of_date):
            source_currency = component.currency.upper()
            if source_currency != target_currency:
                dates_by_currency.setdefault(source_currency, []).append(as_of_date)
    rates_by_currency = {
        source_currency: await get_exchange_rate_series(
            db, source_currency, target_currency, rate_dates, lazy_load=True
        )
        for source_currency, rate_dates in dates_by_currency.items()
    }

    series: dict[date, tuple[list[dict[str, Any]], list[dict[str, Any]]]] = {}
    for as_of_date in ordered:
        lines: list[dict[str, Any]] = []
        for component in components_on(as_of_date):
            amount = component.value
            source_currency = component.currency.upper()
            if source_currency != target_currency:
                rate = rates_by_currency[source_currency].get(as_of_date)
                if rate is None:
                    # Raises the same pricing error as the single-date builder.
                    rate = await get_exchange_rate(db, source_currency, target_currency, as_of_date, lazy_load=True)
                # Same normalization and math as convert_amount in the single-date builder.
                source_code = normalize_currency_code(source_currency)
                target_code = normalize_currency_code(target_currency)
                if source_code != target_code:
                    amount = _convert_money_amount(amount, source_code, target_code, rate)
            lines.append(_manual_valuation_line(component, amount))
        series[as_of_date] = _split_manual_valuation_lines(lines)
    return series
