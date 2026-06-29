#!/usr/bin/env python3
"""Mechanically generate the vision -> AC -> test proof matrix.

This is the single, generated, drift-gated artifact that maps the irreducible
``vision.md`` nodes (axioms, the Decision Filter, Directional Commitments, and
Non-Goals — every node carried by an ``<a id="...">`` anchor) to the EPICs that
declare ``Vision Anchor: <id>``, then down to those EPICs' Acceptance Criteria
and the tests that reference them.

The chain is fully derivable, so the matrix is never hand-maintained:

    vision.md (<a id="..."> anchor)
        <- EPIC docs ("Vision Anchor: <id>")
            -> AC registries (docs/ac_registry.yaml + docs/infra_registry.yaml)
                -> test references (ACx.y.z found in the AC test directories)

The matrix is a derived view. CI checks that it builds and that dangling vision
items fail through ``tools/check_ac_index.py``; no matrix file or MkDocs page is
committed-materialized.

Usage::

    python tools/generate_vision_proof_matrix.py --check
    python tools/generate_vision_proof_matrix.py --yaml-output /tmp/vision-proof-matrix.yaml
    python tools/generate_vision_proof_matrix.py --md-output /tmp/vision-proof-matrix.md
"""

from __future__ import annotations

import argparse
import functools
import os
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:  # pragma: no cover - import guard
    print("ERROR: PyYAML not installed. Run: pip install pyyaml", file=sys.stderr)
    sys.exit(1)

from common.ssot.ac_registry_format import load_registry_entries, sort_key
from common.ssot.ac_traceability_refs import AC_PATTERN, classify_reference_file
from common.ssot.test_surface import default_ac_test_dirs

REPO_ROOT = Path(__file__).resolve().parents[2]

VISION_PATH = REPO_ROOT / "vision.md"
EPIC_DIR = REPO_ROOT / "docs" / "project"
FEATURE_REGISTRY = REPO_ROOT / "docs" / "ac_registry.yaml"
INFRA_REGISTRY = REPO_ROOT / "docs" / "infra_registry.yaml"

VERSION = "1.0"

EXCLUDED_DIRS = {"node_modules", "__pycache__", ".next", "dist", ".cache"}
TEST_FILE_SUFFIXES = ("_test.py", ".test.ts", ".test.tsx", ".spec.ts", ".spec.tsx")

# vision.md anchors are declared as <a id="..."></a>.
_ANCHOR_RE = re.compile(r'<a\s+id="([^"]+)"\s*>')
# EPIC docs declare one or more anchors after a "Vision Anchor" label.
_EPIC_ANCHOR_LABEL_RE = re.compile(r"Vision Anchor", re.IGNORECASE)
_BACKTICK_ANCHOR_RE = re.compile(r"`([a-z0-9][a-z0-9-]*)`")
_EPIC_FILE_RE = re.compile(r"^(EPIC-\d+)\.")
# A blockquote continuation line such as ``> `decision-3-record-layer`,`` that
# carries anchors wrapped onto the next line of a "Vision Anchor" declaration.
_BLOCKQUOTE_LINE_RE = re.compile(r"^\s*>")
# A blockquote line that opens a *new* labelled field (``> **Phase**: ...``)
# ends the wrapped "Vision Anchor" declaration; such a line is not a continuation.
_NEW_LABEL_LINE_RE = re.compile(r"^\s*>\s*\*\*")


def _vision_path(repo_root: Path) -> Path:
    return repo_root / "vision.md"


def _epic_dir(repo_root: Path) -> Path:
    return repo_root / "docs" / "project"


def _registry_paths(repo_root: Path) -> tuple[Path, Path]:
    return (
        repo_root / "docs" / "ac_registry.yaml",
        repo_root / "docs" / "infra_registry.yaml",
    )


def load_vision_anchors(vision_path: Path = VISION_PATH) -> dict[str, str]:
    """Return ``{anchor_id: heading_or_label}`` for every vision.md anchor.

    The label is a best-effort human title for the node, resolved by
    ``_anchor_label`` in this order: (1) text on the same line as the anchor,
    (2) for a standalone anchor, the next Markdown heading or non-empty line —
    whichever comes first within the following few lines (in ``vision.md`` an
    anchor placed just before a ``## Heading`` takes that heading, and one
    placed just before a ``**bold**`` lead-in takes that text), and finally
    (3) the nearest preceding heading as a fallback. Labels are descriptive
    only; the anchor id is the join key.
    """
    text = vision_path.read_text(encoding="utf-8")
    lines = text.splitlines()
    anchors: dict[str, str] = {}
    last_heading = ""
    for idx, line in enumerate(lines):
        heading = re.match(r"^#{1,6}\s+(.*)$", line.strip())
        if heading:
            last_heading = heading.group(1).strip()
        for match in _ANCHOR_RE.finditer(line):
            anchor_id = match.group(1)
            label = _anchor_label(line, match.end(), lines, idx, last_heading)
            anchors[anchor_id] = label
    return anchors


