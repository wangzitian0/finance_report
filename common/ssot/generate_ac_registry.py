#!/usr/bin/env python3
import argparse
import re
import os
import sys
from pathlib import Path

from common.ssot.ac_registry_format import (
    epic_group_key,
    load_registry_entries,
    registry_validation_errors,
    scenario_group_key,
    sort_key,
)

try:
    import yaml
except ImportError:  # pragma: no cover - import guard
    yaml = None


EPIC_DIR = "docs/project"
OUTPUT_FEATURE = "docs/ac_registry.yaml"
OUTPUT_INFRA = "docs/infra_registry.yaml"
OVERRIDES = "docs/ac_registry_overrides.yaml"
# Backward-compat alias used by tests
OUTPUT = OUTPUT_FEATURE

# EPIC classification: which EPICs are feature vs infra
FEATURE_EPICS = {1, 2, 3, 4, 5, 6, 8, 11, 13, 15, 16, 17, 18, 19, 20, 21, 22}
INFRA_EPICS = {7, 9, 10, 12, 14}

# EPIC-016 sub-classification: these AC16.XX.x groups route to infra
EPIC16_INFRA_GROUPS = {11, 13}

EPIC_NAMES: dict[int, str] = {
    1: "phase0-setup",
    2: "double-entry-core",
    3: "statement-parsing",
    4: "reconciliation-engine",
    5: "reporting-visualization",
    6: "ai-advisor",
    7: "deployment",
    8: "testing-strategy",
    9: "pdf-fixture-generation",
    10: "signoz-logging",
    11: "asset-lifecycle",
    12: "foundation-libs",
    13: "statement-parsing-v2",
    14: "ttd-transformation",
    15: "processing-account",
    16: "two-stage-review-ui",
    17: "portfolio-management",
    18: "ai-driven-pipeline",
    19: "event-driven-upload-to-report-ux",
    20: "framework-aware-personal-reporting",
    21: "application-ai-advisor",
    22: "everyday-user-ia",
}


AC_PATTERN = re.compile(r"\b(AC(\d+)\.(\d+)\.(\d+))\b")


def _clean_description(text: str) -> str:
    return text.replace("**", "").replace("`", "").strip()


def _is_reference_only_line(line: str) -> bool:
    stripped = line.strip()
    lower = stripped.lower()
    if stripped.startswith("*(") and "removed" in lower:
        return True
    if "removed as duplicate" in lower or "removed as intra-epic" in lower:
        return True
    if stripped.startswith("- Total AC IDs:"):
        return True
    return False


def _extract_ac_definition(line: str) -> tuple[str, int, str] | None:
    """Extract one AC definition from a Markdown table, bullet, or plain line."""
    if _is_reference_only_line(line):
        return None

    stripped = line.strip()
    if not stripped:
        return None

    if stripped.startswith("|"):
        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        if not cells:
            return None
        match = AC_PATTERN.fullmatch(cells[0])
        if not match:
            return None
        desc = _clean_description(cells[1] if len(cells) > 1 else "")
        return match.group(1), int(match.group(2)), desc

    match = re.match(
        r"^(?:[-*]\s*)?(?:\[[ xX]\]\s*)?(?:\*\*)?"
        r"(AC(\d+)\.(\d+)\.(\d+))(?:\*\*)?(?:\s*[:|-])?\s+(.+)$",
        stripped,
    )
    if not match:
        return None

    ac_id = match.group(1)
    ac_epic = int(match.group(2))
    desc = _clean_description(match.group(5))
    return ac_id, ac_epic, desc


def _require_yaml() -> None:
    if yaml is None:
        print("ERROR: PyYAML not installed. Run: pip install pyyaml", file=sys.stderr)
        sys.exit(1)


def load_existing_registry(path: str | Path) -> dict[str, dict]:
    """Load an existing registry by ID, preserving canonical entry metadata."""
    _require_yaml()
    registry_path = Path(path)
    if not registry_path.exists():
        return {}

    entries: dict[str, dict] = {}
    for entry in load_registry_entries(registry_path):
        ac_id = str(entry["id"])
        normalized = dict(entry)
        epic = int(normalized.get("epic", ac_id.split(".")[0][2:]))
        normalized["epic"] = epic
        if "epic_name" in normalized:
            normalized["epic_name"] = str(normalized["epic_name"])
        normalized["mandatory"] = bool(normalized.get("mandatory", True))
        entries[ac_id] = normalized
    return entries


