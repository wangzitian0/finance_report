"""Generate the README EPIC status table from registries and test reports.

EPIC status and completion are *derived* facts, not hand-written prose. This
module renders a per-EPIC status table from the canonical sources and either
writes it into a clearly delimited generated block in the README, or (with
``--check``) fails CI when the committed block drifts from the regenerated one.

Sources (read-if-present; tolerate absence gracefully):
- ``docs/ac_registry.yaml`` / ``docs/infra_registry.yaml`` — the AC registries,
  consumed through :func:`common.testing.analyze_test_ac_coverage.analyze_repo` so
  the coverage accounting matches the AC coverage report exactly.
- ``tmp/test-ac-coverage-report.md`` — the generated AC coverage
  snapshot (referenced for provenance; counts are recomputed live, not parsed).
- ``unified-coverage.json`` — the committed unified line-coverage baseline
  (repaired by #414). Used only for an optional code-coverage column; absence is
  tolerated.

The four EPIC-completion categories are reported **separately**, never collapsed
into one "percent done":

- ``automated AC coverage`` — active ACs proven by a real (non-placeholder,
  non-stub) test reference.
- ``placeholder/stub debt`` — active ACs whose only references are placeholder
  assertions or ``_ac_stubs`` placeholders.
- ``manual-gate debt`` — active ACs explicitly registry-marked ``mandatory:
  false`` because they rely on manual / e2e-only verification rather than the
  mandatory automated gate.
- ``blockers`` — active, mandatory ACs with no proof of any kind (the real work
  remaining).

Deliberately **not** rendered here: live CI run status, deploy run status, or
Coveralls pass/fail. Those are mutable run-time facts owned by GitHub and the CI
system; duplicating them in static docs is exactly the drift this generator
exists to prevent.
"""

from __future__ import annotations

