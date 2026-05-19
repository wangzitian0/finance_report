#!/usr/bin/env python3
import argparse
import re
import os
import sys
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover - import guard
    yaml = None


EPIC_DIR = "docs/project"
OUTPUT_FEATURE = "docs/ac_registry.yaml"
OUTPUT_INFRA = "docs/infra_registry.yaml"
# Backward-compat alias used by tests
OUTPUT = OUTPUT_FEATURE

# EPIC classification: which EPICs are feature vs infra
FEATURE_EPICS = {1, 2, 3, 4, 5, 6, 8, 11, 13, 15, 16, 17, 18}
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
        return match.group(1), int(match.group(2)), desc[:120]

    match = re.match(
        r"^(?:[-*]\s*)?(?:\*\*)?(AC(\d+)\.(\d+)\.(\d+))(?:\*\*)?\s*[:|-]\s*(.+)$",
        stripped,
    )
    if not match:
        return None

    ac_id = match.group(1)
    ac_epic = int(match.group(2))
    desc = _clean_description(match.group(5))
    return ac_id, ac_epic, desc[:120]


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
    with registry_path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    entries: dict[str, dict] = {}
    for entry in data.get("acs", []) or []:
        ac_id = str(entry["id"])
        entries[ac_id] = {
            "epic": int(entry.get("epic", ac_id.split(".")[0][2:])),
            "epic_name": str(
                entry.get(
                    "epic_name",
                    EPIC_NAMES.get(int(entry.get("epic", 0)), ""),
                )
            ),
            "description": str(entry.get("description", entry.get("title", ""))),
            "mandatory": bool(entry.get("mandatory", True)),
        }
    return entries


def registry_total_mismatch(path: str | Path) -> tuple[int, int] | None:
    """Return (declared, actual) when a registry total field is stale."""
    _require_yaml()
    registry_path = Path(path)
    if not registry_path.exists():
        return None
    with registry_path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    declared = int(data.get("total", 0))
    actual = len(data.get("acs", []) or [])
    if declared != actual:
        return declared, actual
    return None


def load_existing_registries(paths: list[str | Path]) -> dict[str, dict]:
    entries: dict[str, dict] = {}
    for path in paths:
        entries.update(load_existing_registry(path))
    return entries


def extract_acs(existing_acs: dict[str, dict] | None = None) -> dict[str, dict]:
    epic_files = sorted(
        [
            f
            for f in os.listdir(EPIC_DIR)
            if re.match(r"EPIC-\d+.*\.md", f)
            and "IMPLEMENTATION" not in f
            and "ENCODING" not in f
        ]
    )

    existing_acs = existing_acs or {}
    all_acs: dict[str, dict] = {}
    for fname in epic_files:
        path = os.path.join(EPIC_DIR, fname)
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


def sort_key(ac_id: str) -> list[int]:
    return [int(p) for p in ac_id[2:].split(".")]


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
    sorted_ids = sorted(all_acs.keys(), key=sort_key)
    lines = [
        "version: '1.0'",
        f"total: {len(sorted_ids)}",
        "acs:",
    ]
    current_epic = None
    for ac_id in sorted_ids:
        entry = all_acs[ac_id]
        epic = entry["epic"]
        if epic != current_epic:
            current_epic = epic
            lines.append(f"  # EPIC-{epic:03d}: {entry['epic_name']}")
        desc = entry["description"].replace("'", "''")
        lines.extend(
            [
                f"  - id: {ac_id}",
                f"    epic: {epic}",
                f"    epic_name: {entry['epic_name']}",
                f"    description: '{desc}'",
                f"    mandatory: {str(bool(entry.get('mandatory', True))).lower()}",
            ]
        )

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(
            "# DO NOT edit this file manually - run scripts/generate_ac_registry.py\n"
        )
        f.write("# Regenerate: python scripts/generate_ac_registry.py\n")
        f.write("\n".join(lines) + "\n")
    print(f"Written {len(sorted_ids)} ACs to {output_path}")


