#!/usr/bin/env python3
"""Environment variable consistency validation between Settings and .env.example."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Any

from src.runtime.base.env_classification import settings_env_keys

from .project_root import get_project_root

_ASSIGNED_RE = re.compile(r"^(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=")
_COMMENTED_RE = re.compile(r"^#\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)=")


def parse_env_example(path: Path) -> set[str]:
    """Extract documented KEY names from .env.example."""
    if not path.exists():
        print(f"WARNING: .env.example not found: {path}")
        return set()
    keys: set[str] = set()
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if line and (match := (_COMMENTED_RE if line.startswith("#") else _ASSIGNED_RE).match(line)):
            keys.add(match.group(1))
    return keys


def settings_env_key_sets() -> dict[str, frozenset[str]]:
    """Map each ``Settings`` field to the env-var names it reads."""
    from src.config import Settings

    return {name: settings_env_keys(Settings, name) for name in Settings.model_fields}


def check_consistency(field_keys: dict[str, frozenset[str]], env_example_keys: set[str]) -> dict[str, Any]:
    """Check that .env.example documents every ``Settings`` field."""
    accepted = set().union(*field_keys.values())
    undocumented = {"/".join(sorted(keys)) for keys in field_keys.values() if not keys & env_example_keys}
    suspicious = {
        k for k in env_example_keys - accepted if not k.startswith(("NEXT_PUBLIC_", "DOKPLOY_"))
    }
    return {
        "config_field_count": len(field_keys),
        "env_example_keys": env_example_keys,
        "undocumented_in_example": undocumented,
        "suspicious_extra_keys": suspicious,
        "is_consistent": not undocumented,
    }


def print_report(result: dict[str, Any], verbose: bool = False) -> None:
    print(f"\n{'=' * 60}\nEnvironment Variable Consistency Check\n{'=' * 60}")
    print(f"\nconfig.py:       {result['config_field_count']:3d} fields")
    print(f".env.example:    {len(result['env_example_keys']):3d} keys")
    if result["undocumented_in_example"]:
        print("\n[ERROR] In config.py but NOT in .env.example (Undocumented):")
        for key in sorted(result["undocumented_in_example"]):
            print(f"   - {key}")
    if verbose and result["suspicious_extra_keys"]:
        print("\n[INFO] In .env.example but NOT in config.py (Frontend/Infra?):")
        for key in sorted(result["suspicious_extra_keys"]):
            print(f"   - {key}")
    print("\n✅ Consistency check passed!" if result["is_consistent"] else "\n❌ Inconsistency found, please fix and retry")
    print(f"\n{'=' * 60}")


def generate_fix_suggestions(result: dict[str, Any]) -> None:
    if result["undocumented_in_example"]:
        print("\n[FIX] Regenerate the backend block of .env.example:\n    python tools/generate_env_reference.py\n" + "-" * 40)
        for key in sorted(result["undocumented_in_example"]):
            print(f"{key}=")
        print("-" * 40)


def main() -> None:
    parser = argparse.ArgumentParser(description="Environment variable consistency check")
    parser.add_argument("--diff", action="store_true", help="Show detailed diff")
    parser.add_argument("--fix", action="store_true", help="Generate fix suggestions")
    args = parser.parse_args()
    root = get_project_root()
    env_example_path = root / ".env.example"
    print(f"Project root: {root}\n.env.example:  {env_example_path.relative_to(root)}")
    result = check_consistency(settings_env_key_sets(), parse_env_example(env_example_path))
    print_report(result, verbose=args.diff)
    if args.fix:
        generate_fix_suggestions(result)
    sys.exit(0 if result["is_consistent"] else 1)


if __name__ == "__main__":
    main()
