"""One runner for the package-owned governance detectors (#2759).

A package provider (``common/<package>/extension/governance_detector.py``) holds a
``{guarantee id: check}`` table and calls :func:`run_detectors`, which owns the
observation shape, the guarantee-id prefix and the exception policy. Stdlib only.
"""

from __future__ import annotations

import ast
from collections.abc import Callable, Mapping
from pathlib import Path

#: A check returns the findings of one guarantee. An empty list means it holds.
Check = Callable[..., list[str]]

#: Failures that turn into a finding instead of ending the run.
SOURCE_ERRORS: tuple[type[Exception], ...] = (OSError, SyntaxError, UnicodeError)


def read_source(repo_root: Path, relative: str) -> str:
    """Return the UTF-8 text of ``relative``; raise ``OSError`` when it is missing."""
    return (repo_root / relative).read_text(encoding="utf-8")


def missing_fragments(
    repo_root: Path, relative: str, fragments: tuple[str, ...]
) -> list[str]:
    """Return one finding per fragment that ``relative`` lacks; whitespace layout is ignored.

    A missing, unreadable or syntactically invalid ``.py`` file is itself a finding.
    """
    path = repo_root / relative
    if not path.is_file():
        return [f"{relative}: file does not exist"]
    try:
        raw_source = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        return [f"{relative}: failed to read: {exc}"]
    if relative.endswith(".py"):
        try:
            ast.parse(raw_source, filename=str(path))
        except SyntaxError as exc:
            return [f"{relative}: syntax error ({type(exc).__name__}): {exc}"]
    source = " ".join(raw_source.split())
    return [
        f"{relative}: missing {fragment}"
        for fragment in fragments
        if " ".join(fragment.split()) not in source
    ]


def requires(relative: str, *fragments: str) -> Check:
    """Build a check that needs every fragment in ``relative``. No fragment would pass on nothing."""
    if not fragments:
        raise ValueError(f"{relative}: requires() needs at least one fragment")
    return lambda repo_root: missing_fragments(repo_root, relative, fragments)


def all_of(*checks: Check) -> Check:
    """Build a check that joins the findings of ``checks`` in order."""
    if not checks:
        raise ValueError("all_of() needs at least one check")
    return lambda repo_root: [
        finding for check in checks for finding in check(repo_root)
    ]


def run_detectors(
    package: str,
    checks: Mapping[str, Check],
    *args: object,
    catch: tuple[type[Exception], ...] = SOURCE_ERRORS,
) -> list[dict[str, object]]:
    """Return one observation per guarantee id of ``checks`` for ``package``.

    ``check(*args)`` returns the findings. An exception in ``catch`` becomes one
    finding of that guarantee; any other exception ends the run.
    """
    if not checks:
        raise ValueError(f"{package}: detector has no checks")
    observations: list[dict[str, object]] = []
    for guarantee_id, check in checks.items():
        try:
            findings = check(*args)
        except catch as exc:
            findings = [f"{guarantee_id}: check failed ({type(exc).__name__}): {exc}"]
        observations.append(
            {
                "guarantee_id": f"{package}/{guarantee_id}",
                "current": len(findings),
                "target": 0,
                "findings": findings,
            }
        )
    return observations


__all__ = [
    "SOURCE_ERRORS",
    "all_of",
    "missing_fragments",
    "read_source",
    "requires",
    "run_detectors",
]
