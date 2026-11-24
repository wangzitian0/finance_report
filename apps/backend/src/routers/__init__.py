"""API routers package."""

from src.routers import (
    accounts,
    chat,
    journal,
    portfolio,
    pricing,
    reconciliation,
    reports,
    statements,
    user_settings,
    workflow,
)

# NOTE: ``auth`` and ``users`` routers moved into the identity package
# (``src.identity`` — auth_router / users_router) by the #1428 Stage-1 cutover and
# are no longer re-exported here.

__all__ = [
    "accounts",
    "chat",
    "journal",
    "portfolio",
    "pricing",
    "reconciliation",
    "reports",
    "statements",
    "user_settings",
    "workflow",
]
