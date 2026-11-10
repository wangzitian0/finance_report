from datetime import date; from decimal import Decimal; import httpx; import pytest; from sqlalchemy import select; from sqlalchemy.exc import IntegrityError; from sqlalchemy.ext.asyncio import AsyncSession; from src.config import settings; from src.pricing import get_exchange_rate; from src.pricing.extension import market_data; from src.pricing.orm.market_data import FxRate
async def test_get_exchange_rate_lazy_fetches_provider_when_enabled(db: AsyncSession, monkeypatch):
    'AC5.4.3'
    async def fake_yahoo_fetch(base: str, quote: str, requested_date: date) -> market_data.FxRateObservation: assert (base, quote, requested_date) == ('HKD', 'SGD', date(2025, 6, 30)); return market_data.FxRateObservation(base_currency=base, quote_currency=quote, rate=Decimal('0.173077'), rate_date=requested_date, source='yahoo_finance')
    monkeypatch.setattr(settings, 'market_data_lazy_fetch_enabled', True); monkeypatch.setattr(market_data._providers, '_fetch_yahoo_fx_rate', fake_yahoo_fetch); result = await get_exchange_rate(db, 'HKD', 'SGD', date(2025, 6, 30), lazy_load=True); assert result == Decimal('0.173077'); persisted = await db.execute(select(FxRate).where(FxRate.base_currency == 'HKD', FxRate.quote_currency == 'SGD', FxRate.rate_date == date(2025, 6, 30))); provider_rate = persisted.scalar_one(); assert provider_rate.rate == Decimal('0.173077'); assert provider_rate.source == 'yahoo_finance'
async def test_resolve_missing_fx_rate_same_currency_returns_identity(db: AsyncSession): 'AC5.4.3'; result = await market_data.resolve_missing_fx_rate(db, 'sgd', 'SGD', date(2025, 6, 30)); assert result == Decimal('1')
async def test_resolve_missing_fx_rate_returns_stored_direct_rate(db: AsyncSession): 'AC5.4.3'; db.add(FxRate(base_currency='HKD', quote_currency='SGD', rate=Decimal('0.173000'), rate_date=date(2025, 6, 29), source='test')); await db.commit(); result = await market_data.resolve_missing_fx_rate(db, 'hkd', 'sgd', date(2025, 6, 30)); assert result == Decimal('0.173000')
async def test_resolve_missing_fx_rate_returns_none_when_provider_misses(db: AsyncSession, monkeypatch):
    'AC5.4.3'
    async def fake_provider_fetch(_base: str, _quote: str, _requested_date: date) -> None: return None
    monkeypatch.setattr(settings, 'market_data_lazy_fetch_enabled', True); monkeypatch.setattr(market_data._providers, '_fetch_yahoo_or_derived_fx_rate', fake_provider_fetch); result = await market_data.resolve_missing_fx_rate(db, 'HKD', 'SGD', date(2025, 6, 30)); assert result is None
async def test_persist_fx_rate_keeps_existing_same_day_rate(db: AsyncSession): 'AC5.4.3'; db.add(FxRate(base_currency='HKD', quote_currency='SGD', rate=Decimal('0.173000'), rate_date=date(2025, 6, 30), source='manual')); await db.commit(); result = await market_data._persist_fx_rate(db, market_data.FxRateObservation(base_currency='hkd', quote_currency='sgd', rate=Decimal('0.180000'), rate_date=date(2025, 6, 30), source='yahoo_finance')); assert result == Decimal('0.173000'); persisted = await db.execute(select(FxRate).where(FxRate.base_currency == 'HKD', FxRate.quote_currency == 'SGD')); rate = persisted.scalar_one(); assert rate.rate == Decimal('0.173000'); assert rate.source == 'manual'
async def test_persist_fx_rate_handles_concurrent_insert():
    'AC5.4.3'
    class Row: rate = Decimal('0.173500'); rate_date = date(2025, 6, 30); source = 'concurrent'
    class Result:
        def __init__(self, row): self._row = row
        def one_or_none(self): return self._row
    class NestedTransaction:
        async def __aenter__(self): return self
        async def __aexit__(self, *_exc_info): return False
    class FakeSession:
        def __init__(self): self.execute_calls = 0; self.rolled_back = False; self.added = None
        async def execute(self, _stmt): self.execute_calls += 1; return Result(None if self.execute_calls == 1 else Row())
        def add(self, value): self.added = value
        async def flush(self): raise IntegrityError('insert fx', {}, Exception('duplicate'))
        async def rollback(self): self.rolled_back = True
        def begin_nested(self): return NestedTransaction()
    session = FakeSession(); result = await market_data._persist_fx_rate(session, market_data.FxRateObservation(base_currency='HKD', quote_currency='SGD', rate=Decimal('0.173077'), rate_date=date(2025, 6, 30), source='yahoo_finance')); assert result == Decimal('0.173500'); assert session.rolled_back is False; assert session.added is not None
