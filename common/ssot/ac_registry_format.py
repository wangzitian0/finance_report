#!/usr/bin/env python3
"""Shared AC registry YAML helpers."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Iterable

import yaml


AC_PATTERN = re.compile(r"^AC(?P<epic>\d+)\.(?P<scenario>\d+)\.(?P<case>\d+)$")


def sort_key(ac_id: str) -> list[int]:
    return [int(p) for p in ac_id[2:].split(".")]


def epic_group_key(ac_id: str) -> str:
    match = AC_PATTERN.fullmatch(ac_id)
    if not match:
        raise ValueError(f"Invalid AC ID: {ac_id}")
    return f"AC{match.group('epic')}"


def scenario_group_key(ac_id: str) -> str:
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
    return list(iter_registry_entries(payload))


def registry_validation_errors(path: Path) -> list[str]:
    if not path.exists():
        return []

    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    errors: list[str] = []

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
