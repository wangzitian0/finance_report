#!/usr/bin/env python3
import re
import os
import sys


EPIC_DIR = "docs/project"
OUTPUT = "docs/ac_registry.yaml"

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
}


def extract_acs() -> dict[str, dict]:
    epic_files = sorted(
        [
            f
            for f in os.listdir(EPIC_DIR)
            if re.match(r"EPIC-\d+.*\.md", f)
            and "IMPLEMENTATION" not in f
            and "ENCODING" not in f
        ]
    )

    all_acs: dict[str, dict] = {}
    for fname in epic_files:
        path = os.path.join(EPIC_DIR, fname)
        with open(path) as f:
            lines = f.readlines()

        for line in lines:
            for m in re.finditer(r"\b(AC(\d+)\.(\d+)\.(\d+))\b", line):
                ac_id = m.group(1)
                ac_epic = int(m.group(2))
                if ac_id in all_acs:
                    continue

                rest = line[m.end() :].lstrip()
                if rest.startswith("|"):
                    rest = rest[1:].lstrip()
                if rest.startswith(":"):
                    rest = rest[1:].lstrip()
                desc = rest.split("|")[0].strip()
                desc = desc.replace("**", "").replace("`", "").strip()

                if not desc:
                    before = line[: m.start()]
                    cells = [c.strip() for c in before.split("|") if c.strip()]
                    if cells:
                        candidate = cells[-1].replace("**", "").replace("`", "").strip()
                        if candidate and not re.match(r"AC\d+", candidate):
                            desc = candidate

                all_acs[ac_id] = {
                    "epic": ac_epic,
                    "epic_name": EPIC_NAMES.get(ac_epic, f"epic-{ac_epic:03d}"),
                    "description": desc[:120],
                }

    return all_acs


def sort_key(ac_id: str) -> list[int]:
    return [int(p) for p in ac_id[2:].split(".")]


def write_registry(all_acs: dict[str, dict]) -> None:
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
                f"    mandatory: true",
            ]
        )

    with open(OUTPUT, "w") as f:
        f.write(
            "# Central AC Registry — auto-generated. Edit source EPICs, not this file.\n"
        )
        f.write("# Regenerate: python scripts/generate_ac_registry.py\n")
        f.write("\n".join(lines) + "\n")

    print(f"Written {len(sorted_ids)} ACs to {OUTPUT}")


def main() -> int:
    all_acs = extract_acs()
    write_registry(all_acs)
    return 0


if __name__ == "__main__":
    sys.exit(main())
