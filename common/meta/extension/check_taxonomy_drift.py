"""Taxonomy-drift gate — retired package-model vocabulary must read as history.

The package model migrated in-place, so its old vocabulary still appears in
prose all over the repo. Some of it is *legitimate history* ("replaces
kernel/platform/core"); some of it is *drift* — a doc/EPIC/SSOT entry/test
teaching the retired model as current truth. The two are distinguishable
mechanically: a legitimate mention sits next to a historical marker.

Retired vocabulary (each -> its replacement):

- klass ``kernel < platform < core``        -> the five-layer ``PACKAGE_LAYER``
  (incl. ``klass="kernel|platform|core"``)     map (``meta<infra<middleware<
                                                domain<app``, L0-owned)
- ``types/ops/store/api`` role folders /    -> ``base/extension/data`` layers
  "converge by role"
- ``asset_evaluation``                      -> the ``pricing`` package (#1610)
- `` `kernel` `` as a class word            -> the package's five-layer slot

A mention passes when a marker (``formerly``/``replaces``/``retired``/...)
appears on the same line or within :data:`MARKER_WINDOW` lines above — that is
how the surviving historical notes are written. Anything else fails the gate:
either fix the prose to the current model or mark it as history.

**stdlib-only by design**, like its siblings: runnable from the lightweight CI
lint env and from ``tools/check_taxonomy_drift.py``. Registered in preflight
(``common/testing/preflight.py``) so a doc/test edit runs it locally, and
enforced in CI through ``tests/tooling/test_taxonomy_drift.py``
(AC-meta.vocab.1).
"""

from __future__ import annotations

import argparse
import re
import subprocess
from collections.abc import Iterable, Sequence
from pathlib import Path

from common.meta.base.gate_cli import run_gate

REPO_ROOT = Path(__file__).resolve().parents[3]

#: rule id -> the retired-vocabulary pattern it hunts.
RULES: dict[str, re.Pattern[str]] = {
    "klass-trio": re.compile(
        r"core/platform/kernel"
        r"|platform/core/kernel"
        r"|kernel/platform/core"
        r"|`?kernel`?\s*<\s*`?platform`?\s*<\s*`?core`?"
        r"|klass=[\"'](?:kernel|platform|core)[\"']"
    ),
    "role-folders": re.compile(
        r"types/ops/store/api"
        r"|`types`\s*/\s*`ops`\s*/\s*`store`\s*/\s*`api`"
        r"|converges? by role"
    ),
    "asset-evaluation": re.compile(r"asset_evaluation"),
    "kernel-class-word": re.compile(r"`kernel`"),
}

#: Lowercase substrings that frame a retired-vocabulary mention as history.
MARKERS = (
    "formerly",
    "retired",
    "legacy",
    "replace",  # replaces / replaced
    "renamed",
    "superseded",
    "pre-migration",
    "historic",  # historical / historically
    "folded",
    "then-",
    "today placement",
    "was the",
)

#: A marker legitimizes a hit on the same line or up to this many lines above
#: (wrapped sentences put the marker one line up).
MARKER_WINDOW = 2

#: Paths never scanned: the gate's own pattern/test sources, generated files,
#: and the doc whose *job* is to name what the model replaces.
EXCLUDED = (
    "common/meta/extension/check_taxonomy_drift.py",
    "tools/check_taxonomy_drift.py",
    "tests/tooling/test_taxonomy_drift.py",
    "docs/ac_registry.yaml",
    "docs/infra_registry.yaml",
)

#: Tracked-path prefixes that are out of scope (generated/reference output).
EXCLUDED_PREFIXES = ("site/", "docs/reference/")


def _in_scope(path: str) -> bool:
    if path in EXCLUDED or path.startswith(EXCLUDED_PREFIXES):
        return False
    if path.endswith(".md"):
        return True
    # docs/ssot/ is the legacy convention (now retired, #1823); finance
    # report's own gate-data yaml (delivery-gates.yaml, MANIFEST.yaml, ...)
    # relocated to common/meta/data/ in #1822/#1823, so that root is in
    # scope too — a narrow, exact mirror of what moved.
    if path.startswith(("docs/ssot/", "common/meta/data/")) and path.endswith(
        (".yaml", ".yml")
    ):
        return True
    if path.endswith(".py") and path.startswith(("tests/", "common/", "tools/")):
        return True
    return False


def _marked(lines: Sequence[str], index: int) -> bool:
    lo = max(0, index - MARKER_WINDOW)
    window = " ".join(lines[lo : index + 1]).lower()
    return any(marker in window for marker in MARKERS)


def scan_lines(path: str, lines: Sequence[str]) -> list[str]:
    """Return ``path:line: [rule] text`` findings for unmarked retired vocab."""
    findings: list[str] = []
    for i, line in enumerate(lines):
        for rule, pattern in RULES.items():
            if pattern.search(line) and not _marked(lines, i):
                findings.append(f"{path}:{i + 1}: [{rule}] {line.strip()[:120]}")
    return findings


def _tracked_files() -> Iterable[str]:
    out = subprocess.run(
        ["git", "ls-files"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return (line for line in out.splitlines() if line.strip())


def scan_repo() -> list[str]:
    findings: list[str] = []
    for path in _tracked_files():
        if not _in_scope(path):
            continue
        target = REPO_ROOT / path
        if not target.is_file():
            continue
        text = target.read_text(encoding="utf-8", errors="replace")
        findings.extend(scan_lines(path, text.splitlines()))
    return findings


def _run_command(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Fail on retired package-taxonomy vocabulary presented as current."
    )
    parser.parse_args(argv)
    findings = scan_repo()
    if findings:
        print(f"taxonomy-drift: {len(findings)} unmarked retired-vocabulary use(s):")
        for finding in findings:
            print(f"  {finding}")
        print(
            "Fix the prose to the current model (five-layer PACKAGE_LAYER, "
            "base/extension/data, pricing) or mark the mention as history "
            "(e.g. 'formerly', 'replaces', 'retired')."
        )
        return 1
    print("taxonomy-drift: OK — no unmarked retired vocabulary.")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    try:
        status = _run_command(argv)
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else 1
    if status == 2:
        return 2
    findings = [] if status == 0 else [f"command returned status {status}"]
    return run_gate(
        "TAXONOMY-DRIFT", lambda _repo_root: findings, [], failure_status=status
    )


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