def _render_incremental_entry(ac_id: str, entry: dict) -> list[str]:
    desc = entry.get("description", "").replace("'", "''")
    return [
        f"  - id: {ac_id}",
        f"    epic: {entry['epic']}",
        f"    epic_name: {entry['epic_name']}",
        f"    description: '{desc}'",
        f"    mandatory: {str(bool(entry.get('mandatory', True))).lower()}",
    ]


def _registry_total(path: Path) -> int:
    _require_yaml()
    with path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return len(data.get("acs", []) or [])


def sync_registry_total(output_path: str | Path) -> bool:
    path = Path(output_path)
    mismatch = registry_total_mismatch(path)
    if mismatch is None:
        return False
    _, actual = mismatch
    content = path.read_text(encoding="utf-8")
    content = re.sub(
        r"^total:\s*\d+\s*$",
        f"total: {actual}",
        content,
        count=1,
        flags=re.MULTILINE,
    )
    path.write_text(content, encoding="utf-8")
    print(f"Updated total to {actual} in {path}")
    return True


def append_registry_entries(entries: dict[str, dict], output_path: str | Path) -> None:
    if not entries:
        return

    path = Path(output_path)
    if not path.exists():
        write_registry(entries, str(path))
        return

    content = path.read_text(encoding="utf-8")
    new_total = _registry_total(path) + len(entries)
    content = re.sub(
        r"^total:\s*\d+\s*$",
        f"total: {new_total}",
        content,
        count=1,
        flags=re.MULTILINE,
    )
    content = re.sub(r"^acs:\s*\[\]\s*$", "acs:", content, count=1, flags=re.MULTILINE)
    if not content.endswith("\n"):
        content += "\n"
    content += (
        "  # Incremental ACs: generated without rewriting historical registry entries\n"
    )
    for ac_id in sorted(entries.keys(), key=sort_key):
        content += "\n".join(_render_incremental_entry(ac_id, entries[ac_id])) + "\n"
    path.write_text(content, encoding="utf-8")
    print(f"Appended {len(entries)} ACs to {path}")


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
    all_acs = extract_acs(existing_acs=existing_acs)
    missing_acs = {
        ac_id: entry for ac_id, entry in all_acs.items() if ac_id not in existing_acs
    }
    total_mismatches = {
        str(path): mismatch
        for path in (OUTPUT_FEATURE, OUTPUT_INFRA)
        if (mismatch := registry_total_mismatch(path)) is not None
    }

    # Classify ACs into feature vs infra
    feature_acs: dict[str, dict] = {}
    infra_acs: dict[str, dict] = {}
    for ac_id, entry in missing_acs.items():
        if classify_ac(ac_id, entry) == "infra":
            infra_acs[ac_id] = entry
        else:
            feature_acs[ac_id] = entry

    if args.check:
        if total_mismatches:
            details = ", ".join(
                f"{path} declared {declared} but has {actual} entries"
                for path, (declared, actual) in total_mismatches.items()
            )
            print(
                "ERROR: registry total fields are stale: "
                f"{details}\n  Run: python scripts/generate_ac_registry.py",
                file=sys.stderr,
            )
            return 1
        if missing_acs:
            missing = ", ".join(sorted(missing_acs, key=sort_key))
            print(
                "ERROR: EPIC-defined ACs are missing from registry files: "
                f"{missing}\n  Run: python scripts/generate_ac_registry.py",
                file=sys.stderr,
            )
            return 1
        print("OK: AC registries include every EPIC-defined AC.")
        return 0

    append_registry_entries(feature_acs, OUTPUT_FEATURE)
    append_registry_entries(infra_acs, OUTPUT_INFRA)
    ensure_registry_file(OUTPUT_FEATURE)
    ensure_registry_file(OUTPUT_INFRA)
    sync_registry_total(OUTPUT_FEATURE)
    sync_registry_total(OUTPUT_INFRA)
    if not missing_acs:
        print("OK: AC registries already include every EPIC-defined AC.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
