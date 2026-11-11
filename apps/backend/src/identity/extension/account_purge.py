"""Purge throwaway test/QA accounts and all the data they own (#997 item 4)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from uuid import UUID

from sqlalchemy import Table, delete, select
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import Base
from src.identity.extension.sql import User
from src.observability import get_logger

logger = get_logger(__name__)

DEFAULT_TEST_EMAIL_PATTERN = r"^(qa[._].*|e2e[-_].*|load-test[-_].*)@(test\.)?example\.com$"
SAFE_PURGE_ENVIRONMENTS = frozenset({"development", "dev", "local", "test", "testing", "ci", "staging"})


def is_safe_purge_environment(environment: str | None) -> bool:
    return (environment or "").strip().lower() in SAFE_PURGE_ENVIRONMENTS


@dataclass
class PurgeReport:
    matched: list[str] = field(default_factory=list)
    purged: list[str] = field(default_factory=list)
    blocked: list[tuple[str, str]] = field(default_factory=list)
    applied: bool = False

    def summary(self) -> str:
        verb = "Purged" if self.applied else "Would purge"
        mark = "-" if self.applied else "~"
        return "\n".join(
            [
                f"Matched {len(self.matched)} test account(s); {verb} {len(self.purged)}, blocked {len(self.blocked)}.",
                *(f"  {mark} {email}" for email in self.purged),
                *(f"  ! {email} — blocked: {reason}" for email, reason in self.blocked),
            ]
        )


class _DryRunRollback(Exception):
    pass


def owned_tables_in_delete_order() -> list[Table]:
    return [t for t in reversed(Base.metadata.sorted_tables) if t.name != User.__tablename__ and "user_id" in t.c]


async def select_test_user_ids(session: AsyncSession, pattern: str) -> list[tuple[UUID, str]]:
    matcher = re.compile(pattern, re.IGNORECASE)
    result = await session.execute(select(User.id, User.email).order_by(User.email))
    return [(row.id, row.email) for row in result if matcher.match(row.email or "")]


def _block_reason(exc: Exception) -> str:
    cause = getattr(exc, "orig", None) or exc
    text = str(cause).strip()
    return text.splitlines()[0] if text else exc.__class__.__name__


async def _purge_one(session: AsyncSession, user_id: UUID, tables: list[Table]) -> None:
    for table in tables:
        await session.execute(delete(table).where(table.c.user_id == user_id))
    await session.execute(delete(User).where(User.id == user_id))


async def purge_test_accounts(
    session: AsyncSession,
    *,
    pattern: str = DEFAULT_TEST_EMAIL_PATTERN,
    apply: bool = False,
) -> PurgeReport:
    report = PurgeReport(applied=apply)
    users = await select_test_user_ids(session, pattern)
    report.matched = [email for _, email in users]
    if not users:
        return report

    tables = owned_tables_in_delete_order()
    for user_id, email in users:
        try:
            async with session.begin_nested():
                await _purge_one(session, user_id, tables)
                if not apply:
                    raise _DryRunRollback
        except _DryRunRollback:
            report.purged.append(email)
        except (IntegrityError, DBAPIError) as exc:
            reason = _block_reason(exc)
            report.blocked.append((email, reason))
            logger.warning("test-account purge blocked", email=email, reason=reason)
        else:
            report.purged.append(email)
            logger.info("test-account purged", email=email)
    return report
