"""Purge throwaway test/QA accounts and all the data they own (#997 item 4).

E2E and QA runs leave behind disposable accounts (``qa.*@example.com``,
``e2e-*@test.example.com``, ...) on shared/staging databases. This module finds
those accounts and removes them together with every row they own.

Design constraints that shape this module:

- **There is no admin delete API.** ``DELETE /api/users/{id}`` is self-scoped
  (a user may only delete their own account), so bulk cleanup has to run against
  the database directly.
- **The ledger is immutable.** A DB trigger rejects deletion of ``posted`` /
  ``reconciled`` / ``void`` journal entries (see ``models/journal.py`` and #988).
  We do NOT try to defeat that guard — an account that still owns immutable
  ledger entries is reported as *blocked* and left untouched, mirroring the
  409 the API returns ("void those entries first").
- **Atomic per account.** Each account is purged inside its own SAVEPOINT. It is
  either fully removed or, on any error, fully rolled back and reported — never
  left half-deleted. Safety therefore does not depend on perfect delete ordering.
- **Explicit ordered deletes, not user-FK cascade.** We delete each owned table
  by ``user_id`` in reverse-dependency order rather than relying on the
  ``ON DELETE CASCADE`` that ``UserOwnedMixin`` puts on ``user_id``. That cascade
  exists in the production schema but is stripped from the test schema (conftest's
  ``_strip_user_fks``), so deleting explicitly keeps one code path exercised in
  both — and makes the purge robust even where the cascade is missing.

The dry-run path executes the deletes inside the savepoint and then rolls back,
so a dry run reports exactly which accounts *would* be purged and which are
blocked — without persisting anything.

Transaction boundary: this service never calls ``commit()`` (see EPIC-012
AC12.26.1). In ``apply`` mode the successful deletes are released into the outer
transaction via per-account savepoints; the **caller** owns the final commit. In
dry-run mode every savepoint is rolled back, so the caller has nothing to commit.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from uuid import UUID

from sqlalchemy import Table, delete, select
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import Base
from src.logger import get_logger
from src.models import User

logger = get_logger(__name__)

# Default predicate for "this is a disposable test account". Intentionally narrow:
# it matches the qa/e2e/load-test prefixes used by the suites on the example.com
# and test.example.com domains, not every address that merely ends in example.com
# (real fixtures sometimes use plain user@example.com locally). Override via the
# CLI when a one-off pattern is needed.
DEFAULT_TEST_EMAIL_PATTERN = r"^(qa[._].*|e2e[-_].*|load-test[-_].*)@(test\.)?example\.com$"

# Environments where applying the purge is allowed. Production (or anything not on
# this list) must be refused unless the operator passes an explicit override, so a
# misconfigured ENVIRONMENT can never silently delete real accounts.
SAFE_PURGE_ENVIRONMENTS = frozenset({"development", "dev", "local", "test", "testing", "ci", "staging"})


def is_safe_purge_environment(environment: str | None) -> bool:
    """True when ``--apply`` is allowed without an explicit override."""
    return (environment or "").strip().lower() in SAFE_PURGE_ENVIRONMENTS


@dataclass
class PurgeReport:
    """Outcome of a purge run."""

    matched: list[str] = field(default_factory=list)
    purged: list[str] = field(default_factory=list)
    blocked: list[tuple[str, str]] = field(default_factory=list)
    applied: bool = False

    def summary(self) -> str:
        verb = "Purged" if self.applied else "Would purge"
        lines = [
            f"Matched {len(self.matched)} test account(s); {verb} {len(self.purged)}, blocked {len(self.blocked)}."
        ]
        for email in self.purged:
            lines.append(f"  {'-' if self.applied else '~'} {email}")
        for email, reason in self.blocked:
            lines.append(f"  ! {email} — blocked: {reason}")
        return "\n".join(lines)


class _DryRunRollback(Exception):
    """Internal sentinel: unwinds a savepoint so a dry run persists nothing."""


def _compiled(pattern: str) -> re.Pattern[str]:
    return re.compile(pattern, re.IGNORECASE)


def owned_tables_in_delete_order() -> list[Table]:
    """User-owned tables (those carrying a ``user_id`` column), children first.

    ``Base.metadata.sorted_tables`` is in dependency order (referenced tables
    first); reversing it deletes the most-dependent tables first. Tables without
    a ``user_id`` column (pure join/child tables such as ``journal_lines`` or
    ``reconciliation_matches``) are omitted here: they are removed via their
    intra-aggregate ``ON DELETE CASCADE`` when their user-owned parent row goes.
    ``users`` itself is excluded — the caller deletes it last.
    """
    tables: list[Table] = []
    for table in reversed(Base.metadata.sorted_tables):
        if table.name == User.__tablename__:
            continue
        if "user_id" in table.c:
            tables.append(table)
    return tables


async def select_test_user_ids(session: AsyncSession, pattern: str) -> list[tuple[UUID, str]]:
    """Return ``(id, email)`` for every account whose email matches ``pattern``."""
    matcher = _compiled(pattern)
    result = await session.execute(select(User.id, User.email).order_by(User.email))
    return [(row.id, row.email) for row in result if matcher.match(row.email or "")]


def _block_reason(exc: Exception) -> str:
    """Human-readable reason a single account could not be purged."""
    cause = getattr(exc, "orig", None) or exc
    text = str(cause).strip().splitlines()[0] if str(cause).strip() else exc.__class__.__name__
    return text


async def _purge_one(session: AsyncSession, user_id: UUID, tables: list[Table]) -> None:
    """Delete every owned row for ``user_id`` then the user. No commit/rollback."""
    for table in tables:
        await session.execute(delete(table).where(table.c.user_id == user_id))
    await session.execute(delete(User.__table__).where(User.__table__.c.id == user_id))


async def purge_test_accounts(
    session: AsyncSession,
    *,
    pattern: str = DEFAULT_TEST_EMAIL_PATTERN,
    apply: bool = False,
) -> PurgeReport:
    """Find and purge disposable test accounts.

    Each account is processed in its own SAVEPOINT: released into the outer
    transaction when ``apply`` is true and the delete succeeds, rolled back
    otherwise (dry run, or blocked by the ledger-immutability guard). The
    function never leaves an account half-deleted and never commits — the caller
    commits the outer transaction in ``apply`` mode.
    """
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
                    # Unwind the savepoint so a dry run leaves no trace, while
                    # still proving the delete would have succeeded.
                    raise _DryRunRollback
        except _DryRunRollback:
            report.purged.append(email)
        except (IntegrityError, DBAPIError) as exc:
            # The savepoint is already rolled back by the context manager.
            reason = _block_reason(exc)
            report.blocked.append((email, reason))
            logger.warning("test-account purge blocked", email=email, reason=reason)
        else:
            report.purged.append(email)
            logger.info("test-account purged", email=email)

    return report
