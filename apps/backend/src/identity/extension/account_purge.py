"""Purge throwaway test/QA accounts and staging tenant data (#997, #3050)."""

from __future__ import annotations

import importlib
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import Column, Table, delete, exists, func, select, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import Base
from src.identity.extension.sql import User
from src.observability import get_logger

logger = get_logger(__name__)

DEFAULT_TEST_EMAIL_PATTERN = (
    r"^(?:"
    r"qa[._].*|qa-(?!staging-verify$)[^@]*|"
    r"e2e[-_].*|load-test[-_].*|agent[-_](?:random|acceptance)[-_].*|"
    r"(?:statements|accounts)_journey[-_].*|recon_(?:disposition|probe)[-_].*|"
    r"journal_(?:create|falsify)[-_].*|case\d+[-_].*|case_ui[-_].*|"
    r"pdf_oracle[-_].*|holdout[-_].*|oracle_\d+[-_].*|"
    r"probe\w*[-_].*|test_(?:bench|wf|ping)[-_].*|test-probe-staging|"
    r"ux_(?:empty|pop|verify|review|bench|extended_walk|browser_walk)[-_].*|"
    r"ui_(?:probe|agent|bench|test)[-_].*|staging_(?:verify|open_verify|adv|e2e_\d+|bsb_.*|real_ai|gap_verify)[-_]?.*|"
    r"staging-playwright\+.*|jui\d+[-_].*|diag(?:_.*|-\w+)?|browser-probe[-_].*|manual-test[-_].*|"
    r"model_probe[-_].*|codex-(?:staging|debug|mobile|api|upload).*|flow_(?:ui_verifier|debug)[-_].*|"
    r"debug[_-].*|poststress\d*[-_].*|ssot_probe_\d+[-_].*|u13_probe[-_].*|bc_probe[-_].*|"
    r"hygiene_test[-_].*|pw_(?:locator_test\d*|test_\d+)|fx-test[-_].*|rl_[ab][-_].*|silk[-_].*|"
    r"bughunt\d*[-_+].*|oos-(?:trial|seq)[-_].*|cf_(?:fetch|check)[-_].*|fetch_me_test[-_].*|"
    r"link_nav[-_].*|links[-_].*|exact_err[-_].*|why-stuck[-_].*|nav_test[-_].*|inspect[-_].*|"
    r"correct_cookie[-_].*|curl_test_cookie|dogfood(?:_bench)?[-_].*|benchmark[-_].*|walk[-_].*|"
    r"s3_probe[-_].*|card_click[-_].*|bsb\d+[-_].*"
    r")@(?:test\.)?example\.com$"
    r"|^qa-(?:sweep|combo|bughunt)-.*@test\.zitian\.party$"
)
PERSISTENT_TEST_EMAILS: frozenset[str] = frozenset(
    {
        "qa_real_statements@test.example.com",
        "qa-staging-verify@test.example.com",
        "ux-cockpit-demo@zitian.party",
        "test@g.cn",
    }
)
SAFE_PURGE_ENVIRONMENTS = frozenset({"development", "dev", "local", "test", "testing", "ci", "staging"})
_TENANT_TRACE_TABLES = ("trace_record_parents", "trace_records")
_PURGE_BATCH_SIZE = 250


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


def _ensure_orm_registry() -> None:
    """Register every ORM model onto Base.metadata without introducing static cross-domain imports."""
    importlib.import_module("src.orm_registry")


def owned_tables_in_delete_order() -> list[Table]:
    """Return every user-owned table in leaf-to-root foreign-key deletion order."""
    _ensure_orm_registry()
    return [t for t in reversed(Base.metadata.sorted_tables) if t.name != User.__tablename__ and "user_id" in t.c]


