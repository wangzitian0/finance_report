"""``Currency`` — a validated ISO-4217 alphabetic code, not a bare ``str``.

Construction normalizes (``strip().upper()``) and then rejects anything that is
not an active ISO-4217 alphabetic code, so ``Currency`` cannot hold ``"US"``,
``"usd "`` (un-normalized), ``"XYZ"``, or ``"EURO"``. The soft
``normalize_currency_code`` below only normalizes (``strip().upper()``); this type
adds the ISO-4217 membership check the issue (#1167) requires.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, overload

from src.audit.money.errors import InvalidCurrencyError


@overload
def normalize_currency_code(value: str) -> str: ...


@overload
def normalize_currency_code(value: Any) -> Any: ...


def normalize_currency_code(value: Any) -> Any:
    """Canonical soft normalization of an ISO-4217 code: ``strip().upper()``.

    Single source of truth for the ``str`` normalization that was duplicated as
    inline ``.strip().upper()`` across services/routers and re-defined in
    ``schemas.base`` and ``fx``. Non-``str`` values pass through unchanged so
    downstream validation (Pydantic, :class:`Currency`) raises its own type error.
    This is the *soft* form (no membership check); :class:`Currency` adds that.
    """
    return value.strip().upper() if isinstance(value, str) else value


# Active ISO-4217 alphabetic codes. Deliberately a static, dependency-light set
# (no network / no third-party package) so the backend money module stays importable
# everywhere. Fund codes and the precious-metals X-codes most relevant to
# personal finance (XAU/XAG) are included; codes withdrawn from active use are
# excluded (e.g. HRK — Croatia adopted EUR in 2023). This set is mirrored to the
# conformance vectors and the frontend, so any change here must regenerate both.
ISO_4217_CODES: frozenset[str] = frozenset(
    {
        "AED",
        "AFN",
        "ALL",
        "AMD",
        "ANG",
        "AOA",
        "ARS",
        "AUD",
        "AWG",
        "AZN",
        "BAM",
        "BBD",
        "BDT",
        "BGN",
        "BHD",
        "BIF",
        "BMD",
        "BND",
        "BOB",
        "BRL",
        "BSD",
        "BTN",
        "BWP",
        "BYN",
        "BZD",
        "CAD",
        "CDF",
        "CHF",
        "CLP",
        "CNY",
        "COP",
        "CRC",
        "CUP",
        "CVE",
        "CZK",
        "DJF",
        "DKK",
        "DOP",
        "DZD",
        "EGP",
        "ERN",
        "ETB",
        "EUR",
        "FJD",
        "FKP",
        "GBP",
        "GEL",
        "GHS",
        "GIP",
        "GMD",
        "GNF",
        "GTQ",
        "GYD",
        "HKD",
        "HNL",
        "HTG",
        "HUF",
        "IDR",
        "ILS",
        "INR",
        "IQD",
        "IRR",
        "ISK",
        "JMD",
        "JOD",
        "JPY",
        "KES",
        "KGS",
        "KHR",
        "KMF",
        "KPW",
        "KRW",
        "KWD",
        "KYD",
        "KZT",
        "LAK",
        "LBP",
        "LKR",
        "LRD",
        "LSL",
        "LYD",
        "MAD",
        "MDL",
        "MGA",
        "MKD",
        "MMK",
        "MNT",
        "MOP",
        "MRU",
        "MUR",
        "MVR",
        "MWK",
        "MXN",
        "MYR",
        "MZN",
        "NAD",
        "NGN",
        "NIO",
        "NOK",
        "NPR",
        "NZD",
        "OMR",
        "PAB",
        "PEN",
        "PGK",
        "PHP",
        "PKR",
        "PLN",
        "PYG",
        "QAR",
        "RON",
        "RSD",
        "RUB",
        "RWF",
        "SAR",
        "SBD",
        "SCR",
        "SDG",
        "SEK",
        "SGD",
        "SHP",
        "SLE",
        "SOS",
        "SRD",
        "SSP",
        "STN",
        "SVC",
        "SYP",
        "SZL",
        "THB",
        "TJS",
        "TMT",
        "TND",
        "TOP",
        "TRY",
        "TTD",
        "TWD",
        "TZS",
        "UAH",
        "UGX",
        "USD",
        "UYU",
        "UZS",
        "VED",
        "VES",
        "VND",
        "VUV",
        "WST",
        "XAF",
        "XAG",
        "XAU",
        "XCD",
        "XOF",
        "XPF",
        "YER",
        "ZAR",
        "ZMW",
        "ZWL",
    }
)


@dataclass(frozen=True)
class Currency:
    """An immutable, validated ISO-4217 alphabetic currency code.

    >>> Currency("usd ").code
    'USD'
    >>> Currency("XYZ")
    Traceback (most recent call last):
    src.audit.money.errors.InvalidCurrencyError: ...
    """

    code: str

    def __post_init__(self) -> None:
        raw = self.code
        if not isinstance(raw, str):
            raise InvalidCurrencyError(f"currency code must be a str, got {type(raw).__name__}")
        normalized = raw.strip().upper()
        if normalized not in ISO_4217_CODES:
            raise InvalidCurrencyError(f"not an ISO-4217 currency code: {raw!r}")
        # Frozen dataclass: assign the normalized form via object.__setattr__.
        object.__setattr__(self, "code", normalized)

    @classmethod
    def of(cls, value: Currency | str) -> Currency:
        """Coerce a ``Currency`` or ``str`` into a ``Currency`` (idempotent)."""
        return value if isinstance(value, Currency) else cls(value)

    def __str__(self) -> str:
        return self.code
