"""Generate the machine-readable SLA manifest implementation (finance_report#1654)."""

from __future__ import annotations

import argparse
import difflib
import json
import sys
from collections.abc import Sequence
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[2]
BACKEND_DIR = ROOT_DIR / "apps" / "backend"

if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

SLA_MANIFEST_PATH = ROOT_DIR / "common" / "runtime" / "sla-manifest.generated.json"


def _runtime_manifest():
    if str(BACKEND_DIR) not in sys.path:
        sys.path.insert(0, str(BACKEND_DIR))
    from src.runtime import DEPENDENCY_MANIFEST, EnvTier

    return DEPENDENCY_MANIFEST, EnvTier


def collect_sla_entries() -> list[dict]:
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


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Exit 1 (with a diff) if the on-disk file differs from generated output.",
    )
    args = parser.parse_args(argv)

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