def load_existing_registries(paths: list[str | Path]) -> dict[str, dict]:
    entries: dict[str, dict] = {}
    for path in paths:
        entries.update(load_existing_registry(path))
    return entries


def load_overrides(path: str | Path = OVERRIDES) -> dict[str, dict]:
    """Load registry entries that cannot be derived from current EPIC text."""
    return load_existing_registry(path)


def extract_acs(
    existing_acs: dict[str, dict] | None = None,
    epic_dir: str | Path | None = None,
) -> dict[str, dict]:
    source_dir = Path(epic_dir or EPIC_DIR)
    epic_files = sorted(
        [
            f
            for f in os.listdir(source_dir)
            if re.match(r"EPIC-\d+.*\.md", f)
            and "IMPLEMENTATION" not in f
            and "ENCODING" not in f
        ]
    )

    existing_acs = existing_acs or {}
    all_acs: dict[str, dict] = {}
    for fname in epic_files:
        path = source_dir / fname
        with open(path, encoding="utf-8") as f:
            lines = f.readlines()

        for line in lines:
            definition = _extract_ac_definition(line)
            if definition is None:
                continue
            ac_id, ac_epic, desc = definition
            if ac_id in all_acs:
                continue

            existing = existing_acs.get(ac_id, {})
            all_acs[ac_id] = {
                "epic": int(existing.get("epic", ac_epic)),
                "epic_name": existing.get(
                    "epic_name", EPIC_NAMES.get(ac_epic, f"epic-{ac_epic:03d}")
                ),
                "description": existing.get("description", desc),
                "mandatory": existing.get("mandatory", True),
            }

    return all_acs


def classify_ac(ac_id: str, entry: dict) -> str:
    """Return 'feature' or 'infra' for a given AC entry."""
    epic = entry["epic"]
    if epic in INFRA_EPICS:
        return "infra"
    if epic == 16:
        # Sub-classify EPIC-016: check the group number (middle digit)
        parts = ac_id[2:].split(".")
        group = int(parts[1])
        if group in EPIC16_INFRA_GROUPS:
            return "infra"
    return "feature"


def write_registry(all_acs: dict[str, dict], output_path: str | None = None) -> None:
    if output_path is None:
        output_path = OUTPUT
    _require_yaml()
    groups: dict[str, dict[str, list[dict]]] = {}
    for ac_id in sorted(all_acs.keys(), key=sort_key):
        source = dict(all_acs[ac_id])
        source["id"] = ac_id
        source["mandatory"] = bool(source.get("mandatory", True))
        entry = {
            key: source[key]
            for key in (
                "id",
                "epic",
                "epic_name",
                "description",
                "title",
                "status",
                "mandatory",
            )
            if key in source
        }
        for key, value in source.items():
            if key not in entry:
                entry[key] = value
        groups.setdefault(epic_group_key(ac_id), {}).setdefault(
            scenario_group_key(ac_id), []
        ).append(entry)

    payload = {
        "version": "1.0",
        "groups": groups,
    }

    class IndentedDumper(yaml.SafeDumper):
        def increase_indent(self, flow=False, indentless=False):
            return super().increase_indent(flow, False)

    rendered = yaml.dump(
        payload,
        Dumper=IndentedDumper,
        sort_keys=False,
        allow_unicode=False,
        width=120,
    )

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(
            "# DO NOT edit this file manually - run tools/generate_ac_registry.py\n"
        )
        f.write("# Regenerate: python tools/generate_ac_registry.py\n")
        f.write(rendered)
    print(f"Written {len(all_acs)} ACs to {output_path}")


