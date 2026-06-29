"""API routers package."""

from src.routers import (
    accounts,
    assets,
    chat,
    evidence,
    income,
    journal,
    llm,
    market_data,
    reconciliation,
    reports,
    statements,
)

# NOTE: ``auth`` and ``users`` routers moved into the identity package
# (``src.identity`` — auth_router / users_router) by the #1428 Stage-1 cutover and
# are no longer re-exported here.

__all__ = [
    "accounts",
    "assets",
    "chat",
    "evidence",
    "income",
    "journal",
    "llm",
    "market_data",
    "reconciliation",
    "reports",
    "statements",
]