import argparse
import difflib
import json
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from common.meta.extension.ac_registry_format import load_registry_entries
from common.testing.analyze_test_ac_coverage import (
    AnalysisResult,
    _is_deprecated_description,
    analyze_repo,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = REPO_ROOT / "README.md"
DEFAULT_COVERAGE_JSON = REPO_ROOT / "unified-coverage.json"
COVERAGE_REPORT = "tmp/test-ac-coverage-report.md"

BEGIN_MARKER = "<!-- BEGIN GENERATED: epic-status -->"
END_MARKER = "<!-- END GENERATED: epic-status -->"

REGISTRY_PATHS = ("docs/ac_registry.yaml", "docs/infra_registry.yaml")


@dataclass(frozen=True)
class EpicCompletion:
    """Per-EPIC completion broken into separately reported categories."""

    epic: int
    epic_name: str
    active: int
    automated_covered: int
    placeholder_stub_debt: int
    manual_gate_debt: int
    blockers: int
    deprecated: int

    @property
    def automated_pct(self) -> float:
        return (self.automated_covered / self.active * 100.0) if self.active else 100.0


def _manual_gate_ids(repo_root: Path) -> set[str]:
    """Active ACs registry-marked ``mandatory: false`` (manual / e2e-only).

    These are excluded from the mandatory automated coverage gate by an explicit
    registry decision, so they are *manual-gate debt* rather than blockers. A
    missing registry file is read-if-present and simply contributes no
    manual-gate IDs; a malformed/unparseable registry is *not* swallowed here —
    ``load_registry_entries`` raises, matching the AC coverage report's
    fail-closed behavior so drift cannot hide behind a silently empty bucket.
    """
    manual_ids: set[str] = set()
    for rel in REGISTRY_PATHS:
        path = repo_root / rel
        if not path.exists():
            continue
        for entry in load_registry_entries(path):
            if entry.get("mandatory", True):
                continue
            description = str(entry.get("description", ""))
            # A fully strikethrough-wrapped description marks a deprecated AC,
            # which is a separate category and must not be double-counted as
            # manual-gate. Use the canonical rule from analyze_test_ac_coverage
            # so this matches how deprecation is decided everywhere else.
            if _is_deprecated_description(description):
                continue
            manual_ids.add(str(entry["id"]))
    return manual_ids


def build_completions(
    result: AnalysisResult,
    manual_gate_ids: set[str],
) -> list[EpicCompletion]:
    """Split per-EPIC AC accounting into the four separate categories."""
    by_epic: dict[int, dict[str, object]] = {}
    for ac in result.registry.values():
        bucket = by_epic.setdefault(
            ac.epic,
            {
                "epic_name": ac.epic_name,
                "active": 0,
                "automated_covered": 0,
                "placeholder_stub_debt": 0,
                "manual_gate_debt": 0,
                "blockers": 0,
                "deprecated": 0,
            },
        )
        if ac.id in result.deprecated_ids:
            bucket["deprecated"] = int(bucket["deprecated"]) + 1
            continue

        bucket["active"] = int(bucket["active"]) + 1
        if ac.id in result.covered_ids:
            bucket["automated_covered"] = int(bucket["automated_covered"]) + 1
        elif ac.id in result.placeholder_only_ids or ac.id in result.stub_only_ids:
            bucket["placeholder_stub_debt"] = int(bucket["placeholder_stub_debt"]) + 1
        elif ac.id in manual_gate_ids:
            bucket["manual_gate_debt"] = int(bucket["manual_gate_debt"]) + 1
        else:
            bucket["blockers"] = int(bucket["blockers"]) + 1

    return [
        EpicCompletion(
            epic=epic,
            epic_name=str(bucket["epic_name"]),
            active=int(bucket["active"]),
            automated_covered=int(bucket["automated_covered"]),
            placeholder_stub_debt=int(bucket["placeholder_stub_debt"]),
            manual_gate_debt=int(bucket["manual_gate_debt"]),
            blockers=int(bucket["blockers"]),
            deprecated=int(bucket["deprecated"]),
        )
        for epic, bucket in sorted(by_epic.items())
    ]


def load_unified_coverage(path: Path) -> float | None:
    """Return overall line-coverage percent from ``unified-coverage.json``.

    Read-if-present: a missing or malformed file yields ``None`` (rendered as a
    placeholder) so this generator never depends on #414 having landed.
    """
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    value = data.get("coverage_percent")
    if isinstance(value, (int, float)):
        return float(value)
    return None


def render_block(
    completions: list[EpicCompletion],
    coverage_percent: float | None,
) -> str:
    """Render the delimited generated EPIC-status block (markers included)."""
    total_active = sum(c.active for c in completions)
    total_covered = sum(c.automated_covered for c in completions)
    total_placeholder_stub = sum(c.placeholder_stub_debt for c in completions)
    total_manual = sum(c.manual_gate_debt for c in completions)
    total_blockers = sum(c.blockers for c in completions)
    total_deprecated = sum(c.deprecated for c in completions)
    overall_pct = (total_covered / total_active * 100.0) if total_active else 100.0

    coverage_cell = (
        f"`{coverage_percent:.1f}%`"
        if coverage_percent is not None
        else "`n/a` (unified-coverage.json absent)"
    )

    lines: list[str] = [
        BEGIN_MARKER,
        "",
        "> Generated by `python tools/generate_epic_status.py`. Do not edit by hand.",
        "> Derived from `docs/ac_registry.yaml`, `docs/infra_registry.yaml`,"
        f" `{COVERAGE_REPORT}`, and `unified-coverage.json`.",
        "> Completion is reported as four **separate** categories — automated AC"
        " coverage, placeholder/stub debt, manual-gate debt, and blockers — never"
        " a single percent.",
        "> Live CI and deploy run status are intentionally omitted; they are"
        " mutable run-time facts owned by GitHub and CI, not static docs.",
        "",
        "| EPIC | Name | Active ACs | Automated covered | Placeholder/stub debt"
        " | Manual-gate debt | Blockers | Deprecated |",
        "|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    for c in completions:
        lines.append(
            f"| EPIC-{c.epic:03d} | {c.epic_name} | {c.active} | "
            f"{c.automated_covered} ({c.automated_pct:.1f}%) | "
            f"{c.placeholder_stub_debt} | {c.manual_gate_debt} | "
            f"{c.blockers} | {c.deprecated} |"
        )
    lines.append(
        f"| **Total** | all EPICs | **{total_active}** | "
        f"**{total_covered} ({overall_pct:.1f}%)** | "
        f"**{total_placeholder_stub}** | **{total_manual}** | "
        f"**{total_blockers}** | **{total_deprecated}** |"
    )
    lines.extend(
        [
            "",
            f"- Repo line coverage (from `unified-coverage.json`): {coverage_cell}.",
            "- `Automated covered` is the only category that counts as proof;"
            " the three debt columns are work remaining, reported apart so a high"
            " coverage number cannot hide manual or placeholder debt.",
            "",
            END_MARKER,
        ]
    )
    return "\n".join(lines)


def render_pointer_block() -> str:
    """Render the STABLE committed EPIC-status block (markers + on-demand pointer).

    The per-EPIC completion numbers are a DERIVED view of the one AC-keyed graph
    and are NOT committed: a committed snapshot churns on every AC change and was
    a merge-train false-sharing hotspot. The committed README therefore carries
    only this fixed pointer; the live numbers are rendered on demand by
    ``--stdout``. Because this block is constant, ``--check`` never fails on a
    shifted AC total — only on a malformed/missing marker.
    """
    return "\n".join(
        [
            BEGIN_MARKER,
            "",
            "> EPIC status is a DERIVED view of the one AC-keyed graph (see",
            '> [`common/testing/tdd.md`](common/testing/tdd.md) "Cross-Cutting Index Artifacts"). The',
            "> per-EPIC completion numbers are **not committed** here, because a committed",
            "> snapshot churns on every AC change and is the merge-train false-sharing",
            "> hotspot this model removes.",
            ">",
            "> Render the live table on demand:",
            ">",
            "> ```bash",
            "> python tools/generate_epic_status.py --stdout",
            "> ```",
            ">",
            "> It reports four **separate** completion categories — automated AC coverage,",
            "> placeholder/stub debt, manual-gate debt, and blockers — never a single",
            "> percent, derived from `docs/ac_registry.yaml`, `docs/infra_registry.yaml`, the",
            "> AC coverage report, and `unified-coverage.json`. Consistency (no dangling /",
            "> missing proof) is gated by `python tools/check_ac_index.py`; live CI and",
            "> deploy run status are intentionally excluded.",
            "",
            END_MARKER,
        ]
    )


def generate_block(
    repo_root: Path = REPO_ROOT,
    coverage_json: Path | None = None,
) -> str:
    """Compute and render the LIVE EPIC-status block from the AC-graph sources.

    Used for the on-demand ``--stdout`` rendering, never committed. It is a thin
    projection of the one AC-keyed graph: completion is computed from the same AC
    registries (graph nodes) and the test references the graph already models.
    """
    repo_root = repo_root.resolve()
    result = analyze_repo(repo_root=repo_root)
    manual_gate_ids = _manual_gate_ids(repo_root)
    completions = build_completions(result, manual_gate_ids)
    coverage_path = coverage_json or (repo_root / "unified-coverage.json")
    coverage_percent = load_unified_coverage(coverage_path)
    return render_block(completions, coverage_percent)


def splice_block(document: str, block: str) -> str:
    """Replace the delimited generated block inside ``document`` with ``block``.

    Raises ``ValueError`` if the markers are missing or malformed so a silently
    un-spliced document can never pass ``--check``.
    """
    start = document.find(BEGIN_MARKER)
    end = document.find(END_MARKER)
    if start == -1 or end == -1 or end < start:
        raise ValueError(
            f"EPIC status markers not found or malformed; expected {BEGIN_MARKER!r} ... {END_MARKER!r}"
        )
    end += len(END_MARKER)
    return document[:start] + block + document[end:]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="Markdown document containing the generated EPIC-status block.",
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=REPO_ROOT,
        help="Repository root used to discover registries and test files.",
    )
    parser.add_argument(
        "--coverage-json",
        type=Path,
        default=None,
        help="Path to unified-coverage.json (default: <repo-root>/unified-coverage.json).",
    )
    parser.add_argument(
        "--stdout",
        action="store_true",
        help="Print the LIVE per-EPIC completion table to stdout (never committed).",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help=(
            "Fail only if the committed README EPIC-status pointer block is "
            "missing or malformed. The block is a stable on-demand pointer, so "
            "this never fails on a shifted AC total."
        ),
    )
    args = parser.parse_args(argv)

    # The live numeric table is a derived view, rendered on demand only.
    if args.stdout:
        print(
            generate_block(repo_root=args.repo_root, coverage_json=args.coverage_json)
        )
        return 0

    output = args.output
    pointer = render_pointer_block()

    try:
        document = output.read_text(encoding="utf-8")
    except OSError:
        print(f"ERROR: EPIC status document is missing: {output}", file=sys.stderr)
        return 1

    try:
        updated = splice_block(document, pointer)
    except ValueError as exc:
        print(f"ERROR: {exc} in {output}", file=sys.stderr)
        return 1

    if args.check:
        if document != updated:
            diff = difflib.unified_diff(
                document.splitlines(),
                updated.splitlines(),
                fromfile=str(output),
                tofile="generated",
                lineterm="",
            )
            print(
                "ERROR: README EPIC-status pointer block is missing or malformed.",
                file=sys.stderr,
            )
            print("\n".join(diff), file=sys.stderr)
            print("  Run: python tools/generate_epic_status.py", file=sys.stderr)
            return 1
        print(f"OK: EPIC status pointer block is current: {output}")
        return 0

    output.write_text(updated, encoding="utf-8")
    print(f"Wrote EPIC status pointer block: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