def write_registry_index(kind: str, output_path: str | Path) -> None:
    """Write the small checked-in registry index used by runtime loaders."""
    if kind not in {"feature", "infra"}:
        raise ValueError(f"Invalid registry kind: {kind}")
    _require_yaml()
    payload = {
        "version": "2.0",
        "kind": kind,
        "generated_from_epics": True,
        "epic_source": EPIC_DIR,
        "overrides": OVERRIDES,
    }
    rendered = yaml.safe_dump(payload, sort_keys=False, allow_unicode=False)
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "# DO NOT edit this file manually - run tools/generate_ac_registry.py\n"
        "# Checked-in index only; entries are generated from EPIC docs plus overrides.\n"
        f"{rendered}",
        encoding="utf-8",
    )
    print(f"Written generated registry index to {output_path}")


def build_registry_entries(
    existing_acs: dict[str, dict] | None = None,
    epic_source: str | Path | None = None,
    overrides: str | Path | None = None,
) -> dict[str, dict]:
    """Return the complete current registry without requiring committed entries."""
    override_entries = load_overrides(overrides or OVERRIDES)
    if existing_acs:
        override_entries.update(existing_acs)
    extracted = extract_acs(epic_dir=epic_source)
    merged = dict(extracted)
    for ac_id, entry in override_entries.items():
        if ac_id not in merged:
            merged[ac_id] = dict(entry)
            continue
        current = dict(merged[ac_id])
        if str(current.get("description", "")).strip().lower() != "stub":
            continue
        for key, value in entry.items():
            if key == "description":
                continue
            current[key] = value
        merged[ac_id] = current
    return dict(sorted(merged.items(), key=lambda item: sort_key(item[0])))


def materialized_entries(
    kind: str,
    epic_source: str | Path | None = None,
    overrides: str | Path | None = None,
) -> list[dict]:
    """Return generated feature or infra registry entries as flat dictionaries."""
    entries: list[dict] = []
    for ac_id, source in build_registry_entries(
        epic_source=epic_source,
        overrides=overrides,
    ).items():
        if classify_ac(ac_id, source) != kind:
            continue
        entry = dict(source)
        entry["id"] = ac_id
        entry["mandatory"] = bool(entry.get("mandatory", True))
        entries.append(entry)
    return entries


def append_registry_entries(entries: dict[str, dict], output_path: str | Path) -> None:
    if not entries:
        return

    path = Path(output_path)
    merged = load_existing_registry(path)
    merged.update(entries)
    write_registry(merged, str(path))


def ensure_registry_file(output_path: str | Path) -> None:
    path = Path(output_path)
    if not path.exists():
        write_registry({}, str(path))


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Register AC definitions from EPIC docs without rewriting registry history."
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Exit 1 if EPIC-defined ACs are missing from the registries.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args([] if argv is None else argv)
    existing_acs = load_existing_registries([OUTPUT_FEATURE, OUTPUT_INFRA])
    all_acs = build_registry_entries()
    extracted_acs = extract_acs(existing_acs=load_overrides())
    missing_acs = {
        ac_id: entry
        for ac_id, entry in extracted_acs.items()
        if ac_id not in existing_acs
    }
    registry_errors = {
        str(path): errors
        for path in (Path(OUTPUT_FEATURE), Path(OUTPUT_INFRA))
        if (errors := registry_validation_errors(path))
    }

    # Force classification while building so malformed AC IDs fail before writing.
    for ac_id, entry in all_acs.items():
        classify_ac(ac_id, entry)

    if args.check:
        if registry_errors:
            details = ", ".join(
                f"{path}: {'; '.join(errors)}"
                for path, errors in registry_errors.items()
            )
            print(
                "ERROR: AC registry files do not match grouped ACx.y format: "
                f"{details}\n  Run: python tools/generate_ac_registry.py",
                file=sys.stderr,
            )
            return 1
        if missing_acs:
            missing = ", ".join(sorted(missing_acs, key=sort_key))
            print(
                "ERROR: EPIC-defined ACs are missing from registry files: "
                f"{missing}\n  Run: python tools/generate_ac_registry.py",
                file=sys.stderr,
            )
            return 1
        print("OK: AC registries include every EPIC-defined AC.")
        return 0

    write_registry_index("feature", OUTPUT_FEATURE)
    write_registry_index("infra", OUTPUT_INFRA)
    if not missing_acs and not registry_errors:
        print("OK: AC registries already include every EPIC-defined AC.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