def _child_fk_links() -> list[tuple[Table, list[tuple[Column[Any], Column[Any]]]]]:
    """Return non-user_id child tables paired with transitive FK hop chains into user-owned tables."""
    _ensure_orm_registry()
    tables = Base.metadata.sorted_tables
    chains: dict[str, list[tuple[Column[Any], Column[Any]]]] = {
        t.name: [] for t in tables if t.name != User.__tablename__ and "user_id" in t.c
    }
    changed = True
    while changed:
        changed = False
        for table in tables:
            if table.name == User.__tablename__ or "user_id" in table.c or table.name in chains:
                continue
            for fk in table.foreign_keys:
                target = fk.column.table.name
                if target != table.name and target in chains:
                    chains[table.name] = [(fk.parent, fk.column), *chains[target]]
                    changed = True
                    break
    return [(table, chains[table.name]) for table in reversed(tables) if table.name in chains and chains[table.name]]


def _owned_target_subquery(chain: Sequence[tuple[Column[Any], Column[Any]]], id_list: Sequence[UUID]):
    """Build nested IN subquery traversing a transitive FK hop chain down from user_id-owned tables."""
    target_ids = select(chain[-1][1]).where(chain[-1][1].table.c.user_id.in_(id_list))
    for i in range(len(chain) - 2, -1, -1):
        target_ids = select(chain[i][1]).where(chain[i + 1][0].in_(target_ids))
    return target_ids


def non_user_child_tables_in_delete_order() -> list[Table]:
    """Return child tables lacking ``user_id`` whose FKs reference user-owned tables."""
    return [table for table, _ in _child_fk_links()]


async def select_test_user_ids(
    session: AsyncSession,
    pattern: str,
    *,
    older_than_days: int | None = None,
    exclude_emails: Iterable[str] = (),
) -> list[tuple[UUID, str]]:
    """Select test account ``(id, email)`` pairs matching regex, age, and allowlist."""
    matcher = re.compile(pattern, re.IGNORECASE)
    excluded = {email.strip().lower() for email in exclude_emails if email and email.strip()}
    stmt = select(User.id, User.email).order_by(User.email)
    if older_than_days is not None and older_than_days > 0:
        cutoff = datetime.now(UTC) - timedelta(days=older_than_days)
        stmt = stmt.where(User.created_at < cutoff)
    result = await session.execute(stmt)
    return [
        (row.id, row.email)
        for row in result
        if row.email and row.email.strip().lower() not in excluded and matcher.match(row.email)
    ]


def _block_reason(exc: Exception) -> str:
    cause = getattr(exc, "orig", None) or exc
    text = str(cause).strip()
    return text.splitlines()[0] if text else exc.__class__.__name__


def _tenant_scope_value(table: Table) -> object:
    col_type = table.c.scope_kind.type
    enum_class = getattr(col_type, "enum_class", None)
    return enum_class["TENANT"] if enum_class is not None else "TENANT"


async def _delete_tenant_batch(
    session: AsyncSession,
    user_ids: Sequence[UUID],
    owned_tables: list[Table],
    child_links: list[tuple[Table, list[tuple[Column[Any], Column[Any]]]]],
    *,
    include_tenant_traces: bool,
) -> None:
    """Delete a batch of users from leaf tables up through child, trace, owned, and user rows."""
    if not user_ids:
        return
    id_list = list(user_ids)
    owned_chain_names = {t.name for t in owned_tables} | {t.name for t, _ in child_links}
    for child_table, chain in child_links:
        local_col = chain[0][0]
        target_ids = _owned_target_subquery(chain, id_list)
        unowned_parents = [
            (fk.parent, fk.column)
            for fk in child_table.foreign_keys
            if fk.column.table.name != User.__tablename__
            and "user_id" not in fk.column.table.c
            and fk.column.table.name not in owned_chain_names
            and fk.column.table.name not in _TENANT_TRACE_TABLES
        ]
        parent_candidates: list[tuple[Column[Any], Column[Any], list[Any]]] = []
        for parent_fk_col, parent_pk_col in unowned_parents:
            rows = (
                (await session.execute(select(parent_fk_col).where(local_col.in_(target_ids)).distinct()))
                .scalars()
                .all()
            )
            if rows:
                parent_candidates.append((parent_fk_col, parent_pk_col, list(rows)))
        await session.execute(delete(child_table).where(local_col.in_(target_ids)))
        for parent_fk_col, parent_pk_col, candidate_ids in parent_candidates:
            for offset in range(0, len(candidate_ids), 1000):
                chunk = candidate_ids[offset : offset + 1000]
                await session.execute(
                    delete(parent_pk_col.table).where(
                        parent_pk_col.in_(chunk),
                        ~exists(select(1).where(parent_fk_col == parent_pk_col)),
                    )
                )
    if include_tenant_traces:
        id_strs = [str(uid) for uid in id_list]
        for trace_table_name in _TENANT_TRACE_TABLES:
            trace_table = Base.metadata.tables.get(trace_table_name)
            if trace_table is not None:
                scope_val = _tenant_scope_value(trace_table)
                await session.execute(
                    delete(trace_table).where(
                        trace_table.c.scope_kind == scope_val,
                        trace_table.c.scope_id.in_(id_strs),
                    )
                )
    for table in owned_tables:
        await session.execute(delete(table).where(table.c.user_id.in_(id_list)))
    await session.execute(delete(User).where(User.id.in_(id_list)))


