#!/usr/bin/env python3
"""Shared AC registry YAML helpers."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Iterable

import yaml


# Legacy EPIC-scoped id: ``AC{epic}.{scenario}.{case}`` (all numeric).
AC_PATTERN = re.compile(r"^AC(?P<epic>\d+)\.(?P<scenario>\d+)\.(?P<case>\d+)$")

# Package-scoped id: ``AC-{package}.{group}.{seq}`` — the package model's scheme,
# where the key self-describes its owning package instead of an EPIC number.
# ``group`` accepts both a numeric group (continuing an EPIC's own numbering,
# e.g. ``39``) and a word-entity slug (e.g. ``guardrail``, ``fx-transfer``) —
# packages use whichever convention fits their own roadmap; ``seq`` stays
# numeric either way.
PKG_AC_PATTERN = re.compile(
    r"^AC-(?P<package>[a-z][a-z0-9_]*)\.(?P<group>[a-z0-9][a-z0-9_-]*)\.(?P<seq>\d+)$"
)


def sort_key(ac_id: str) -> tuple:
    """Total order over BOTH id grammars.

    Legacy numeric ids sort first (leading ``0``) by (epic, scenario, case);
    package ids sort after (leading ``1``) by (package, group, seq). The leading
    discriminant means an ``int`` field is never compared against a ``str`` one.
    ``group`` sorts as a string (a package's group may be a word-entity slug,
    not a number), so two packages that both use numeric groups sort
    lexicographically among themselves (e.g. ``"9"`` before ``"39"`` is NOT
    guaranteed) — acceptable, since ``group`` is a label, not a magnitude.
    """
    pkg = PKG_AC_PATTERN.fullmatch(ac_id)
    if pkg:
        return (1, pkg.group("package"), pkg.group("group"), int(pkg.group("seq")))
    return (0, "", *(int(p) for p in ac_id[2:].split(".")))


def epic_group_key(ac_id: str) -> str:
    """Top-level registry group: ``AC{epic}`` (legacy) or ``AC-{package}``."""
    pkg = PKG_AC_PATTERN.fullmatch(ac_id)
    if pkg:
        return f"AC-{pkg.group('package')}"
    match = AC_PATTERN.fullmatch(ac_id)
    if not match:
        raise ValueError(f"Invalid AC ID: {ac_id}")
    return f"AC{match.group('epic')}"


def scenario_group_key(ac_id: str) -> str:
    """Second-level group: ``AC{epic}.{scenario}`` or ``AC-{package}.{group}``."""
    pkg = PKG_AC_PATTERN.fullmatch(ac_id)
    if pkg:
        return f"AC-{pkg.group('package')}.{pkg.group('group')}"
    match = AC_PATTERN.fullmatch(ac_id)
    if not match:
        raise ValueError(f"Invalid AC ID: {ac_id}")
    return f"AC{match.group('epic')}.{match.group('scenario')}"


def iter_registry_entries(payload: dict[str, Any]) -> Iterable[dict[str, Any]]:
    """Yield registry entries from the grouped ACx -> ACx.y registry payload."""
    groups = payload.get("groups") or {}
    for _epic_key, scenario_groups in groups.items():
        for _scenario_key, entries in (scenario_groups or {}).items():
            yield from (dict(entry) for entry in entries or [])


def load_registry_entries(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if payload.get("generated_from_epics"):
        from common.testing import generate_ac_registry

        registry_kind = str(payload.get("kind") or _infer_registry_kind(path))
        return generate_ac_registry.materialized_entries(
            registry_kind,
            epic_source=payload.get("epic_source"),
            overrides=payload.get("overrides"),
        )
    return list(iter_registry_entries(payload))


def registry_validation_errors(path: Path) -> list[str]:
    if not path.exists():
        return []

    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    errors: list[str] = []

    if payload.get("generated_from_epics"):
        kind = payload.get("kind")
        if kind not in {"feature", "infra"}:
            errors.append("generated registry requires kind: feature|infra")
        return errors

    if "groups" not in payload:
        errors.append("missing required 'groups' map")
        return errors
    if "acs" in payload:
        errors.append("uses unsupported flat 'acs' format")
    if "total" in payload:
        errors.append("uses unsupported committed 'total' field")

    seen: set[str] = set()
    groups = payload.get("groups") or {}
    for epic_key, scenario_groups in groups.items():
        for scenario_key, entries in (scenario_groups or {}).items():
            for entry in entries or []:
                ac_id = str(entry.get("id", ""))
                if ac_id in seen:
                    errors.append(f"duplicates {ac_id}")
                    continue
                seen.add(ac_id)
                try:
                    expected_epic = epic_group_key(ac_id)
                    expected_scenario = scenario_group_key(ac_id)
                except ValueError as exc:
                    errors.append(str(exc))
                    continue
                if epic_key != expected_epic or scenario_key != expected_scenario:
                    errors.append(
                        f"places {ac_id} under {epic_key}/{scenario_key}, "
                        f"expected {expected_epic}/{expected_scenario}"
                    )

    return errors


def _infer_registry_kind(path: Path) -> str:
    if path.name == "infra_registry.yaml":
        return "infra"
    return "feature"
