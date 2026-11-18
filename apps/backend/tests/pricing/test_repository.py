from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.identity import User
from src.pricing import MarketDataOverride
from src.pricing.base.observation import Authority, ObservationSource
from src.pricing.base.subject import PriceableSubject
from src.pricing.extension.repository import SqlObservationRepository
from src.pricing.orm.manual_valuation import ManualValuationSnapshot
from src.pricing.orm.market_data import FxRate, StockPrice

pytestmark = pytest.mark.asyncio


async def _commit(db: AsyncSession, *objs) -> None:
    db.add_all(objs)
    await db.commit()


async def test_fx_candidates_id_and_as_of_cutoff(db: AsyncSession):
    row = FxRate(base_currency="USD", quote_currency="SGD", rate=Decimal("1.35"), rate_date=date(2026, 1, 1), source="test")
    await _commit(db, row, FxRate(base_currency="USD", quote_currency="SGD", rate=Decimal("1.40"), rate_date=date(2026, 12, 1), source="test"))
    await db.refresh(row)
    cands = await SqlObservationRepository(db).candidates(PriceableSubject.currency_pair("USD", "SGD"), date(2026, 6, 1))
    assert (len(cands), cands[0].id, cands[0].value, cands[0].source, cands[0].authority) == (1, row.id, Decimal("1.35"), ObservationSource.CRAWLER, Authority.CRAWLER)


async def test_security_candidates_combine_sources_and_isolate_users(db: AsyncSession, test_user):
    other = User(email="other-pricing-test@example.com", hashed_password="hashed")
    db.add(other)
    await db.flush()
    await _commit(
        db,
        StockPrice(symbol="AAPL", price=Decimal("180.00"), currency="USD", price_date=date(2026, 6, 1), source="test"),
        MarketDataOverride(user_id=test_user.id, asset_identifier="AAPL", price_date=date(2026, 6, 1), price=Decimal("185.50"), currency="USD"),
        MarketDataOverride(user_id=other.id, asset_identifier="TSLA", price_date=date(2026, 6, 1), price=Decimal("999.00"), currency="USD"),
    )
    repo = SqlObservationRepository(db)
    aapl = await repo.candidates(PriceableSubject.security("AAPL"), date(2026, 6, 15), user_id=test_user.id)
    ov = next(o for o in aapl if o.source is ObservationSource.OVERRIDE)
    tsla = PriceableSubject.security("TSLA")
    assert (
        {o.source for o in aapl},
        ov.authority,
        ov.value,
        await repo.candidates(tsla, date(2026, 6, 15), user_id=test_user.id),
        await repo.candidates(tsla, date(2026, 6, 15), user_id=None),
        len(await repo.candidates(tsla, date(2026, 6, 15), user_id=other.id)),
    ) == ({ObservationSource.CRAWLER, ObservationSource.OVERRIDE}, Authority.OVERRIDE, Decimal("185.50"), [], [], 1)


async def test_component_candidates_user_scope_and_superseded_history(db: AsyncSession, test_user):
    orig = ManualValuationSnapshot(user_id=test_user.id, component_type="cpf_balance", liquidity_class="restricted", as_of_date=date(2026, 6, 1), value=Decimal("100000.00"), currency="SGD", source="user-entry")
    db.add(orig)
    await db.flush()
    corr = ManualValuationSnapshot(id=uuid4(), user_id=test_user.id, component_type="cpf_balance", liquidity_class="restricted", as_of_date=date(2026, 6, 1), value=Decimal("101000.00"), currency="SGD", source="user-entry", version=2, superseded_by_id=orig.id)
    db.add(corr)
    await db.flush()
    orig.superseded_by_id = corr.id
    await db.flush()
    corr.superseded_by_id = None
    await _commit(db, ManualValuationSnapshot(user_id=test_user.id, component_type="property_value", liquidity_class="illiquid", as_of_date=date(2026, 6, 1), value=Decimal("500000.00"), currency="SGD", source="test"))
    repo = SqlObservationRepository(db)
    prop_sub, cpf_sub = PriceableSubject.component("property_value"), PriceableSubject.component("cpf_balance")
    owned = await repo.candidates(prop_sub, date(2026, 6, 15), user_id=test_user.id)
    cpf_cands = await repo.candidates(cpf_sub, date(2026, 6, 15), user_id=test_user.id)
    assert (
        await repo.candidates(prop_sub, date(2026, 6, 15), user_id=None),
        len(owned),
        (owned[0].source, owned[0].authority, owned[0].value),
        {c.value for c in cpf_cands},
    ) == ([], 1, (ObservationSource.MANUAL, Authority.MANUAL, Decimal("500000.00")), {Decimal("100000.00"), Decimal("101000.00")})
