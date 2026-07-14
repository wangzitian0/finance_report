#!/usr/bin/env python3
"""Generate the machine-readable SLA manifest (finance_report#1654).

2026-07-07 decision: a dependency listed in ``DEPENDENCY_MANIFEST.required_for(tier)``
for ``tier=production`` is a platform SLA commitment, independent of whether the
app *feature* consuming it has shipped (resolves the contradiction between
``runtime/base/manifest.py`` and EPIC-019's deferred AC19.13 — platform
availability != feature adoption).

This generator is the "no second hand-maintained list" half of that decision:
infra2's periodic Lark report (``tools/stability_report.py`` /
``ops-checks.yml``) needs to know which dependencies are SLA-bearing without
hand-copying a service list that can drift from the real manifest. The
committed artifact (``common/runtime/sla-manifest.generated.json``) is derived
from the same ``DEPENDENCY_MANIFEST`` that ``/health?full=1`` already asserts
(finance_report#1653 consumes that endpoint out-of-band; this manifest gives
the report the *why*/*what* half — SLA declaration — that a point-in-time probe
result alone can't carry).

Mirrors ``tools/generate_env_reference.py``'s generated-artifact + drift-gate
pattern (#1828 G-injection-drift-gate) for the same reason: a change to the
dependency manifest must not silently drift from what infra2 renders.

Usage:
    python tools/generate_sla_manifest.py            # write the file
    python tools/generate_sla_manifest.py --check    # exit 1 if it drifts
"""

from __future__ import annotations

import argparse
import difflib
import json
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
BACKEND_DIR = ROOT_DIR / "apps" / "backend"

# Repo root on sys.path[0] when run directly (tool-wrapper contract AC8.13.56).
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

SLA_MANIFEST_PATH = ROOT_DIR / "common" / "runtime" / "sla-manifest.generated.json"


def _runtime_manifest():
    """Load ``DEPENDENCY_MANIFEST``/``EnvTier`` from the backend package.

    ``apps/backend`` is inserted onto ``sys.path`` lazily (only when actually
    generating), mirroring ``generate_env_reference.py``'s care not to perturb
    ``sys.path`` merely by importing this module. Unlike ``config.py``,
    ``manifest.py`` makes real intra-package imports (``src.runtime.base.kind``
    etc.), so it is loaded as a proper package import rather than by file path.
    """
    if str(BACKEND_DIR) not in sys.path:
        sys.path.insert(0, str(BACKEND_DIR))
    from src.runtime import DEPENDENCY_MANIFEST, EnvTier

    return DEPENDENCY_MANIFEST, EnvTier


def collect_sla_entries() -> list[dict]:
    """One entry per ``(tier, dependency)`` pair where the dependency is
    ``required_in`` that tier — the full SLA declaration, every tier (not just
    production), so the artifact stays useful for staging SLA reporting too."""
    manifest, env_tier = _runtime_manifest()
    entries: list[dict] = []
    for tier in env_tier:
        for name in sorted(manifest.required_for(tier)):
            dependency = manifest.get(name)
            entries.append(
                {
                    "tier": tier.value,
                    "dependency": name,
                    "kind": dependency.kind.value,
                    "summary": dependency.summary,
                }
            )
    return entries


def render_sla_manifest(entries: list[dict]) -> str:
    """Render the machine-readable SLA manifest as pretty-printed JSON."""
    manifest = {
        "generated_by": "tools/generate_sla_manifest.py — do not edit",
        "source": "apps/backend/src/runtime/base/manifest.py::DEPENDENCY_MANIFEST",
        "semantics": (
            "required_in(tier) means the dependency's continuous presence in "
            "that tier is an SLA commitment, independent of whether the app "
            "feature consuming it has shipped (wangzitian0/finance_report#1654, "
            "decided 2026-07-07)."
        ),
        "consumer": (
            "infra2's periodic Lark report renders one SLA row per entry "
            "(wangzitian0/finance_report#1654) instead of hand-maintaining a "
            "second service list."
        ),
        "entries": entries,
    }
    return json.dumps(manifest, indent=2, ensure_ascii=False) + "\n"


def _diff(label: str, current: str, generated: str) -> str:
    return "".join(
        difflib.unified_diff(
            current.splitlines(keepends=True),
            generated.splitlines(keepends=True),
            fromfile=f"{label} (on disk)",
            tofile=f"{label} (generated)",
        )
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Exit 1 (with a diff) if the on-disk file differs from generated output.",
    )
    args = parser.parse_args()

    entries = collect_sla_entries()
    new_manifest = render_sla_manifest(entries)

    if args.check:
        current = (
            SLA_MANIFEST_PATH.read_text(encoding="utf-8")
            if SLA_MANIFEST_PATH.exists()
            else ""
        )
        if current != new_manifest:
            print(_diff(SLA_MANIFEST_PATH.name, current, new_manifest))
            print(
                "ERROR: sla-manifest.generated.json is out of date. "
                "Run: python tools/generate_sla_manifest.py",
                file=sys.stderr,
            )
            return 1
        print("OK: sla-manifest.generated.json is up to date.")
        return 0

    SLA_MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    SLA_MANIFEST_PATH.write_text(new_manifest, encoding="utf-8")
    print(f"Wrote {SLA_MANIFEST_PATH.relative_to(ROOT_DIR)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
