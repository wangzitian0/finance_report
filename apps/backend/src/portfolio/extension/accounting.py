"""Brokerage investment transaction accounting service."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.audit.money import Currency, Money, to_money
from src.audit.quantity import Quantity, Unit
from src.audit.unit_price import UnitPrice
from src.config_app import get_effective_base_currency
from src.extraction.orm.layer3 import CostBasisMethod, ManagedPosition, PositionStatus
from src.ledger import Account, AccountType, Direction, Entry, JournalEntry, Leg, account_service, post_entry
from src.portfolio.base.errors import InvestmentAccountingValidationError, PortfolioNotFoundError
from src.portfolio.base.types import DividendEvent, TradeAccounts, TradeOrder
from src.portfolio.orm.portfolio import (
    DividendIncome,
    DividendType,
    InvestmentLot,
    InvestmentTransaction,
    InvestmentTransactionType,
)
from src.pricing import get_exchange_rate

INVESTMENT_QUANTITY_UNIT = "units"
DEFAULT_DIVIDEND_INCOME_CODE = "4210"
DEFAULT_SETTLEMENT_CASH_CODE = "1120"


@dataclass(frozen=True)
class InvestmentAccountingResult:
    """Result of posting an investment accounting transaction."""

    transaction: InvestmentTransaction
    journal_entry: JournalEntry
    position: ManagedPosition
    dividend: DividendIncome | None = None


class InvestmentAccountingService:
    """Post buy, sell, and dividend transactions into ledger and portfolio state."""

    def _validate_trade_order(self, order: TradeOrder) -> Quantity:
        self._validate_positive(order.quantity.value, "quantity")
        self._validate_non_negative(order.unit_price.rate, "unit_price")
        self._validate_non_negative(order.fees.amount, "fees")
        trade_quantity = order.quantity.quantize()
        if trade_quantity.is_zero():
            raise InvestmentAccountingValidationError("quantity must round to a non-zero quantity")
        return trade_quantity

    async def post_buy(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        order: TradeOrder,
        accounts: TradeAccounts,
    ) -> InvestmentAccountingResult:
        """Post a buy transaction as Dr investment / Cr brokerage cash."""
        trade_quantity = self._validate_trade_order(order)
        cash_account = await self._get_account(db, user_id, accounts.cash, AccountType.ASSET)
        investment_account = await self._get_account(db, user_id, accounts.investment, AccountType.ASSET)
        buy_price = order.unit_price
        currency = buy_price.currency.code
        gross = (buy_price * trade_quantity + order.fees).quantize()
        if not gross.is_positive():
            raise InvestmentAccountingValidationError("buy amount must be positive")
        amount = gross.amount
        cost_basis_method = CostBasisMethod(order.cost_basis_method)

        position = await self._get_or_create_position(
            db,
            user_id=user_id,
            account_id=investment_account.id,
            asset_identifier=order.asset_identifier,
            transaction_date=order.transaction_date,
            currency=currency,
            cost_basis_method=cost_basis_method,
        )
        self._require_position_currency(position, currency)

        posted = await post_entry(
            db,
            user_id=user_id,
            entry_date=order.transaction_date,
            memo=f"Buy {order.asset_identifier}",
            source_id=order.source_id,
            entry=Entry.transfer(
                debit=investment_account.id,
                credit=cash_account.id,
                money=gross,
                fx_rate=order.fx_rate,
                event_type="investment_buy",
                tags={"asset_identifier": order.asset_identifier},
            ),
        )

        transaction = InvestmentTransaction(
            user_id=user_id,
            position_id=position.id,
            journal_entry_id=posted.id,
            source_id=order.source_id,
            transaction_date=order.transaction_date,
            transaction_type=InvestmentTransactionType.BUY,
            asset_identifier=order.asset_identifier,
            quantity=trade_quantity.value,
            unit_price=buy_price.quantize().rate,
            gross_amount=amount,
            fees=order.fees.quantize().amount,
            currency=currency,
            cost_basis=amount,
            realized_pnl=Decimal("0.00"),
            cost_basis_method=cost_basis_method,
        )
        db.add(transaction)
        await db.flush()

        db.add(
            InvestmentLot(
                user_id=user_id,
                position_id=position.id,
                opening_transaction_id=transaction.id,
                asset_identifier=order.asset_identifier,
                acquisition_date=order.transaction_date,
                original_quantity=trade_quantity.value,
                remaining_quantity=trade_quantity.value,
                unit_cost=UnitPrice.from_total(Money(amount, Currency.of(currency)), trade_quantity).quantize().rate,
                currency=currency,
            )
        )

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
        order: TradeOrder,
        accounts: TradeAccounts,
    ) -> InvestmentAccountingResult:
        """Post a sell transaction and realize gain or loss from investment lots."""
        trade_quantity = self._validate_trade_order(order)
        if accounts.realized_pnl is None:
            raise InvestmentAccountingValidationError("realized_pnl account is required for sell")
        cash_account = await self._get_account(db, user_id, accounts.cash, AccountType.ASSET)
        investment_account = await self._get_account(db, user_id, accounts.investment, AccountType.ASSET)
        pnl_account = await self._get_account(db, user_id, accounts.realized_pnl, AccountType.INCOME)
        position = await self._get_position(
            db, user_id=user_id, account_id=investment_account.id, asset_identifier=order.asset_identifier
        )
        currency = order.unit_price.currency.code
        self._require_position_currency(position, currency)

        sell_price = order.unit_price
        net = (sell_price * trade_quantity - order.fees).quantize()
        if not net.is_positive():
            raise InvestmentAccountingValidationError("sell proceeds must be positive")
        proceeds = net.amount
        cost_basis_method = CostBasisMethod(order.cost_basis_method)
        cost_basis = await self._consume_lots(
            db,
            user_id=user_id,
            position=position,
            quantity=trade_quantity,
            method=cost_basis_method,
            disposal_date=order.transaction_date,
        )
        realized_pnl = to_money(proceeds - cost_basis)

        currency_obj = Currency.of(currency)
        sell_tags = {"asset_identifier": order.asset_identifier}
        legs = [
            Leg(cash_account.id, Direction.DEBIT, Money(proceeds, currency_obj), order.fx_rate, "investment_sell", sell_tags),
            Leg(investment_account.id, Direction.CREDIT, Money(cost_basis, currency_obj), order.fx_rate, "investment_sell", sell_tags),
        ]
        if realized_pnl != Decimal("0"):
            legs.append(
                Leg(
                    pnl_account.id,
                    Direction.CREDIT if realized_pnl > Decimal("0") else Direction.DEBIT,
                    Money(abs(realized_pnl), currency_obj),
                    order.fx_rate,
                    "investment_realized_pnl",
                    sell_tags,
                )
            )

        posted = await post_entry(
            db,
            user_id=user_id,
            entry_date=order.transaction_date,
            memo=f"Sell {order.asset_identifier}",
            source_id=order.source_id,
            entry=Entry.of(*legs),
        )

        position_quantity = (position.quantity_qty - trade_quantity).quantize()
        position.quantity = position_quantity.value
        position.cost_basis = (position.cost_basis_money - Money(cost_basis, currency_obj)).quantize().amount
        position.realized_pnl = (position.realized_pnl_money + Money(realized_pnl, currency_obj)).quantize().amount
        position.cost_basis_method = cost_basis_method
        if position_quantity.is_zero():
            position.status = PositionStatus.DISPOSED
            position.disposal_date = order.transaction_date

        transaction = InvestmentTransaction(
            user_id=user_id,
            position_id=position.id,
            journal_entry_id=posted.id,
            source_id=order.source_id,
            transaction_date=order.transaction_date,
            transaction_type=InvestmentTransactionType.SELL,
            asset_identifier=order.asset_identifier,
            quantity=trade_quantity.value,
            unit_price=sell_price.quantize().rate,
            gross_amount=proceeds,
            fees=order.fees.quantize().amount,
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
        event: DividendEvent,
        accounts: TradeAccounts,
    ) -> InvestmentAccountingResult:
        """Post a dividend transaction as cash plus dividend income."""
        gross_amount = event.gross_amount.amount
        withholding_tax = event.withholding_tax.amount
        currency = event.gross_amount.currency.code
        self._validate_positive(gross_amount, "gross_amount")
        self._validate_non_negative(withholding_tax, "withholding_tax")
        if event.withholding_tax > event.gross_amount:
            raise InvestmentAccountingValidationError("withholding_tax cannot exceed gross_amount")
        if accounts.dividend_income is None:
            raise InvestmentAccountingValidationError("dividend_income account is required for dividend")

        cash_account = await self._get_account(db, user_id, accounts.cash, AccountType.ASSET)
        investment_account = await self._get_account(db, user_id, accounts.investment, AccountType.ASSET)
        income_account = await self._get_account(db, user_id, accounts.dividend_income, AccountType.INCOME)
        tax_account = None
        if withholding_tax > Decimal("0"):
            if accounts.withholding_tax is None:
                raise InvestmentAccountingValidationError("withholding_tax_account_id is required for tax withheld")
            tax_account = await self._get_account(db, user_id, accounts.withholding_tax, AccountType.EXPENSE)

        position = await self._get_position(
            db, user_id=user_id, account_id=investment_account.id, asset_identifier=event.asset_identifier
        )
        gross = to_money(gross_amount)
        tax = to_money(withholding_tax)
        net_cash = to_money(gross - tax)

        currency_obj = Currency.of(currency)
        div_tags = {"asset_identifier": event.asset_identifier}
        legs: list[Leg] = []
        if net_cash > Decimal("0"):
            legs.append(Leg(cash_account.id, Direction.DEBIT, Money(net_cash, currency_obj), event.fx_rate, "investment_dividend", div_tags))
        if tax > Decimal("0") and tax_account is not None:
            legs.append(Leg(tax_account.id, Direction.DEBIT, Money(tax, currency_obj), event.fx_rate, "investment_dividend_tax", div_tags))
        legs.append(Leg(income_account.id, Direction.CREDIT, Money(gross, currency_obj), event.fx_rate, "investment_dividend", div_tags))

        posted = await post_entry(
            db,
            user_id=user_id,
            entry_date=event.payment_date,
            memo=f"Dividend {event.asset_identifier}",
            source_id=event.source_id,
            entry=Entry.of(*legs),
        )

        transaction = InvestmentTransaction(
            user_id=user_id,
            position_id=position.id,
            journal_entry_id=posted.id,
            source_id=event.source_id,
            transaction_date=event.payment_date,
            transaction_type=InvestmentTransactionType.DIVIDEND,
            asset_identifier=event.asset_identifier,
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
            payment_date=event.payment_date,
            amount=gross,
            currency=currency,
            dividend_type=DividendType(event.dividend_type),
        )
        db.add_all([transaction, dividend])
        await db.flush()
        await db.refresh(transaction)
        await db.refresh(dividend)
        await db.refresh(position)
        return InvestmentAccountingResult(
            transaction=transaction, journal_entry=posted, position=position, dividend=dividend
        )

    async def record_holding_dividend(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        ticker: str,
        payment_date: date,
        amount: Decimal,
        currency: str,
        dividend_type: str = "ordinary",
        withholding_tax: Decimal = Decimal("0.00"),
        cash_account_id: UUID | None = None,
        dividend_income_account_id: UUID | None = None,
        withholding_tax_account_id: UUID | None = None,
    ) -> DividendIncome:
        """Resolve holding and default accounts, then post a dividend journal entry (#2673)."""
        position = await db.scalar(
            select(ManagedPosition)
            .where(
                ManagedPosition.user_id == user_id,
                ManagedPosition.asset_identifier == ticker,
                ManagedPosition.status == PositionStatus.ACTIVE,
            )
            .order_by(ManagedPosition.created_at.desc())
        )
        if position is None:
            raise PortfolioNotFoundError("Holding not found")

        ccy = currency.upper()
        resolved_cash_id = cash_account_id or (
            await self._resolve_default_account(
                db,
                user_id=user_id,
                account_type=AccountType.ASSET,
                code=DEFAULT_SETTLEMENT_CASH_CODE,
                name=f"Brokerage Cash ({ccy})",
                currency=ccy,
            )
        ).id
        resolved_income_id = dividend_income_account_id or (
            await self._resolve_default_account(
                db,
                user_id=user_id,
                account_type=AccountType.INCOME,
                code=DEFAULT_DIVIDEND_INCOME_CODE,
                name=f"Dividend Income ({ccy})",
                currency=ccy,
            )
        ).id

        base_currency = (await get_effective_base_currency(db, user_id=user_id)).upper()
        fx_rate = (
            await get_exchange_rate(db, ccy, base_currency, payment_date, lazy_load=True)
            if ccy != base_currency
            else None
        )

        result = await self.post_dividend(
            db,
            user_id=user_id,
            event=DividendEvent(
                payment_date=payment_date,
                asset_identifier=position.asset_identifier,
                gross_amount=Money(amount, Currency.of(ccy)),
                withholding_tax=Money(withholding_tax, Currency.of(ccy)),
                dividend_type=dividend_type,
                fx_rate=fx_rate,
            ),
            accounts=TradeAccounts(
                cash=resolved_cash_id,
                investment=position.account_id,
                dividend_income=resolved_income_id,
                withholding_tax=withholding_tax_account_id,
            ),
        )
        assert result.dividend is not None
        result.dividend.journal_entry_id = result.journal_entry.id  # type: ignore[attr-defined]
        return result.dividend

    async def list_holding_dividends(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        ticker: str,
        limit: int,
        offset: int,
    ) -> list[DividendIncome]:
        """List dividend rows for a holding and attach matching journal_entry_id (#2673)."""
        dividends = list(
            (
                await db.scalars(
                    select(DividendIncome)
                    .join(ManagedPosition, DividendIncome.position_id == ManagedPosition.id)
                    .where(
                        DividendIncome.user_id == user_id,
                        ManagedPosition.user_id == user_id,
                        ManagedPosition.asset_identifier == ticker,
                    )
                    .order_by(DividendIncome.payment_date.desc(), DividendIncome.id.desc())
                    .offset(offset)
                    .limit(limit)
                )
            ).all()
        )
        journal_by_key: dict[tuple[UUID, date, Decimal], UUID] = {}
        if dividends:
            position_ids = {d.position_id for d in dividends}
            txns = (
                await db.scalars(
                    select(InvestmentTransaction)
                    .where(
                        InvestmentTransaction.user_id == user_id,
                        InvestmentTransaction.position_id.in_(position_ids),
                        InvestmentTransaction.transaction_type == InvestmentTransactionType.DIVIDEND,
                        InvestmentTransaction.journal_entry_id.is_not(None),
                    )
                    .order_by(InvestmentTransaction.created_at.desc())
                )
            ).all()
            for txn in txns:
                if txn.position_id is not None and txn.journal_entry_id is not None:
                    journal_by_key.setdefault(
                        (txn.position_id, txn.transaction_date, txn.gross_amount), txn.journal_entry_id
                    )
        for dividend in dividends:
            dividend.journal_entry_id = journal_by_key.get(  # type: ignore[attr-defined]
                (dividend.position_id, dividend.payment_date, dividend.amount)
            )
        return dividends

    async def _resolve_default_account(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        account_type: AccountType,
        code: str,
        name: str,
        currency: str,
    ) -> Account:
        async def find(session: AsyncSession) -> Account | None:
            return await session.scalar(
                select(Account)
                .where(
                    Account.user_id == user_id,
                    Account.type == account_type,
                    Account.currency == currency,
                    Account.is_active.is_(True),
                    or_(Account.code == code, Account.name == name),
                )
                .order_by((Account.code == code).desc(), Account.created_at, Account.id)
                .limit(1)
            )

        return await account_service.find_or_create_account(
            db,
            user_id=user_id,
            find=find,
            build=lambda: Account(user_id=user_id, name=name, code=code, type=account_type, currency=currency),
        )

    async def _get_account(
        self,
        db: AsyncSession,
        user_id: UUID,
        account_id: UUID,
        expected_type: AccountType,
    ) -> Account:
        account = await db.scalar(select(Account).where(Account.id == account_id, Account.user_id == user_id))
        if account is None:
            raise InvestmentAccountingValidationError(f"account {account_id} not found")
        if account.type != expected_type:
            raise InvestmentAccountingValidationError(f"account {account.name} must be {expected_type.value}")
        if not account.is_active:
            raise InvestmentAccountingValidationError(f"account {account.name} is inactive")
        return account

    async def _find_position(
        self, db: AsyncSession, *, user_id: UUID, account_id: UUID, asset_identifier: str
    ) -> ManagedPosition | None:
        return await db.scalar(
            select(ManagedPosition).where(
                ManagedPosition.user_id == user_id,
                ManagedPosition.account_id == account_id,
                ManagedPosition.asset_identifier == asset_identifier,
            )
        )

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
        position = await self._find_position(db, user_id=user_id, account_id=account_id, asset_identifier=asset_identifier)
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
        position = await self._find_position(db, user_id=user_id, account_id=account_id, asset_identifier=asset_identifier)
        if position is None:
            raise InvestmentAccountingValidationError(f"position {asset_identifier} not found")
        return position

    @staticmethod
    def _require_position_currency(position: ManagedPosition, currency: str) -> None:
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
        unit_obj = Unit.of(INVESTMENT_QUANTITY_UNIT)
        currency_obj = Currency.of(position.currency)
        lot_quantities = [(lot, Quantity(lot.remaining_quantity, unit_obj).quantize()) for lot in lots]
        total_available = sum((lot_quantity for _, lot_quantity in lot_quantities), Quantity.zero(unit_obj))
        if total_available < quantity:
            raise InvestmentAccountingValidationError(
                f"cannot sell {quantity.value} {position.asset_identifier}; only {total_available.value} available"
            )

        if method == CostBasisMethod.AVGCOST:
            total_cost = Money.sum(
                (UnitPrice(lot.unit_cost, currency_obj, unit_obj) * lot_qty for lot, lot_qty in lot_quantities),
                currency=currency_obj,
            )
            avg_unit_cost = UnitPrice.from_total(total_cost, total_available).quantize().rate
            for lot in lots:
                lot.unit_cost = avg_unit_cost

        remaining_to_sell = quantity
        cost_basis = Money.zero(currency_obj)
        for lot, lot_quantity in lot_quantities:
            if remaining_to_sell.is_zero():
                break
            consumed_quantity = min(lot_quantity, remaining_to_sell)
            cost_basis += UnitPrice(lot.unit_cost, currency_obj, unit_obj) * consumed_quantity
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
        order_cols = (
            (InvestmentLot.acquisition_date.desc(), InvestmentLot.created_at.desc())
            if method == CostBasisMethod.LIFO
            else (InvestmentLot.acquisition_date.asc(), InvestmentLot.created_at.asc())
        )
        return list(
            (
                await db.scalars(
                    select(InvestmentLot)
                    .where(
                        InvestmentLot.user_id == user_id,
                        InvestmentLot.position_id == position_id,
                        InvestmentLot.remaining_quantity > Quantity.zero(INVESTMENT_QUANTITY_UNIT).quantize().value,
                    )
                    .order_by(*order_cols)
                )
            ).all()
        )

    def _validate_positive(self, value: Decimal, field: str) -> None:
        if value <= Decimal("0"):
            raise InvestmentAccountingValidationError(f"{field} must be positive")

    def _validate_non_negative(self, value: Decimal, field: str) -> None:
        if value < Decimal("0"):
            raise InvestmentAccountingValidationError(f"{field} cannot be negative")
