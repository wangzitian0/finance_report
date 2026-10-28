"""Regression: importing common.audit must not shadow the repo-root ``tests`` package."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_importing_common_audit_keeps_repo_root_tests_package() -> None:
    code = "import common.audit, tests.e2e.auth_cookie as m, sys; print(m.__file__)"
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=REPO_ROOT,
        env={"PYTHONPATH": str(REPO_ROOT), "PATH": ""},
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert Path(result.stdout.strip()) == REPO_ROOT / "tests" / "e2e" / "auth_cookie.py"
