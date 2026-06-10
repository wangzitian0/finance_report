#!/usr/bin/env python3
"""Backfill Layer 1/2 (uploaded_documents + atomic_transactions) from legacy Layer 0.

EPIC-011 Stage 2a: project historical ``BankStatement`` data into the 4-layer
tables so the Layer-2 read path has full coverage before ``ENABLE_4_LAYER_READ``
is turned on. Idempotent — safe to re-run.

Usage:
    # Local development
    python tools/backfill_layer2.py --env local

    # Staging / production (requires DATABASE_URL)
    DATABASE_URL=... python tools/backfill_layer2.py --env production

    # Scope to a single user
    python tools/backfill_layer2.py --env local --user-id <uuid>

Backend imports (`src.*`, `sqlalchemy`) are deferred into the functions so that
importing this module has no side effects (no ``sys.path`` mutation, no heavy
imports). This keeps the wrapper-bootstrap contract in
``tests/tooling/test_common_tooling_modules.py`` deterministic.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path
from uuid import UUID

REPO_ROOT = Path(__file__).resolve().parents[3]


def _ensure_backend_importable() -> None:
    """Append apps/backend to sys.path so ``src.*`` resolves. Append (never
    insert at 0) so a wrapper that bootstrapped the repo root keeps it first."""
    backend_path = str(REPO_ROOT / "apps" / "backend")
    if backend_path not in sys.path:
        sys.path.append(backend_path)


def get_database_url(env: str) -> str:
    if env in ("staging", "production"):
        database_url = os.getenv("DATABASE_URL")
        if not database_url:
            raise SystemExit(f"DATABASE_URL must be set for env={env}")
        return database_url
    _ensure_backend_importable()
    from src.config import settings

    return os.getenv("DATABASE_URL", settings.database_url)


async def run(env: str, user_id: UUID | None) -> int:
    _ensure_backend_importable()
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from src.services.deduplication import backfill_atomic_transactions_from_statements

    engine = create_async_engine(get_database_url(env))
    maker = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with maker() as session:
            result = await backfill_atomic_transactions_from_statements(
                session, user_id=user_id
            )
            await session.commit()
    finally:
        await engine.dispose()

    print(
        "Layer 2 backfill complete: "
        f"statements_scanned={result['statements_scanned']} "
        f"documents_created={result['documents_created']} "
        f"atomic_transactions_upserted={result['atomic_transactions_upserted']}"
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Backfill Layer 1/2 from legacy Layer 0 statements."
    )
    parser.add_argument(
        "--env", default="local", choices=["local", "staging", "production"]
    )
    parser.add_argument(
        "--user-id",
        default=None,
        help="Optional UUID to scope the backfill to one user.",
    )
    args = parser.parse_args()

    user_id = UUID(args.user_id) if args.user_id else None
    return asyncio.run(run(args.env, user_id))


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
