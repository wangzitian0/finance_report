"""Brokerage investment transaction accounting service."""

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.account import Account, AccountType
from src.models.journal import Direction, JournalEntry, JournalEntrySourceType
from src.models.layer3 import CostBasisMethod, ManagedPosition, PositionStatus
from src.models.portfolio import (
    DividendIncome,
    DividendType,
    InvestmentLot,
    InvestmentTransaction,
    InvestmentTransactionType,
)
from src.money import to_money
from src.quantity import Quantity
from src.services.accounting import create_journal_entry, post_journal_entry

INVESTMENT_QUANTITY_UNIT = "units"
UNIT_RATE_QUANTUM = Decimal("0.000001")


class InvestmentAccountingError(Exception):
    """Base exception for investment accounting errors."""


class InvestmentAccountingValidationError(InvestmentAccountingError):
    """Raised when an investment transaction cannot be posted."""


@dataclass(frozen=True)
class InvestmentAccountingResult:
    """Result of posting an investment accounting transaction."""

    transaction: InvestmentTransaction
    journal_entry: JournalEntry
    position: ManagedPosition


def _money(value: Decimal) -> Decimal:
    # Canonical money rounding (banker's / HALF_EVEN). See docs/ssot/accounting.md#decimal-rule.
    return to_money(value)


def _quantized_quantity(value: Decimal) -> Decimal:
    return Quantity(value, INVESTMENT_QUANTITY_UNIT).quantize().value


def _quantity_is_zero(value: Decimal) -> bool:
    return _quantized_quantity(value) == Quantity.zero(INVESTMENT_QUANTITY_UNIT).value


def _quantized_unit_rate(value: Decimal) -> Decimal:
    return value.quantize(UNIT_RATE_QUANTUM, rounding=ROUND_HALF_UP)