async def _set_postgresql_replication_role(session: AsyncSession, role: str) -> bool:
    conn = await session.connection()
    if conn.dialect.name != "postgresql":
        return False
    await session.execute(text(f"SET LOCAL session_replication_role = '{role}'"))
    return True


async def purge_test_accounts(
    session: AsyncSession,
    *,
    pattern: str = DEFAULT_TEST_EMAIL_PATTERN,
    older_than_days: int | None = None,
    exclude_emails: Iterable[str] = PERSISTENT_TEST_EMAILS,
    rotate_append_only: bool = False,
    environment: str | None = None,
    apply: bool = False,
) -> PurgeReport:
    """Purge matching test accounts cleanly, or rotate aged staging tenants past append-only triggers."""
    if rotate_append_only and not is_safe_purge_environment(environment):
        raise PermissionError(f"Refusing append-only tenant rotation in unsafe environment {environment!r}")

    report = PurgeReport(applied=apply)
    users = await select_test_user_ids(
        session,
        pattern,
        older_than_days=older_than_days,
        exclude_emails=exclude_emails,
    )
    report.matched = [email for _, email in users]
    if not users:
        return report

    owned_tables = owned_tables_in_delete_order()
    child_links = _child_fk_links()

    if not rotate_append_only:
        for user_id, email in users:
            try:
                async with session.begin_nested():
                    await _delete_tenant_batch(
                        session,
                        [user_id],
                        owned_tables,
                        child_links,
                        include_tenant_traces=False,
                    )
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

    try:
        async with session.begin_nested():
            switched = await _set_postgresql_replication_role(session, "replica")
            try:
                for start in range(0, len(users), _PURGE_BATCH_SIZE):
                    batch_ids = [uid for uid, _ in users[start : start + _PURGE_BATCH_SIZE]]
                    await _delete_tenant_batch(
                        session,
                        batch_ids,
                        owned_tables,
                        child_links,
                        include_tenant_traces=True,
                    )
            finally:
                if switched:
                    await _set_postgresql_replication_role(session, "origin")

            trace_table = Base.metadata.tables.get("trace_records")
            if trace_table is not None:
                scope_val = _tenant_scope_value(trace_table)
                leftover_traces = (
                    await session.execute(
                        select(func.count())
                        .select_from(trace_table)
                        .where(
                            trace_table.c.scope_kind == scope_val,
                            trace_table.c.scope_id.in_([str(uid) for uid, _ in users]),
                        )
                    )
                ).scalar_one()
                if leftover_traces:
                    raise RuntimeError(f"Post-purge check found {leftover_traces} leftover trace_records")

            if not apply:
                raise _DryRunRollback
    except _DryRunRollback:
        report.purged.extend(email for _, email in users)
    else:
        report.purged.extend(email for _, email in users)
        logger.info("staging tenant rotation applied", purged_count=len(users))
    return report
