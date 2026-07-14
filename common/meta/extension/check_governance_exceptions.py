#!/usr/bin/env python3
"""Validate the bottom-up proof-exception registry (issue #524).

``common/meta/data/governance-exceptions.yaml`` classifies the surfaces the bottom-up
proof chain deliberately does not gate as normal AC proof:

  * ``proof_exceptions``    — budgeted or e2e-only proofs bounded by a guard or
                              override, tracked for burn-down.
  * ``code_owned_surfaces`` — thresholds / generated artifacts whose
                              authoritative value lives in code or config.

Each classified entry must declare ``id``, ``owner``, ``reason``, and a tracking
``issue`` URL. The legacy ``exceptions`` list (SSOT governance gate exceptions)
is left untouched so ``common/meta/extension/governance_report`` keeps reading it.

Exit code 0 on success, 1 on any violation.

Run locally::

    python tools/check_governance_exceptions.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_REGISTRY = REPO_ROOT / "common" / "meta" / "data" / "governance-exceptions.yaml"

CLASSIFIED_SECTIONS = ("proof_exceptions", "code_owned_surfaces")
REQUIRED_FIELDS = ("id", "owner", "reason", "issue")


def validate_registry(path: Path) -> list[str]:
    """Return a list of human-readable violations for *path* (empty == valid)."""
    violations: list[str] = []
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return [f"{path}: registry file does not exist"]
    except yaml.YAMLError as exc:  # pragma: no cover - defensive
        return [f"{path}: invalid YAML: {exc}"]

    if not isinstance(data, dict):
        return [f"{path}: registry root must be a mapping"]

    seen_ids: set[str] = set()
    for section in CLASSIFIED_SECTIONS:
        entries = data.get(section)
        if entries is None:
            violations.append(f"{section}: missing classification section")
            continue
        if not isinstance(entries, list):
            violations.append(f"{section}: must be a list")
            continue
        for index, entry in enumerate(entries):
            label = f"{section}[{index}]"
            if not isinstance(entry, dict):
                violations.append(f"{label}: entry must be a mapping")
                continue
            for field in REQUIRED_FIELDS:
                value = entry.get(field)
                if not isinstance(value, str) or not value.strip():
                    violations.append(f"{label}: missing or empty '{field}'")
            issue = entry.get("issue")
            if isinstance(issue, str) and "/issues/" not in issue:
                violations.append(
                    f"{label}: 'issue' must link a GitHub issue (got {issue!r})"
                )
            entry_id = entry.get("id")
            if isinstance(entry_id, str):
                if entry_id in seen_ids:
                    violations.append(f"{label}: duplicate id '{entry_id}'")
                seen_ids.add(entry_id)
            owner = entry.get("owner")
            if isinstance(owner, str) and owner.strip():
                owner_path = REPO_ROOT / owner
                # Generated/git-ignored artifacts may be absent in a clean
                # checkout; only flag clearly-broken non-generated owners.
                if not owner_path.exists() and not _is_known_generated(owner):
                    violations.append(f"{label}: owner path does not exist: '{owner}'")
    return violations


def _is_known_generated(owner: str) -> bool:
    """Owners that produce generated, possibly-absent artifacts are valid."""
    return owner.startswith("tools/generate_")


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    registry = Path(args[0]) if args else DEFAULT_REGISTRY

    violations = validate_registry(registry)
    if not violations:
        print(f"OK: governance exceptions registry valid ({registry}).")
        return 0

    print(
        f"FAIL: governance exceptions registry has {len(violations)} violation(s):",
        file=sys.stderr,
    )
    for violation in violations:
        print(f"  - {violation}", file=sys.stderr)
    return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