class InvestmentAccountingService:
    """Post buy, sell, and dividend transactions into ledger and portfolio state."""

    async def post_buy(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        transaction_date: date,
        asset_identifier: str,
        quantity: Decimal,
        unit_price: Decimal,
        currency: str,
        cash_account_id: UUID,
        investment_account_id: UUID,
        fees: Decimal = Decimal("0.00"),
        fx_rate: Decimal | None = None,
        source_id: UUID | None = None,
        cost_basis_method: CostBasisMethod = CostBasisMethod.FIFO,
    ) -> InvestmentAccountingResult:
        """Post a buy transaction as Dr investment / Cr brokerage cash."""
        self._validate_positive(quantity, "quantity")
        self._validate_non_negative(unit_price, "unit_price")
        self._validate_non_negative(fees, "fees")
        trade_quantity = _quantized_quantity(quantity)
        if _quantity_is_zero(trade_quantity):
            raise InvestmentAccountingValidationError("quantity must round to a non-zero quantity")

        cash_account = await self._get_account(db, user_id, cash_account_id, AccountType.ASSET)
        investment_account = await self._get_account(db, user_id, investment_account_id, AccountType.ASSET)
        amount = _money(trade_quantity * unit_price + fees)
        if amount <= Decimal("0"):
            raise InvestmentAccountingValidationError("buy amount must be positive")

        position = await self._get_or_create_position(
            db,
            user_id=user_id,
            account_id=investment_account.id,
            asset_identifier=asset_identifier,
            transaction_date=transaction_date,
            currency=currency,
            cost_basis_method=cost_basis_method,
        )

        entry = await create_journal_entry(
            db,
            user_id=user_id,
            entry_date=transaction_date,
            memo=f"Buy {asset_identifier}",
            source_type=JournalEntrySourceType.SYSTEM,
            source_id=source_id,
            lines_data=[
                {
                    "account_id": investment_account.id,
                    "direction": Direction.DEBIT,
                    "amount": amount,
                    "currency": currency,
                    "fx_rate": fx_rate,
                    "event_type": "investment_buy",
                    "tags": {"asset_identifier": asset_identifier},
                },
                {
                    "account_id": cash_account.id,
                    "direction": Direction.CREDIT,
                    "amount": amount,
                    "currency": currency,
                    "fx_rate": fx_rate,
                    "event_type": "investment_buy",
                    "tags": {"asset_identifier": asset_identifier},
                },
            ],
        )
        posted = await self._post_and_load(db, entry.id, user_id)

        transaction = InvestmentTransaction(
            user_id=user_id,
            position_id=position.id,
            journal_entry_id=posted.id,
            source_id=source_id,
            transaction_date=transaction_date,
            transaction_type=InvestmentTransactionType.BUY,
            asset_identifier=asset_identifier,
            quantity=trade_quantity,
            unit_price=_quantized_unit_rate(unit_price),
            gross_amount=amount,
            fees=_money(fees),
            currency=currency,
            cost_basis=amount,
            realized_pnl=Decimal("0.00"),
            cost_basis_method=cost_basis_method,
        )
        db.add(transaction)
        await db.flush()

        lot = InvestmentLot(
            user_id=user_id,
            position_id=position.id,
            opening_transaction_id=transaction.id,
            asset_identifier=asset_identifier,
            acquisition_date=transaction_date,
            original_quantity=trade_quantity,
            remaining_quantity=trade_quantity,
            unit_cost=_quantized_unit_rate(amount / trade_quantity),
            currency=currency,
        )
        db.add(lot)

        position.quantity = _quantized_quantity(position.quantity + trade_quantity)
        position.cost_basis = _money(position.cost_basis + amount)
        position.cost_basis_method = cost_basis_method
        position.status = PositionStatus.ACTIVE
        position.disposal_date = None
        await db.flush()
        await db.refresh(transaction)
        await db.refresh(position)
        return InvestmentAccountingResult(transaction=transaction, journal_entry=posted, position=position)

    async def post_sell(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        transaction_date: date,
        asset_identifier: str,
        quantity: Decimal,
        unit_price: Decimal,
        currency: str,
        cash_account_id: UUID,
        investment_account_id: UUID,
        realized_pnl_account_id: UUID,
        fees: Decimal = Decimal("0.00"),
        fx_rate: Decimal | None = None,
        source_id: UUID | None = None,
        cost_basis_method: CostBasisMethod = CostBasisMethod.FIFO,
    ) -> InvestmentAccountingResult:
        """Post a sell transaction and realize gain or loss from investment lots."""
        self._validate_positive(quantity, "quantity")
        self._validate_non_negative(unit_price, "unit_price")
        self._validate_non_negative(fees, "fees")
        trade_quantity = _quantized_quantity(quantity)
        if _quantity_is_zero(trade_quantity):
            raise InvestmentAccountingValidationError("quantity must round to a non-zero quantity")

        cash_account = await self._get_account(db, user_id, cash_account_id, AccountType.ASSET)
        investment_account = await self._get_account(db, user_id, investment_account_id, AccountType.ASSET)
        pnl_account = await self._get_account(db, user_id, realized_pnl_account_id, AccountType.INCOME)
        position = await self._get_position(
            db,
            user_id=user_id,
            account_id=investment_account.id,
            asset_identifier=asset_identifier,
        )

        proceeds = _money(trade_quantity * unit_price - fees)
        if proceeds <= Decimal("0"):
            raise InvestmentAccountingValidationError("sell proceeds must be positive")
        cost_basis = await self._consume_lots(
            db,
            user_id=user_id,
            position=position,
            quantity=trade_quantity,
            method=cost_basis_method,
            disposal_date=transaction_date,
        )
        realized_pnl = _money(proceeds - cost_basis)

        lines = [
            {
                "account_id": cash_account.id,
                "direction": Direction.DEBIT,
                "amount": proceeds,
                "currency": currency,
                "fx_rate": fx_rate,
                "event_type": "investment_sell",
                "tags": {"asset_identifier": asset_identifier},
            },
            {
                "account_id": investment_account.id,
                "direction": Direction.CREDIT,
                "amount": cost_basis,
                "currency": currency,
                "fx_rate": fx_rate,
                "event_type": "investment_sell",
                "tags": {"asset_identifier": asset_identifier},
            },
        ]
        if realized_pnl > Decimal("0"):
            lines.append(
                {
                    "account_id": pnl_account.id,
                    "direction": Direction.CREDIT,
                    "amount": realized_pnl,
                    "currency": currency,
                    "fx_rate": fx_rate,
                    "event_type": "investment_realized_pnl",
                    "tags": {"asset_identifier": asset_identifier},
                }
            )
        elif realized_pnl < Decimal("0"):
            lines.append(
                {
                    "account_id": pnl_account.id,
                    "direction": Direction.DEBIT,
                    "amount": abs(realized_pnl),
                    "currency": currency,
                    "fx_rate": fx_rate,
                    "event_type": "investment_realized_pnl",
                    "tags": {"asset_identifier": asset_identifier},
                }
            )

        entry = await create_journal_entry(
            db,
            user_id=user_id,
            entry_date=transaction_date,
            memo=f"Sell {asset_identifier}",
            source_type=JournalEntrySourceType.SYSTEM,
            source_id=source_id,
            lines_data=lines,
        )
        posted = await self._post_and_load(db, entry.id, user_id)

        position.quantity = _quantized_quantity(position.quantity - trade_quantity)
        position.cost_basis = _money(position.cost_basis - cost_basis)
        position.realized_pnl = _money((position.realized_pnl or Decimal("0.00")) + realized_pnl)
        position.cost_basis_method = cost_basis_method
        if _quantity_is_zero(position.quantity):
            position.status = PositionStatus.DISPOSED
            position.disposal_date = transaction_date

        transaction = InvestmentTransaction(
            user_id=user_id,
            position_id=position.id,
            journal_entry_id=posted.id,
            source_id=source_id,
            transaction_date=transaction_date,
            transaction_type=InvestmentTransactionType.SELL,
            asset_identifier=asset_identifier,
            quantity=trade_quantity,
            unit_price=_quantized_unit_rate(unit_price),
            gross_amount=proceeds,
            fees=_money(fees),
            currency=currency,
            cost_basis=cost_basis,
            realized_pnl=realized_pnl,
            cost_basis_method=cost_basis_method,
        )
        db.add(transaction)
        await db.flush()
        await db.refresh(transaction)
        await db.refresh(position)
        return InvestmentAccountingResult(transaction=transaction, journal_entry=posted, position=position)

    async def post_dividend(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        payment_date: date,
        asset_identifier: str,
        gross_amount: Decimal,
        currency: str,
        cash_account_id: UUID,
        investment_account_id: UUID,
        dividend_income_account_id: UUID,
        withholding_tax: Decimal = Decimal("0.00"),
        withholding_tax_account_id: UUID | None = None,
        fx_rate: Decimal | None = None,
        source_id: UUID | None = None,
        dividend_type: DividendType = DividendType.ORDINARY,
    ) -> InvestmentAccountingResult:
        """Post a dividend transaction as cash plus dividend income."""
        self._validate_positive(gross_amount, "gross_amount")
        self._validate_non_negative(withholding_tax, "withholding_tax")
        if withholding_tax > gross_amount:
            raise InvestmentAccountingValidationError("withholding_tax cannot exceed gross_amount")

        cash_account = await self._get_account(db, user_id, cash_account_id, AccountType.ASSET)
        investment_account = await self._get_account(db, user_id, investment_account_id, AccountType.ASSET)
        income_account = await self._get_account(db, user_id, dividend_income_account_id, AccountType.INCOME)
        tax_account = None
        if withholding_tax > Decimal("0"):
            if withholding_tax_account_id is None:
                raise InvestmentAccountingValidationError("withholding_tax_account_id is required for tax withheld")
            tax_account = await self._get_account(db, user_id, withholding_tax_account_id, AccountType.EXPENSE)

        position = await self._get_position(
            db,
            user_id=user_id,
            account_id=investment_account.id,
            asset_identifier=asset_identifier,
        )
        gross = _money(gross_amount)
        tax = _money(withholding_tax)
        net_cash = _money(gross - tax)

        lines = []
        if net_cash > Decimal("0"):
            lines.append(
                {
                    "account_id": cash_account.id,
                    "direction": Direction.DEBIT,
                    "amount": net_cash,
                    "currency": currency,
                    "fx_rate": fx_rate,
                    "event_type": "investment_dividend",
                    "tags": {"asset_identifier": asset_identifier},
                }
            )
        if tax > Decimal("0") and tax_account is not None:
            lines.append(
                {
                    "account_id": tax_account.id,
                    "direction": Direction.DEBIT,
                    "amount": tax,
                    "currency": currency,
                    "fx_rate": fx_rate,
                    "event_type": "investment_dividend_tax",
                    "tags": {"asset_identifier": asset_identifier},
                }
            )
        lines.append(
            {
                "account_id": income_account.id,
                "direction": Direction.CREDIT,
                "amount": gross,
                "currency": currency,
                "fx_rate": fx_rate,
                "event_type": "investment_dividend",
                "tags": {"asset_identifier": asset_identifier},
            }
        )

        entry = await create_journal_entry(
            db,
            user_id=user_id,
            entry_date=payment_date,
            memo=f"Dividend {asset_identifier}",
            source_type=JournalEntrySourceType.SYSTEM,
            source_id=source_id,
            lines_data=lines,
        )
        posted = await self._post_and_load(db, entry.id, user_id)

        transaction = InvestmentTransaction(
            user_id=user_id,
            position_id=position.id,
            journal_entry_id=posted.id,
            source_id=source_id,
            transaction_date=payment_date,
            transaction_type=InvestmentTransactionType.DIVIDEND,
            asset_identifier=asset_identifier,
            quantity=None,
            unit_price=None,
            gross_amount=gross,
            fees=Decimal("0.00"),
            currency=currency,
            cost_basis=None,
            realized_pnl=None,
            cost_basis_method=position.cost_basis_method,
        )
        dividend = DividendIncome(
            user_id=user_id,
            position_id=position.id,
            payment_date=payment_date,
            amount=gross,
            currency=currency,
            dividend_type=dividend_type,
        )
        db.add_all([transaction, dividend])
        await db.flush()
        await db.refresh(transaction)
        await db.refresh(position)
        return InvestmentAccountingResult(transaction=transaction, journal_entry=posted, position=position)

    async def _get_account(
        self,
        db: AsyncSession,
        user_id: UUID,
        account_id: UUID,
        expected_type: AccountType,
    ) -> Account:
        account = await db.scalar(select(Account).where(Account.id == account_id).where(Account.user_id == user_id))
        if account is None:
            raise InvestmentAccountingValidationError(f"account {account_id} not found")
        if account.type != expected_type:
            raise InvestmentAccountingValidationError(f"account {account.name} must be {expected_type.value}")
        if not account.is_active:
            raise InvestmentAccountingValidationError(f"account {account.name} is inactive")
        return account

    async def _get_or_create_position(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        account_id: UUID,
        asset_identifier: str,
        transaction_date: date,
        currency: str,
        cost_basis_method: CostBasisMethod,
    ) -> ManagedPosition:
        position = await db.scalar(
            select(ManagedPosition)
            .where(ManagedPosition.user_id == user_id)
            .where(ManagedPosition.account_id == account_id)
            .where(ManagedPosition.asset_identifier == asset_identifier)
        )
        if position is not None:
            return position

        position = ManagedPosition(
            user_id=user_id,
            account_id=account_id,
            asset_identifier=asset_identifier,
            quantity=Quantity.zero(INVESTMENT_QUANTITY_UNIT).quantize().value,
            cost_basis=Decimal("0.00"),
            currency=currency,
            acquisition_date=transaction_date,
            status=PositionStatus.ACTIVE,
            cost_basis_method=cost_basis_method,
            realized_pnl=Decimal("0.00"),
        )
        db.add(position)
        await db.flush()
        return position

    async def _get_position(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        account_id: UUID,
        asset_identifier: str,
    ) -> ManagedPosition:
        position = await db.scalar(
            select(ManagedPosition)
            .where(ManagedPosition.user_id == user_id)
            .where(ManagedPosition.account_id == account_id)
            .where(ManagedPosition.asset_identifier == asset_identifier)
        )
        if position is None:
            raise InvestmentAccountingValidationError(f"position {asset_identifier} not found")
        return position

    async def _consume_lots(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        position: ManagedPosition,
        quantity: Decimal,
        method: CostBasisMethod,
        disposal_date: date,
    ) -> Decimal:
        lots = await self._open_lots(db, user_id=user_id, position_id=position.id, method=method)
        total_available = sum((lot.remaining_quantity for lot in lots), Quantity.zero(INVESTMENT_QUANTITY_UNIT).value)
        if total_available < quantity:
            raise InvestmentAccountingValidationError(
                f"cannot sell {quantity} {position.asset_identifier}; only {total_available} available"
            )

        if method == CostBasisMethod.AVGCOST:
            avg_unit_cost = _quantized_unit_rate(
                sum(
                    (_quantized_quantity(lot.remaining_quantity) * lot.unit_cost for lot in lots),
                    Decimal("0.00"),
                )
                / total_available
            )
            for lot in lots:
                lot.unit_cost = avg_unit_cost

        remaining_to_sell = _quantized_quantity(quantity)
        cost_basis = Decimal("0.00")
        for lot in lots:
            if remaining_to_sell <= Quantity.zero(INVESTMENT_QUANTITY_UNIT).value:
                break
            consumed_quantity = min(_quantized_quantity(lot.remaining_quantity), remaining_to_sell)
            cost_basis += consumed_quantity * lot.unit_cost
            lot.remaining_quantity = _quantized_quantity(lot.remaining_quantity - consumed_quantity)
            if _quantity_is_zero(lot.remaining_quantity):
                lot.disposed_date = disposal_date
            remaining_to_sell = _quantized_quantity(remaining_to_sell - consumed_quantity)

        await db.flush()
        return _money(cost_basis)

    async def _open_lots(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        position_id: UUID,
        method: CostBasisMethod,
    ) -> list[InvestmentLot]:
        query = (
            select(InvestmentLot)
            .where(InvestmentLot.user_id == user_id)
            .where(InvestmentLot.position_id == position_id)
            .where(InvestmentLot.remaining_quantity > Quantity.zero(INVESTMENT_QUANTITY_UNIT).value)
        )
        if method == CostBasisMethod.LIFO:
            query = query.order_by(InvestmentLot.acquisition_date.desc(), InvestmentLot.created_at.desc())
        else:
            query = query.order_by(InvestmentLot.acquisition_date.asc(), InvestmentLot.created_at.asc())
        return list((await db.execute(query)).scalars().all())

    async def _post_and_load(self, db: AsyncSession, entry_id: UUID, user_id: UUID) -> JournalEntry:
        posted = await post_journal_entry(db, entry_id, user_id)
        await db.refresh(posted, ["lines"])
        return posted

    def _validate_positive(self, value: Decimal, field: str) -> None:
        if value <= Decimal("0"):
            raise InvestmentAccountingValidationError(f"{field} must be positive")

    def _validate_non_negative(self, value: Decimal, field: str) -> None:
        if value < Decimal("0"):
            raise InvestmentAccountingValidationError(f"{field} cannot be negative")
