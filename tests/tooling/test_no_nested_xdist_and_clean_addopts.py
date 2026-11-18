from __future__ import annotations

import re
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PYPROJECT = REPO_ROOT / "apps" / "backend" / "pyproject.toml"
_NESTED_XDIST_AUTO_RE = re.compile(
    r"""(?:pytest\b[^\n\r;]*?-n\s*=?\s*auto|-n\s*=?\s*auto[^\n\r;]*?pytest\b)"""
)


def test_backend_default_addopts_has_no_xdist_or_coverage_flags() -> None:
    data = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    addopts = data["tool"]["pytest"]["ini_options"]["addopts"]
    joined = " ".join(addopts)
    assert "-n" not in addopts
    assert "--cov=src" not in joined
    assert "--cov-branch" not in addopts
    assert "--cov-fail-under" not in joined


def test_tests_do_not_invoke_nested_pytest_with_xdist_auto() -> None:
    offenders: list[str] = []
    for root in (REPO_ROOT / "tests", REPO_ROOT / "apps" / "backend" / "tests"):
        for path in sorted(root.rglob("*.py")):
            if path.resolve() == Path(__file__).resolve():
                continue
            text = path.read_text(encoding="utf-8")
            for lineno, line in enumerate(text.splitlines(), 1):
                if _NESTED_XDIST_AUTO_RE.search(line):
                    offenders.append(
                        f"{path.relative_to(REPO_ROOT)}:{lineno}: {line.strip()}"
                    )
    assert offenders == [], (
        f"Nested pytest -n auto subprocess calls found: {offenders}"
    )
