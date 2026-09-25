"""Reporting domain ports and boundary protocols.

These protocols formalize reporting's narrow-waist interfaces with external L3
packages (ledger balances, manual valuations, portfolio adjustments), eliminating
direct runtime imports of other domains' ORM entities.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any, Protocol, runtime_checkable
from uuid import UUID

from src.ledger import AccountType


@runtime_checkable
class LedgerBalanceProvider(Protocol):
    """Protocol for aggregating account balances from the ledger boundary."""

    async def __call__(
        self,
        user_id: UUID,
        account_types: tuple[AccountType, ...],
        as_of_date: date,
        target_currency: str,
        *,
        fx_warnings: list[dict[str, str]] | None = None,
        included_currencies: set[str] | None = None,
    ) -> dict[UUID, Decimal]:
        """Aggregate ledger balances converted to target presentation currency."""
        ...


@runtime_checkable
class ValuationLinesProvider(Protocol):
    """Protocol for manual valuation line aggregation from the pricing boundary."""

    async def __call__(
        self,
        user_id: UUID,
        *,
        as_of_date: date,
        target_currency: str,
        include_restricted: bool = True,
        warnings: list[dict[str, str]] | None = None,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Build (asset_lines, liability_lines) from manual valuation snapshots."""
        ...


@runtime_checkable
class PortfolioAdjustmentProvider(Protocol):
    """Protocol for portfolio market adjustments from the portfolio boundary."""

    async def __call__(
        self,
        user_id: UUID,
        *,
        as_of_date: date,
        target_currency: str,
        asset_lines: list[dict[str, Any]],
        warnings: list[dict[str, str]] | None = None,
    ) -> list[dict[str, Any]]:
        """Compute mark-to-market adjustment lines for investment holdings."""
        ...