def _anchor_label(line: str, anchor_end: int, lines: list[str], idx: int, last_heading: str) -> str:
    """Derive a short human label for an anchor."""
    # Text immediately following the anchor on the same line wins.
    tail = re.sub(r"<[^>]+>", "", line[anchor_end:]).strip()
    if not tail:
        # The anchor sits on its own line; scan the next few lines and take the
        # first meaningful one. In vision.md a standalone anchor is placed right
        # before the node it names, which is either a "## Heading" (use it as the
        # label) or a non-empty lead-in line (use that text).
        for follow in lines[idx + 1 : idx + 5]:
            if re.match(r"^#{1,6}\s", follow.strip()):
                return follow.strip().lstrip("#").strip()
            stripped = re.sub(r"<[^>]+>", "", follow).strip()
            if stripped:
                tail = stripped
                break
    if tail:
        bold = re.match(r"\*\*(.+?)\*\*", tail)
        if bold:
            return bold.group(1).strip()
        sentence = re.split(r"(?<=[.;])\s", tail, maxsplit=1)[0]
        return sentence.strip().rstrip(".")
    return last_heading


def _epic_files(epic_dir: Path = EPIC_DIR) -> list[Path]:
    return sorted(
        epic_dir / fname
        for fname in os.listdir(epic_dir)
        if re.match(r"EPIC-\d+.*\.md", fname) and "IMPLEMENTATION" not in fname and "ENCODING" not in fname
    )


def load_epic_anchor_map(epic_dir: Path = EPIC_DIR) -> dict[str, list[str]]:
    """Return ``{anchor_id: [EPIC-001, ...]}`` from EPIC ``Vision Anchor`` lines.

    A "Vision Anchor" declaration may wrap its anchor list across several
    blockquote lines (e.g. EPIC-019 carries a third anchor on the line after the
    label). Anchors on those continuation lines must be captured too, so once the
    label line is found we keep consuming following blockquote continuation lines
    until one opens a new ``**Label**`` field or the blockquote ends.
    """
    mapping: dict[str, set[str]] = defaultdict(set)
    for path in _epic_files(epic_dir):
        epic_match = _EPIC_FILE_RE.match(path.name)
        if not epic_match:
            continue
        epic_id = epic_match.group(1)
        lines = path.read_text(encoding="utf-8").splitlines()
        idx = 0
        while idx < len(lines):
            line = lines[idx]
            if not _EPIC_ANCHOR_LABEL_RE.search(line):
                idx += 1
                continue
            # Capture anchors from the label line plus any wrapped continuation
            # blockquote lines that do not start a new labelled field.
            for anchor in _BACKTICK_ANCHOR_RE.findall(line):
                mapping[anchor].add(epic_id)
            follow = idx + 1
            while (
                follow < len(lines)
                and _BLOCKQUOTE_LINE_RE.match(lines[follow])
                and not _NEW_LABEL_LINE_RE.match(lines[follow])
            ):
                for anchor in _BACKTICK_ANCHOR_RE.findall(lines[follow]):
                    mapping[anchor].add(epic_id)
                follow += 1
            idx = follow
    return {anchor: sorted(epics) for anchor, epics in mapping.items()}


def _load_registry_acs(registry_paths: tuple[Path, Path] = (FEATURE_REGISTRY, INFRA_REGISTRY)) -> dict[str, dict[str, Any]]:
    """Return ``{ac_id: {epic, epic_name, description, mandatory}}`` for both registries."""
    acs: dict[str, dict[str, Any]] = {}
    for path in registry_paths:
        for entry in load_registry_entries(path):
            ac_id = str(entry["id"])
            acs.setdefault(
                ac_id,
                {
                    "epic": int(entry["epic"]),
                    "epic_name": str(entry.get("epic_name", "")),
                    "description": str(entry.get("description", "")),
                    "mandatory": bool(entry.get("mandatory", True)),
                },
            )
    return acs


def _find_test_files(repo_root: Path = REPO_ROOT) -> list[Path]:
    found: list[Path] = []
    for base in default_ac_test_dirs(repo_root):
        if not base.exists():
            continue
        for root, dirs, files in os.walk(base):
            dirs[:] = [d for d in dirs if d not in EXCLUDED_DIRS]
            for fname in files:
                if fname.startswith("test_") or fname.endswith(TEST_FILE_SUFFIXES):
                    found.append(Path(root) / fname)
    return sorted(found)