async def test_persist_fx_rate_reraises_integrity_error_without_concurrent_rate():
    'AC5.4.3'
    class Result:
        def one_or_none(self): return None
    class NestedTransaction:
        async def __aenter__(self): return self
        async def __aexit__(self, *_exc_info): return False
    class FakeSession:
        async def execute(self, _stmt): return Result()
        def add(self, _value): return None
        async def flush(self): raise IntegrityError('insert fx', {}, Exception('duplicate'))
        async def rollback(self): return None
        def begin_nested(self): return NestedTransaction()
    with pytest.raises(IntegrityError): await market_data._persist_fx_rate(FakeSession(), market_data.FxRateObservation(base_currency='HKD', quote_currency='SGD', rate=Decimal('0.173077'), rate_date=date(2025, 6, 30), source='yahoo_finance'))
async def test_fetch_yahoo_or_derived_fx_rate_uses_inverse(monkeypatch):
    'AC5.4.3'
    async def fake_fetch(base: str, quote: str, requested_date: date) -> market_data.FxRateObservation | None:
        if (base, quote, requested_date) == ('SGD', 'HKD', date(2025, 6, 30)): return market_data.FxRateObservation(base_currency=base, quote_currency=quote, rate=Decimal('5.800000'), rate_date=requested_date, source='yahoo_finance')
        return None
    monkeypatch.setattr(market_data._providers, '_fetch_yahoo_fx_rate', fake_fetch); result = await market_data._fetch_yahoo_or_derived_fx_rate('HKD', 'SGD', date(2025, 6, 30)); assert result == market_data.FxRateObservation(base_currency='HKD', quote_currency='SGD', rate=Decimal('0.172414'), rate_date=date(2025, 6, 30), source='yahoo_finance:inverse')
async def test_fetch_yahoo_or_derived_fx_rate_uses_bridge(monkeypatch):
    'AC5.4.3'
    async def fake_fetch(base: str, quote: str, requested_date: date) -> market_data.FxRateObservation | None: observations = {('HKD', 'USD'): market_data.FxRateObservation(base_currency='HKD', quote_currency='USD', rate=Decimal('0.128205'), rate_date=date(2025, 6, 29), source='yahoo_finance'), ('USD', 'SGD'): market_data.FxRateObservation(base_currency='USD', quote_currency='SGD', rate=Decimal('1.350000'), rate_date=date(2025, 6, 30), source='yahoo_finance')}; assert requested_date == date(2025, 6, 30); return observations.get((base, quote))
    monkeypatch.setattr(settings, 'market_data_fx_bridge_currency', 'USD'); monkeypatch.setattr(market_data._providers, '_fetch_yahoo_fx_rate', fake_fetch); result = await market_data._fetch_yahoo_or_derived_fx_rate('HKD', 'SGD', date(2025, 6, 30)); assert result == market_data.FxRateObservation(base_currency='HKD', quote_currency='SGD', rate=Decimal('0.173077'), rate_date=date(2025, 6, 30), source='yahoo_finance:bridge:USD')
async def test_fetch_yahoo_or_derived_fx_rate_skips_bridge_when_bridge_is_pair_currency(monkeypatch):
    'AC5.4.3'
    async def fake_fetch(_base: str, _quote: str, _requested_date: date) -> None: return None
    monkeypatch.setattr(settings, 'market_data_fx_bridge_currency', 'SGD'); monkeypatch.setattr(market_data._providers, '_fetch_yahoo_fx_rate', fake_fetch); result = await market_data._fetch_yahoo_or_derived_fx_rate('HKD', 'SGD', date(2025, 6, 30)); assert result is None
