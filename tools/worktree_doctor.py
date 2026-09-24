#!/usr/bin/env python3
"""Multi-worker worktree lifecycle doctor (AC-testing.preflight.4).

Audits local git worktrees against active process locks (lsof), GitHub PR status
(gh pr view), and uncommitted working-tree dirt.

    python tools/worktree_doctor.py             # inspect all worktrees
    python tools/worktree_doctor.py --check     # fail non-zero on orphans/leakage
    python tools/worktree_doctor.py --prune     # safely prune verified orphans
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from common.testing.extension.worktree_doctor import (  # noqa: E402
    audit_worktrees,
    main,
    prune_worktrees,
    run_doctor,
)

__all__ = ["audit_worktrees", "main", "prune_worktrees", "run_doctor"]

if __name__ == "__main__":
    raise SystemExit(main())