def collect_real_test_refs(repo_root: Path = REPO_ROOT) -> dict[str, list[str]]:
    """Return ``{ac_id: [test_file, ...]}`` for real (non-stub/placeholder) refs."""
    refs: dict[str, set[str]] = defaultdict(set)
    for fpath in _find_test_files(repo_root):
        try:
            content = fpath.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if classify_reference_file(fpath, content) != "real":
            continue
        rel = fpath.relative_to(repo_root).as_posix()
        for match in AC_PATTERN.finditer(content):
            refs[match.group(0)].add(rel)
    return {ac_id: sorted(files) for ac_id, files in refs.items()}


def _epic_num(epic_id: str) -> int:
    return int(epic_id.split("-")[1])


@functools.lru_cache(maxsize=4)
def build_matrix(repo_root: Path = REPO_ROOT) -> dict[str, Any]:
    """Build the vision -> AC -> test matrix as a plain, serializable mapping.

    Building scans vision.md, every EPIC doc, both AC registries, and the AC
    test directories under ``repo_root``, so it is memoized per ``repo_root``:
    repeated calls (the CLI plus several tests) reuse one scan within a process.
    Threading ``repo_root`` through keeps the whole matrix sourced from ONE
    consistent checkout, so callers like ``ac_graph.build_ac_graph(repo_root=...)``
    (temp worktrees, tests) never mix this checkout's vision.md with another
    root's registries. The returned mapping is treated as read-only by all
    callers; do not mutate it, or call ``build_matrix.cache_clear()`` if the
    underlying files change mid-process.
    """
    repo_root = repo_root.resolve()
    anchors = load_vision_anchors(_vision_path(repo_root))
    epic_map = load_epic_anchor_map(_epic_dir(repo_root))
    acs = _load_registry_acs(_registry_paths(repo_root))
    test_refs = collect_real_test_refs(repo_root)

    # Index ACs by EPIC number for fast EPIC -> AC lookup.
    acs_by_epic: dict[int, list[str]] = defaultdict(list)
    for ac_id, meta in acs.items():
        acs_by_epic[int(meta["epic"])].append(ac_id)

    nodes: list[dict[str, Any]] = []
    # Only emit nodes for anchors that exist in vision.md (the source of truth).
    for anchor in sorted(anchors):
        owner_epics = epic_map.get(anchor, [])
        node_acs: list[dict[str, Any]] = []
        for epic_id in owner_epics:
            for ac_id in sorted(acs_by_epic.get(_epic_num(epic_id), []), key=sort_key):
                node_acs.append(
                    {
                        "id": ac_id,
                        "epic": epic_id,
                        "description": acs[ac_id]["description"],
                        "mandatory": acs[ac_id]["mandatory"],
                        "tests": test_refs.get(ac_id, []),
                    }
                )
        proven = sum(1 for ac in node_acs if ac["tests"])
        nodes.append(
            {
                "anchor": anchor,
                "label": anchors[anchor],
                "owner_epics": owner_epics,
                "ac_count": len(node_acs),
                "ac_with_test_count": proven,
                "acs": node_acs,
            }
        )

    total_acs = sum(node["ac_count"] for node in nodes)
    total_proven = sum(node["ac_with_test_count"] for node in nodes)
    return {
        "version": VERSION,
        "description": (
            "Generated vision -> AC -> test proof matrix. Maps every vision.md "
            "anchor to the EPICs that declare it, their Acceptance Criteria, and "
            "the tests that reference each AC. Generated by "
            "tools/generate_vision_proof_matrix.py; do not edit by hand."
        ),
        "summary": {
            "vision_nodes": len(nodes),
            "vision_nodes_with_owner_epic": sum(1 for node in nodes if node["owner_epics"]),
            "total_acs": total_acs,
            "acs_with_real_test": total_proven,
        },
        "vision_nodes": nodes,
    }


class _IndentedDumper(yaml.SafeDumper):
    def increase_indent(self, flow=False, indentless=False):  # noqa: ANN001
        return super().increase_indent(flow, False)


def render_yaml(matrix: dict[str, Any]) -> str:
    """Render the matrix as deterministic, parseable YAML with a header."""
    body = yaml.dump(
        matrix,
        Dumper=_IndentedDumper,
        sort_keys=False,
        allow_unicode=False,
        width=100,
    )
    return (
        "# DO NOT edit this file manually - it is generated.\n"
        "# Regenerate: python tools/generate_vision_proof_matrix.py\n"
        f"{body}"
    )


