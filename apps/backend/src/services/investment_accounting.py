"""Brokerage investment transaction accounting service."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.audit.money import Money, to_money
from src.audit.quantity import Quantity
from src.audit.unit_price import UnitPrice
from src.ledger import Entry, Leg, post_entry
from src.models.account import Account, AccountType
from src.models.journal import Direction, JournalEntry
from src.models.layer3 import CostBasisMethod, ManagedPosition, PositionStatus
from src.models.portfolio import (
    DividendIncome,
    DividendType,
    InvestmentLot,
    InvestmentTransaction,
    InvestmentTransactionType,
)

INVESTMENT_QUANTITY_UNIT = "units"


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
        trade_quantity = Quantity(quantity, INVESTMENT_QUANTITY_UNIT).quantize()
        if trade_quantity.is_zero():
            raise InvestmentAccountingValidationError("quantity must round to a non-zero quantity")

        cash_account = await self._get_account(db, user_id, cash_account_id, AccountType.ASSET)
        investment_account = await self._get_account(db, user_id, investment_account_id, AccountType.ASSET)
        buy_price = UnitPrice(unit_price, currency, INVESTMENT_QUANTITY_UNIT)
        gross = (buy_price * trade_quantity + Money(fees, currency)).quantize()
        if not gross.is_positive():
            raise InvestmentAccountingValidationError("buy amount must be positive")
        amount = gross.amount

        position = await self._get_or_create_position(
            db,
            user_id=user_id,
            account_id=investment_account.id,
            asset_identifier=asset_identifier,
            transaction_date=transaction_date,
            currency=currency,
            cost_basis_method=cost_basis_method,
        )
        self._require_position_currency(position, currency)

        # Dr investment / Cr cash — a balanced two-leg transfer. Entry guarantees
        # the balance invariant at construction; post_entry persists + posts it.
        posted = await post_entry(
            db,
            user_id=user_id,
            entry_date=transaction_date,
            memo=f"Buy {asset_identifier}",
            source_id=source_id,
            entry=Entry.transfer(
                debit=investment_account.id,
                credit=cash_account.id,
                money=gross,
                fx_rate=fx_rate,
                event_type="investment_buy",
                tags={"asset_identifier": asset_identifier},
            ),
        )

        transaction = InvestmentTransaction(
            user_id=user_id,
            position_id=position.id,
            journal_entry_id=posted.id,
            source_id=source_id,
            transaction_date=transaction_date,
            transaction_type=InvestmentTransactionType.BUY,
            asset_identifier=asset_identifier,
            quantity=trade_quantity.value,
            unit_price=buy_price.quantize().rate,
            gross_amount=amount,
            fees=to_money(fees),
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
            original_quantity=trade_quantity.value,
            remaining_quantity=trade_quantity.value,
            unit_cost=UnitPrice.from_total(Money(amount, currency), trade_quantity).quantize().rate,
            currency=currency,
        )
        db.add(lot)

        position.quantity = (position.quantity_qty + trade_quantity).quantize().value
        position.cost_basis = (position.cost_basis_money + gross).quantize().amount
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
        trade_quantity = Quantity(quantity, INVESTMENT_QUANTITY_UNIT).quantize()
        if trade_quantity.is_zero():
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
        self._require_position_currency(position, currency)

        sell_price = UnitPrice(unit_price, currency, INVESTMENT_QUANTITY_UNIT)
        net = (sell_price * trade_quantity - Money(fees, currency)).quantize()
        if not net.is_positive():
            raise InvestmentAccountingValidationError("sell proceeds must be positive")
        proceeds = net.amount
        cost_basis = await self._consume_lots(
            db,
            user_id=user_id,
            position=position,
            quantity=trade_quantity,
            method=cost_basis_method,
            disposal_date=transaction_date,
        )
        realized_pnl = to_money(proceeds - cost_basis)

        sell_tags = {"asset_identifier": asset_identifier}
        legs = [
            Leg(cash_account.id, Direction.DEBIT, Money(proceeds, currency), fx_rate, "investment_sell", sell_tags),
            Leg(
                investment_account.id,
                Direction.CREDIT,
                Money(cost_basis, currency),
                fx_rate,
                "investment_sell",
                sell_tags,
            ),
        ]
        if realized_pnl > Decimal("0"):
            legs.append(
                Leg(
                    pnl_account.id,
                    Direction.CREDIT,
                    Money(realized_pnl, currency),
                    fx_rate,
                    "investment_realized_pnl",
                    sell_tags,
                )
            )
        elif realized_pnl < Decimal("0"):
            legs.append(
                Leg(
                    pnl_account.id,
                    Direction.DEBIT,
                    Money(abs(realized_pnl), currency),
                    fx_rate,
                    "investment_realized_pnl",
                    sell_tags,
                )
            )

        posted = await post_entry(
            db,
            user_id=user_id,
            entry_date=transaction_date,
            memo=f"Sell {asset_identifier}",
            source_id=source_id,
            entry=Entry.of(*legs),
        )

        position_quantity = (position.quantity_qty - trade_quantity).quantize()
        position.quantity = position_quantity.value
        position.cost_basis = (position.cost_basis_money - Money(cost_basis, currency)).quantize().amount
        position.realized_pnl = (position.realized_pnl_money + Money(realized_pnl, currency)).quantize().amount
        position.cost_basis_method = cost_basis_method
        if position_quantity.is_zero():
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
            quantity=trade_quantity.value,
            unit_price=sell_price.quantize().rate,
            gross_amount=proceeds,
            fees=to_money(fees),
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
        gross = to_money(gross_amount)
        tax = to_money(withholding_tax)
        net_cash = to_money(gross - tax)

        div_tags = {"asset_identifier": asset_identifier}
        legs = []
        if net_cash > Decimal("0"):
            legs.append(
                Leg(
                    cash_account.id,
                    Direction.DEBIT,
                    Money(net_cash, currency),
                    fx_rate,
                    "investment_dividend",
                    div_tags,
                )
            )
        if tax > Decimal("0") and tax_account is not None:
            legs.append(
                Leg(tax_account.id, Direction.DEBIT, Money(tax, currency), fx_rate, "investment_dividend_tax", div_tags)
            )
        legs.append(
            Leg(income_account.id, Direction.CREDIT, Money(gross, currency), fx_rate, "investment_dividend", div_tags)
        )

        posted = await post_entry(
            db,
            user_id=user_id,
            entry_date=payment_date,
            memo=f"Dividend {asset_identifier}",
            source_id=source_id,
            entry=Entry.of(*legs),
        )

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

    @staticmethod
    def _require_position_currency(position: ManagedPosition, currency: str) -> None:
        """A transaction must be in the position's currency.

        Money arithmetic on the position's typed accessors rejects cross-currency
        mixing; surface that as a clean domain error rather than a raw
        ``CurrencyMismatchError`` (this was a silent currency-blind add before).
        """
        if position.currency != currency:
            raise InvestmentAccountingValidationError(
                f"transaction currency {currency} does not match position currency {position.currency}"
            )

    async def _consume_lots(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        position: ManagedPosition,
        quantity: Quantity,
        method: CostBasisMethod,
        disposal_date: date,
    ) -> Decimal:
        lots = await self._open_lots(db, user_id=user_id, position_id=position.id, method=method)
        zero_quantity = Quantity.zero(INVESTMENT_QUANTITY_UNIT)
        lot_quantities = [(lot, Quantity(lot.remaining_quantity, INVESTMENT_QUANTITY_UNIT).quantize()) for lot in lots]
        total_available = sum((lot_quantity for _, lot_quantity in lot_quantities), zero_quantity)
        if total_available < quantity:
            raise InvestmentAccountingValidationError(
                f"cannot sell {quantity.value} {position.asset_identifier}; only {total_available.value} available"
            )

        if method == CostBasisMethod.AVGCOST:
            total_cost = Money.sum(
                (
                    UnitPrice(lot.unit_cost, position.currency, INVESTMENT_QUANTITY_UNIT) * lot_quantity
                    for lot, lot_quantity in lot_quantities
                ),
                currency=position.currency,
            )
            avg_unit_cost = UnitPrice.from_total(total_cost, total_available).quantize().rate
            for lot in lots:
                lot.unit_cost = avg_unit_cost

        remaining_to_sell = quantity
        cost_basis = Money.zero(position.currency)
        for lot, lot_quantity in lot_quantities:
            if remaining_to_sell.is_zero():
                break
            consumed_quantity = min(
                lot_quantity,
                remaining_to_sell,
            )
            cost_basis += UnitPrice(lot.unit_cost, position.currency, INVESTMENT_QUANTITY_UNIT) * consumed_quantity
            lot_remaining = (lot_quantity - consumed_quantity).quantize()
            lot.remaining_quantity = lot_remaining.value
            if lot_remaining.is_zero():
                lot.disposed_date = disposal_date
            remaining_to_sell = (remaining_to_sell - consumed_quantity).quantize()

        await db.flush()
        return cost_basis.quantize().amount

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
            .where(InvestmentLot.remaining_quantity > Quantity.zero(INVESTMENT_QUANTITY_UNIT).quantize().value)
        )
        if method == CostBasisMethod.LIFO:
            query = query.order_by(InvestmentLot.acquisition_date.desc(), InvestmentLot.created_at.desc())
        else:
            query = query.order_by(InvestmentLot.acquisition_date.asc(), InvestmentLot.created_at.asc())
        return list((await db.execute(query)).scalars().all())

    def _validate_positive(self, value: Decimal, field: str) -> None:
        if value <= Decimal("0"):
            raise InvestmentAccountingValidationError(f"{field} must be positive")

    def _validate_non_negative(self, value: Decimal, field: str) -> None:
        if value < Decimal("0"):
            raise InvestmentAccountingValidationError(f"{field} cannot be negative")