async def test_fetch_yahoo_or_derived_fx_rate_returns_none_when_bridge_leg_missing(monkeypatch):
    'AC5.4.3'
    async def fake_fetch(base: str, quote: str, _requested_date: date) -> market_data.FxRateObservation | None:
        if (base, quote) == ('HKD', 'USD'): return market_data.FxRateObservation(base_currency='HKD', quote_currency='USD', rate=Decimal('0.128205'), rate_date=date(2025, 6, 30), source='yahoo_finance')
        return None
    monkeypatch.setattr(settings, 'market_data_fx_bridge_currency', 'USD'); monkeypatch.setattr(market_data._providers, '_fetch_yahoo_fx_rate', fake_fetch); result = await market_data._fetch_yahoo_or_derived_fx_rate('HKD', 'SGD', date(2025, 6, 30)); assert result is None
async def test_fetch_yahoo_fx_rate_success(monkeypatch):
    'AC5.4.3'; calls = []; payload = {'chart': {'result': [{'timestamp': [market_data._date_to_epoch(date(2025, 6, 29))], 'indicators': {'quote': [{'close': [0.173077]}]}}]}}
    class FakeClient:
        def __init__(self, *, timeout, headers): self.timeout = timeout; self.headers = headers
        async def __aenter__(self): return self
        async def __aexit__(self, _exc_type, _exc, _traceback): return False
        async def get(self, url, params): calls.append((self.timeout, self.headers, url, params)); return httpx.Response(200, json=payload, request=httpx.Request('GET', url))
    monkeypatch.setattr(market_data.httpx, 'AsyncClient', FakeClient); result = await market_data._fetch_yahoo_fx_rate('HKD', 'SGD', date(2025, 6, 30)); assert result == market_data.FxRateObservation(base_currency='HKD', quote_currency='SGD', rate=Decimal('0.173077'), rate_date=date(2025, 6, 29), source='yahoo_finance'); timeout, headers, url, params = calls[0]; assert timeout == settings.market_data_yahoo_timeout_seconds; assert headers['User-Agent'] == 'finance-report-audit/1.0'; assert url == 'https://query1.finance.yahoo.com/v8/finance/chart/HKDSGD=X'; assert params['interval'] == '1d'
async def test_fetch_yahoo_fx_rate_returns_none_on_http_error(monkeypatch):
    'AC5.4.3'
    class FailingClient:
        def __init__(self, *, timeout, headers): self.timeout = timeout; self.headers = headers
        async def __aenter__(self): return self
        async def __aexit__(self, _exc_type, _exc, _traceback): return False
        async def get(self, url, params): raise httpx.ConnectError('offline', request=httpx.Request('GET', url))
    monkeypatch.setattr(market_data.httpx, 'AsyncClient', FailingClient); result = await market_data._fetch_yahoo_fx_rate('HKD', 'SGD', date(2025, 6, 30)); assert result is None
def test_parse_yahoo_fx_response_selects_latest_on_or_before_requested_date(): 'AC5.4.3'; payload = {'chart': {'result': [{'timestamp': [market_data._date_to_epoch(date(2025, 6, 28)), market_data._date_to_epoch(date(2025, 6, 29)), market_data._date_to_epoch(date(2025, 7, 1))], 'indicators': {'quote': [{'close': [None, 0.1730774, 0.2]}]}}]}}; rows = market_data._parse_yahoo_fx_response_series(payload, 'HKD', 'SGD', date.min, date(2025, 6, 30)); result = max(rows, key=lambda item: item.rate_date, default=None); assert result == market_data.FxRateObservation(base_currency='HKD', quote_currency='SGD', rate=Decimal('0.173077'), rate_date=date(2025, 6, 29), source='yahoo_finance'); 'AC5.4.3'; 'AC5.4.3'; assert market_data._parse_yahoo_fx_response_series({}, 'HKD', 'SGD', date.min, date(2025, 6, 30)) == []; assert market_data._parse_yahoo_fx_response_series({'chart': {'result': [{'timestamp': [market_data._date_to_epoch(date(2025, 7, 1))], 'indicators': {'quote': [{'close': [0.2]}]}}]}}, 'HKD', 'SGD', date.min, date(2025, 6, 30)) == []
