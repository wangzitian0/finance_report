"""Operator alias delegating to ``apps/backend/scripts/purge_test_accounts.py`` (#997, #3050)."""

from __future__ import annotations

import sys
from collections.abc import Sequence
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[3]
BACKEND_DIR = ROOT_DIR / "apps" / "backend"
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(1, str(BACKEND_DIR))

from scripts.purge_test_accounts import _redact, run_cli  # noqa: E402, F401
from src.database import async_session_maker  # noqa: E402
from src.identity import purge_test_accounts  # noqa: E402


def main(argv: Sequence[str] | None = None) -> int:
    return run_cli(
        argv,
        session_maker=async_session_maker,
        purge_fn=purge_test_accounts,
    )


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
