#!/usr/bin/env python3
"""Anonymize a scratch copy of a prod database snapshot in place (#893).

RL-DATA-2: real data never leaves the prod boundary un-anonymized. This wrapper
drives ``src.runtime.extension.snapshot_anonymizer`` against a database URL that
MUST point at a scratch copy (never prod itself, never live staging) — the
``--i-am-on-a-scratch-copy`` acknowledgement is required for exactly that
reason. The whole transform runs in one transaction: if the residual scan finds
any original sensitive value in the output, everything rolls back (fail closed).

Usage (from the repo root):

    cd apps/backend && uv run python ../../tools/anonymize_snapshot.py \
        --database-url postgresql+psycopg2://user:pass@host/scratch_db \
        --i-am-on-a-scratch-copy

    # classification-only (no database needed): fails on unclassified columns
    cd apps/backend && uv run python ../../tools/anonymize_snapshot.py --check-only

The scale factor defaults to a cryptographically-random integer in [3, 19] and
is deliberately NOT printed or persisted; the HMAC secret defaults to a random
value per run. Neither needs to be remembered — the anonymized copy never has
to be reversed.
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
BACKEND_DIR = ROOT_DIR / "apps" / "backend"
for path in (str(ROOT_DIR), str(BACKEND_DIR)):
    if path not in sys.path:
        sys.path.insert(0, path)

# Populate Base.metadata with every model (same import set as migrations/env.py).
import src.counter.extension.sql  # noqa: E402,F401
import src.identity.extension.sql  # noqa: E402,F401
import src.orm_registry  # noqa: E402,F401
import src.platform.extension.sql  # noqa: E402,F401
from src.database import Base  # noqa: E402
from src.runtime.extension.snapshot_anonymizer import (  # noqa: E402
    ResidualError,
    anonymize,
    classify_columns,
    scan_for_residuals,
)


def _normalize_url(url: str) -> str:
    """Accept the backend's canonical async URL and run it sync.

    The app configures ``postgresql+asyncpg://``; this offline tool uses a
    sync engine, so the async driver marker is swapped for psycopg2 — the
    same normalization migrations/env.py applies.
    """
    return url.replace("+asyncpg", "+psycopg2")


def _get_schema_revision(conn: Any) -> str:
    import sqlalchemy as sa

    try:
        res = conn.execute(
            sa.text("SELECT version_num FROM alembic_version")
        ).scalar_one_or_none()
        if res:
            return str(res)
    except Exception as exc:
        raise RuntimeError(
            f"Unable to read schema revision from alembic_version: {exc}"
        ) from exc
    raise RuntimeError("Missing schema revision in alembic_version table")


def _get_anonymizer_sha() -> str:
    env_sha = os.getenv("GITHUB_SHA")
    if env_sha and len(env_sha) == 40:
        return env_sha
    try:
        res = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            cwd=str(ROOT_DIR),
            timeout=5,
        )
        if res.returncode == 0 and len(res.stdout.strip()) == 40:
            return res.stdout.strip()
    except Exception:
        pass
    return "0" * 40


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--database-url", help="SQLAlchemy URL of the SCRATCH copy to rewrite"
    )
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="Only verify every model column is classified; touches no database",
    )
    parser.add_argument(
        "--i-am-on-a-scratch-copy",
        action="store_true",
        help="Required acknowledgement that the URL is a disposable scratch copy",
    )
    parser.add_argument(
        "--scale-factor",
        type=int,
        default=secrets.choice(range(3, 20)),
        help="Integer money multiplier >= 2 (default: random in [3, 19], not echoed)",
    )
    parser.add_argument(
        "--secret",
        default=secrets.token_hex(32),
        help="HMAC secret for deterministic pseudonyms (default: random per run)",
    )
    parser.add_argument(
        "--emit-audit-proof",
        help="Write intermediate verified audit proof JSON to path upon clean completion",
    )
    args = parser.parse_args(argv)

    plan = classify_columns(Base.metadata)
    print(
        f"classification: {len(plan)} columns across {len(Base.metadata.sorted_tables)} tables — complete"
    )
    if args.check_only:
        return 0

    if not args.database_url:
        parser.error("--database-url is required unless --check-only")
    if not args.i_am_on_a_scratch_copy:
        parser.error(
            "refusing to rewrite a database without --i-am-on-a-scratch-copy "
            "(this tool must never point at prod or live staging; RL-DATA-2)"
        )

    import sqlalchemy as sa

    engine = sa.create_engine(_normalize_url(args.database_url))
    with engine.begin() as conn:
        report = anonymize(
            conn, Base.metadata, secret=args.secret, scale_factor=args.scale_factor
        )
        residuals = scan_for_residuals(conn, Base.metadata, report.original_values)
        if residuals:
            # Raising aborts the enclosing transaction: nothing is committed.
            raise ResidualError(
                f"original sensitive values survived in {sorted(set(residuals))} — rolled back"
            )
        print(
            f"anonymized: {report.tables_updated} tables, "
            f"{report.values_pseudonymized} values pseudonymized, "
            f"{report.json_redacted} JSON payloads redacted, "
            f"residual scan clean"
        )
        if args.emit_audit_proof:
            proof = {
                "status": "passed",
                "classified_columns": len(plan),
                "tables_scanned": len(Base.metadata.tables),
                "residuals_found": 0,
                "source_schema_revision": _get_schema_revision(conn),
                "anonymizer_sha": _get_anonymizer_sha(),
            }
            Path(args.emit_audit_proof).write_text(
                json.dumps(proof, indent=2) + "\n", encoding="utf-8"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