def render_markdown(matrix: dict[str, Any]) -> str:
    """Render the navigable MkDocs page for the matrix."""
    summary = matrix["summary"]
    lines = [
        "# Generated Vision-to-Proof Matrix",
        "",
        "> Generated by `python tools/generate_vision_proof_matrix.py`. Do not edit by hand.",
        "> Parseable YAML is generated on demand with "
        "`python tools/generate_vision_proof_matrix.py --yaml-output <path>`.",
        "",
        "This matrix is the single generated map from the irreducible `vision.md` "
        "nodes (anchors) to the EPICs that declare them, their Acceptance Criteria, "
        "and the tests that reference each AC. The chain "
        "`vision anchor -> EPIC -> AC -> test` is derived, never hand-maintained, "
        "and CI fails on drift.",
        "",
        "## Summary",
        "",
        "| Metric | Count |",
        "|---|---:|",
        f"| Vision nodes (anchors) | {summary['vision_nodes']} |",
        f"| Vision nodes with an owning EPIC | {summary['vision_nodes_with_owner_epic']} |",
        f"| Acceptance Criteria mapped | {summary['total_acs']} |",
        f"| ACs with a real test reference | {summary['acs_with_real_test']} |",
        "",
        "## Vision nodes",
        "",
        "| Vision anchor | Node | Owner EPICs | ACs | ACs with test |",
        "|---|---|---|---:|---:|",
    ]
    for node in matrix["vision_nodes"]:
        owners = ", ".join(node["owner_epics"]) or "_none_"
        lines.append(
            f"| `{node['anchor']}` | {_md_escape(node['label'])} | {owners} | "
            f"{node['ac_count']} | {node['ac_with_test_count']} |"
        )
    lines.append("")

    for node in matrix["vision_nodes"]:
        lines.append(f"### `{node['anchor']}`")
        lines.append("")
        lines.append(f"- **Node**: {_md_escape(node['label'])}")
        lines.append(f"- **Owner EPICs**: {', '.join(node['owner_epics']) or '_none_'}")
        lines.append(f"- **ACs**: {node['ac_count']} ({node['ac_with_test_count']} with a real test reference)")
        lines.append("")
        if not node["acs"]:
            lines.append("_No Acceptance Criteria are anchored to this node yet._")
            lines.append("")
            continue
        lines.append("| AC | EPIC | Description | Tests |")
        lines.append("|---|---|---|---|")
        for ac in node["acs"]:
            tests = "<br>".join(f"`{path}`" for path in ac["tests"]) if ac["tests"] else "_none_"
            lines.append(f"| {ac['id']} | {ac['epic']} | {_md_escape(ac['description'])} | {tests} |")
        lines.append("")

    # This page reproduces AC descriptions verbatim, so it can incidentally
    # echo rule keywords (thresholds, the Decimal rule, the transaction
    # boundary). Those rules are owned elsewhere; point at the canonical SSOT
    # owners so the rule-keyword cross-reference gate stays satisfied and
    # readers reach the source of truth, not this generated mirror.
    lines.extend(
        [
            "## Rule ownership",
            "",
            "AC descriptions above are mirrored from the EPIC docs and may echo "
            "rule keywords. The rules themselves are owned by their SSOT files:",
            "",
            "- See: docs/ssot/reconciliation.md#thresholds",
            "- See: common/ledger/readme.md#decimal-rule",
            "- See: common/ledger/readme.md#async-tx-boundary",
            "- See: common/ledger/readme.md#entry-balance",
            "- See: docs/ssot/schema.md#enum-naming",
            "",
        ]
    )

    return "\n".join(lines).rstrip() + "\n"


def _md_escape(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ").strip()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--yaml-output",
        type=Path,
        default=None,
        help="Write the parseable YAML matrix to a file (default: stdout, never committed).",
    )
    parser.add_argument(
        "--md-output",
        type=Path,
        default=None,
        help="Write the MkDocs page to a file (default: not written).",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help=(
            "Build the matrix and exit 0 if it builds. The vision matrix is a "
            "derived (not committed) view of the AC graph; dangling vision items "
            "are gated by tools/check_ac_index.py, not by a byte-compare."
        ),
    )
    args = parser.parse_args(argv)

    matrix = build_matrix()
    yaml_text = render_yaml(matrix)
    md_text = render_markdown(matrix)

    if args.check:
        print(
            "OK: vision-proof matrix builds from vision.md anchors + AC registries "
            f"({matrix['summary']['vision_nodes']} vision nodes, "
            f"{matrix['summary']['total_acs']} ACs). The matrix is a derived view "
            "and is not committed; dangling vision items are gated by "
            "tools/check_ac_index.py."
        )
        return 0

    wrote_file = False
    if args.yaml_output is not None:
        args.yaml_output.parent.mkdir(parents=True, exist_ok=True)
        args.yaml_output.write_text(yaml_text, encoding="utf-8")
        wrote_file = True
    if args.md_output is not None:
        args.md_output.parent.mkdir(parents=True, exist_ok=True)
        args.md_output.write_text(md_text, encoding="utf-8")
        wrote_file = True

    if wrote_file:
        print(
            "Wrote vision-proof matrix view(s) "
            f"({matrix['summary']['vision_nodes']} vision nodes, "
            f"{matrix['summary']['total_acs']} ACs)."
        )
    else:
        sys.stdout.write(yaml_text)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
