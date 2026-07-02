"""Shared market-data constants, quanta, provider URLs, logger."""

from __future__ import annotations

import re
from datetime import timedelta
from decimal import Decimal

from src.audit.unit_price import UNIT_PRICE_QUANTUM
from src.observability import get_logger

logger = get_logger(__name__)

MARKET_DATA_QUANTITY_UNIT = "units"
_RATE_QUANT = Decimal("0.000001")
# Security prices share the canonical unit-price quantum (6 dp, ROUND_HALF_UP).
_PRICE_QUANT = UNIT_PRICE_QUANTUM
_DEFAULT_INCREMENTAL_LOOKBACK_DAYS = 7
_PROVIDER_DISAGREEMENT_THRESHOLD = Decimal("0.02")
_FRESHNESS_THRESHOLD = timedelta(hours=24)
_YAHOO_FX_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}=X"
_YAHOO_STOCK_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
_YAHOO_CHART_URL = _YAHOO_FX_CHART_URL
_STOOQ_DAILY_URL = "https://stooq.com/q/d/l/"
# A plausible Yahoo ticker is short, alphanumeric, and may carry an exchange/class
# suffix (e.g. AAPL, MSFT, BRK.B, 0700.HK) or be an FX pair (e.g. USDSGD). It never
# contains whitespace and is not free text. Brokerage fund positions store the full
# fund name (e.g. "CSOP USD MONEY MARKET FUND SGX296797238") as the asset identifier,
# which is not a ticker and would 404 against Yahoo on every lookup.
_TICKER_MAX_LENGTH = 15
_TICKER_PATTERN = re.compile(r"^\^?[A-Za-z0-9]+([.\-=][A-Za-z0-9]+)*$")
