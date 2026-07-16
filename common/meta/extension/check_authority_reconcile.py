#!/usr/bin/env python3
"""Gate: reconcile a package's DECLARED authority tier against its DETECTED band.

The authority tier has two views over one CODE↔LLM spectrum
(``common/meta/base/authority_matrix.py``):

- **declared** — ``PackageContract.tier`` (the package's authorial intent);
- **detected** — the band the ``authority_classifier`` measures from the shapes
  of the tests that prove the package's roadmap ACs (cassette/replay → LLM,
  deterministic → CODE).

Until now nothing tied the two together, so intent and reality could diverge
silently — the exact gap that made "the declared tier can't be validated". This
gate closes it by enforcing the two *enforceable ends* of the band scale (the
ones ``authority_classifier`` itself marks enforceable); the middle bands
(CODE-LED / LLM-LED) are measured, not hard-gated:

- declared **CODE-ONLY** ⟹ NO roadmap-AC test may be an LLM test (share == 0);
- declared **LLM-ONLY** ⟹ NO roadmap-AC test may be deterministic CODE (share == 100).

Pure AST/text (no pydantic), so it runs in the CI lint env. ``draft`` packages
(tier undecided) are skipped.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from common.meta.base.gate_cli import run_gate
from common.meta.extension.authority_classifier import (
    band,
    build_test_index,
    classify_test_files,
)
from common.meta.extension.generate_ac_registry import package_contract_meta

REPO_ROOT = Path(__file__).resolve().parents[3]


def _detect(meta: dict, index: dict, cache: dict) -> tuple[int, int, float, str]:
    """Return (code, llm, llm_share, detected_band) for a package's roadmap ACs."""
    code = llm = 0
    for ac in meta.get("roadmap", []):
        test = ac.get("test")
        if not test:
            continue
        verdict = classify_test_files([test.split("::")[0]], index, cache)
        if verdict == "CODE":
            code += 1
        elif verdict == "LLM":
            llm += 1
    known = code + llm
    share = round(100 * llm / known, 1) if known else 0.0
    return code, llm, share, band(share)


def reconcile(repo_root: Path) -> tuple[list[str], list[str]]:
    """Return (violations, report_lines) comparing declared tier vs detected band."""
    index = build_test_index(repo_root)
    cache: dict = {}
    violations: list[str] = []
    report: list[str] = []
    for path in sorted(repo_root.glob("common/*/contract.py")):
        meta = package_contract_meta(path)
        if not meta or not meta.get("tier"):  # draft / undecided → nothing to reconcile
            continue
        declared = meta["tier"]
        code, llm, share, detected = _detect(meta, index, cache)
        report.append(
            f"  {meta.get('name') or path.parent.name:14} declared={declared:10} "
            f"detected={detected:10} (code={code} llm={llm} share={share}%)"
        )
        if declared == "CODE-ONLY" and llm > 0:
            violations.append(
                f"package {meta.get('name')!r}: declared CODE-ONLY but {llm}/"
                f"{code + llm} roadmap-AC test(s) are LLM tests (detected "
                f"{detected}). A CODE-ONLY package permits no LLM — re-declare the "
                "tier or drop the LLM test dependency."
            )
        elif declared == "LLM-ONLY" and code > 0:
            violations.append(
                f"package {meta.get('name')!r}: declared LLM-ONLY but {code}/"
                f"{code + llm} roadmap-AC test(s) are deterministic CODE (detected "
                f"{detected}). An LLM-ONLY package permits no hardcoded oracle."
            )
    return violations, report


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Reconcile declared authority tier vs detected CODE/LLM band."
    )
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    return parser.parse_args(argv)


def _run_command(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    violations, report = reconcile(args.repo_root.resolve())
    for line in report:
        print(line)
    if violations:
        for message in violations:
            print(f"::error title=Authority reconcile::{message}", file=sys.stderr)
        print(
            f"[RECONCILE] FAILED: {len(violations)} package(s) whose declared tier "
            "contradicts the detected CODE/LLM band at an enforceable end.",
            file=sys.stderr,
        )
        return 1
    print(
        "[RECONCILE] PASSED: every shipped package's declared tier agrees with its detected band."
    )
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
        "AUTHORITY-RECONCILE", lambda _repo_root: findings, [], failure_status=status
    )


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
