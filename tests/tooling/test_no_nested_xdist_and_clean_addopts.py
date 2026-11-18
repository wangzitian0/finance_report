from __future__ import annotations

import re
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PYPROJECT = REPO_ROOT / "apps" / "backend" / "pyproject.toml"
_NESTED_XDIST_LINE_RE = re.compile(
    r"""(?:pytest\b[^\n\r;]*?(?:-n|--numprocesses)\s*=?\s*(?:auto|[1-9]\d*)|(?:-n|--numprocesses)\s*=?\s*(?:auto|[1-9]\d*)[^\n\r;]*?pytest\b)"""
)
_NESTED_XDIST_CALL_RE = re.compile(
    r"""pytest[^\)\]]{0,240}(?:-n|--numprocesses)["'\s,=]+(?:auto|[1-9]\d*)""",
    re.DOTALL,
)


def test_backend_default_addopts_has_no_xdist_or_coverage_flags() -> None:
    data = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    addopts = data["tool"]["pytest"]["ini_options"]["addopts"]
    joined = " ".join(addopts)
    assert "-n" not in addopts
    assert "--cov=src" not in joined
    assert "--cov-branch" not in addopts
    assert "--cov-fail-under" not in joined


def test_tests_do_not_invoke_nested_pytest_with_xdist_workers() -> None:
    offenders: list[str] = []
    for root in (REPO_ROOT / "tests", REPO_ROOT / "apps" / "backend" / "tests"):
        for path in sorted(root.rglob("*.py")):
            if path.resolve() == Path(__file__).resolve():
                continue
            text = path.read_text(encoding="utf-8")
            matched_lines = {
                f"{path.relative_to(REPO_ROOT)}:{lineno}: {line.strip()}"
                for lineno, line in enumerate(text.splitlines(), 1)
                if _NESTED_XDIST_LINE_RE.search(line)
            }
            for m in _NESTED_XDIST_CALL_RE.finditer(text):
                lineno = text.count("\n", 0, m.start()) + 1
                matched_lines.add(
                    f"{path.relative_to(REPO_ROOT)}:{lineno}: {m.group(0).splitlines()[0].strip()}"
                )
            offenders.extend(sorted(matched_lines))
    assert offenders == [], f"Nested pytest xdist worker calls found: {offenders}"


def test_nested_xdist_detector_catches_multiline_and_numeric_workers() -> None:
    assert _NESTED_XDIST_CALL_RE.search('subprocess.run(["pytest",\n "-n",\n "auto"])')
    assert _NESTED_XDIST_CALL_RE.search('subprocess.run(["pytest",\n "-n",\n "4"])')
    assert not _NESTED_XDIST_CALL_RE.search('subprocess.run(["pytest", "-n", "0"])')
