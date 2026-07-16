#!/usr/bin/env python3
"""Concept-ownership Manifest consistency checker (closes meta-issue horizontal-axis).

Validates the computed union of two sources (#1799):

  * ``common/meta/data/MANIFEST.yaml`` — the RESIDUAL concepts with no owning
    package (governance docs, the one frontend-app-local doc);
  * every package's own ``concepts=[ConceptRecord(...), ...]`` declaration in
    its ``contract.py``, projected by ``common.meta.data.projection.
    concept_index`` (mirrors how ``contract_index`` computes ``ac_index``
    from ``roadmap`` instead of a hand-kept AC list).

Before #1799 this validated a single hand-authored file; the concept registry
is now computed from contracts wherever a package owns the concept, same as
the AC registry. The checks themselves are unchanged:

  0. Every concept value must be a YAML mapping, not null or a scalar.
  1. No two concepts may share the same owner (file + optional anchor).
  2. Every owner *file* path (ignoring ``#anchor``) MUST exist on disk.
  3. Every cross_ref *file* path (ignoring ``#anchor``) MUST exist on disk.
  4. Every ``#anchor`` in owner and cross_ref entries MUST resolve to an
     explicit HTML id or Markdown heading slug in the referenced file.

A former rule 5 validated that every file physically present in
``docs/ssot/`` was classified in ``docs/ssot/README.md``; both are retired
along with the directory (#1823) — superseded by the terminal allowlist gate
(``tests/tooling/test_terminal_centers_allowlist.py``), which asserts
``docs/ssot/`` does not exist at all rather than merely that its contents are
classified.

The script exits 0 on success and 1 on any violation.

Usage::

    python tools/check_manifest.py
    python tools/check_manifest.py --verbose

Run in CI alongside ``tools/lint_doc_consistency.py``. Needs ``pydantic`` (to
load package contracts), not just ``pyyaml`` — its isolated CI/pre-commit
invocations pass ``--with pydantic`` accordingly.
"""

from __future__ import annotations

import argparse
import re
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import NamedTuple

from common.meta.base.gate_cli import run_gate

try:
    import yaml
except ImportError:  # pragma: no cover
    print("ERROR: PyYAML not installed. Run: pip install pyyaml", file=sys.stderr)
    sys.exit(1)

from common.meta.extension.check_package_contract import discover_packages

REPO_ROOT = Path(__file__).resolve().parents[3]
MANIFEST_PATH = REPO_ROOT / "common" / "meta" / "data" / "MANIFEST.yaml"


class Violation(NamedTuple):
    check: str
    message: str


def _file_part(ref: str) -> str:
    """Strip optional ``#anchor`` from a path string and return the file part."""
    return ref.split("#")[0]


def _anchor_part(ref: str) -> str | None:
    """Return the anchor fragment from a path string, if present."""
    if "#" not in ref:
        return None
    return ref.split("#", 1)[1]


HTML_ID_PATTERN = re.compile(r"""id\s*=\s*["'](?P<id>[^"']+)["']""", re.IGNORECASE)
MARKDOWN_HEADING_PATTERN = re.compile(r"^\s{0,3}#{1,6}\s+(?P<heading>.+?)\s*$")
HTML_TAG_PATTERN = re.compile(r"<[^>]+>")
NON_SLUG_CHARS = re.compile(r"[^a-z0-9 _-]")
WHITESPACE_OR_DASH = re.compile(r"[\s_-]+")


def _github_heading_slug(heading: str) -> str:
    """Return a close GitHub/MkDocs-compatible slug for a Markdown heading."""
    text = HTML_TAG_PATTERN.sub("", heading)
    text = text.replace("`", "").strip().lower()
    text = NON_SLUG_CHARS.sub("", text)
    text = WHITESPACE_OR_DASH.sub("-", text).strip("-")
    return text


def collect_markdown_anchors(path: Path) -> set[str]:
    """Collect explicit HTML ids and generated heading slugs from a Markdown file."""
    text = path.read_text(encoding="utf-8", errors="ignore")
    anchors = {match.group("id") for match in HTML_ID_PATTERN.finditer(text)}
    for line in text.splitlines():
        match = MARKDOWN_HEADING_PATTERN.match(line)
        if not match:
            continue
        slug = _github_heading_slug(match.group("heading"))
        if slug:
            anchors.add(slug)
    return anchors


def _is_valid_concept(concept_data: object) -> bool:
    """Return True if concept_data is a dict (a valid mapping in YAML)."""
    return isinstance(concept_data, dict)


def load_manifest(path: Path) -> dict:
    if not path.exists():
        print(f"ERROR: MANIFEST.yaml not found at {path}", file=sys.stderr)
        sys.exit(1)
    with open(path, encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    return data


def _concept_record_dict(concept: object) -> dict:
    """A ConceptRecord's fields as a plain dict, matching a MANIFEST.yaml entry's shape."""
    return {
        "owner": concept.owner,
        "description": concept.description,
        "cross_refs": list(concept.cross_refs),
        "proofs": list(concept.proofs),
        "family": concept.family,
        "kind": concept.kind,
        "authority": concept.authority,
        "parent": concept.parent,
    }


def load_computed_concepts(repo_root: Path, manifest_path: Path) -> dict:
    """The concept registry to validate: residual MANIFEST.yaml + every
    package's declared ``concepts`` (#1799), unioned like ``ac_index`` unions
    roadmap ACs across packages.

    Deliberately does NOT go through ``common.meta.data.projection.
    concept_index`` — that's a ``data``-layer projection, and this module
    lives in ``extension/``; a package's own ``extension`` may never import
    its own ``data`` (the read-model is a downstream sink, mechanism A/#1675
    idiom — ``check_package_contract``'s ``_check_data_is_sink`` enforces
    this structurally). ``concept_index`` stays available for external
    consumers who want the package-only half; this walks
    ``discover_packages()``'s contracts directly instead, mirroring
    ``concept_index``'s per-record shape without importing it.

    A concept key claimed by both the residual file and a package (or by two
    packages) is a "no concept owned twice" violation, reported the same way
    a malformed YAML file is (a clear error, exit 1) rather than silently
    letting a dict merge overwrite one owner with another.
    """
    residual = load_manifest(manifest_path).get("concepts", {})
    packages = discover_packages(repo_root)

    concepts: dict = dict(residual)
    owner_source: dict[str, str] = {key: "MANIFEST.yaml (residual)" for key in residual}
    for pkg in packages:
        for concept in pkg.contract.concepts:
            existing = owner_source.get(concept.key)
            if existing is not None:
                print(
                    f"ERROR: concept key {concept.key!r} is declared both in "
                    f"{existing} and package {pkg.name!r} — no concept may be "
                    "owned twice.",
                    file=sys.stderr,
                )
                sys.exit(1)
            owner_source[concept.key] = f"package {pkg.name!r}"
            concepts[concept.key] = _concept_record_dict(concept)

    return concepts


def check_concept_schema(concepts: dict) -> list[Violation]:
    """Rule 0: every concept value must be a mapping (dict), not null or scalar."""
    violations: list[Violation] = []
    for concept_key, concept_data in concepts.items():
        if not _is_valid_concept(concept_data):
            violations.append(
                Violation(
                    check="check0_concept_schema",
                    message=(
                        f"Concept '{concept_key}' must be a YAML mapping but got "
                        f"{type(concept_data).__name__!r}. "
                        "Expected keys: owner, description, cross_refs."
                    ),
                )
            )
    return violations


def check_duplicate_owners(concepts: dict) -> list[Violation]:
    """Rule 1: no two concepts may share the same owner."""
    owner_to_concepts: dict[str, list[str]] = {}
    for concept_key, concept_data in concepts.items():
        if not _is_valid_concept(concept_data):
            continue
        owner = concept_data.get("owner", "")
        if not owner:
            continue
        owner_to_concepts.setdefault(owner, []).append(concept_key)

    violations: list[Violation] = []
    for owner, keys in owner_to_concepts.items():
        if len(keys) > 1:
            joined = ", ".join(sorted(keys))
            violations.append(
                Violation(
                    check="check1_duplicate_owners",
                    message=(
                        f"Owner '{owner}' is claimed by multiple concepts: {joined}"
                    ),
                )
            )
    return violations


def check_owner_files_exist(concepts: dict) -> list[Violation]:
    """Rule 2: every owner file path must exist on disk."""
    violations: list[Violation] = []
    for concept_key, concept_data in concepts.items():
        if not _is_valid_concept(concept_data):
            continue
        owner = concept_data.get("owner", "")
        if not owner:
            violations.append(
                Violation(
                    check="check2_owner_exists",
                    message=f"Concept '{concept_key}' has no 'owner' field.",
                )
            )
            continue
        file_path = REPO_ROOT / _file_part(owner)
        if not file_path.exists():
            violations.append(
                Violation(
                    check="check2_owner_exists",
                    message=(
                        f"Concept '{concept_key}': owner file does not exist: "
                        f"'{_file_part(owner)}'"
                    ),
                )
            )
    return violations


def check_crossref_files_exist(concepts: dict) -> list[Violation]:
    """Rule 3: every cross_ref file path must exist on disk."""
    violations: list[Violation] = []
    for concept_key, concept_data in concepts.items():
        if not _is_valid_concept(concept_data):
            continue
        cross_refs = concept_data.get("cross_refs")
        if cross_refs is None:
            continue
        if not isinstance(cross_refs, list):
            violations.append(
                Violation(
                    check="check3_crossref_exists",
                    message=(
                        f"Concept '{concept_key}': 'cross_refs' must be a YAML list "
                        f"but got {type(cross_refs).__name__!r}. "
                        "Expected format: `cross_refs: [file1.md, file2.md]`"
                    ),
                )
            )
            continue
        for ref in cross_refs:
            if not isinstance(ref, str):
                violations.append(
                    Violation(
                        check="check3_crossref_exists",
                        message=(
                            f"Concept '{concept_key}': cross_ref entry must be a "
                            f"string but got {type(ref).__name__!r}: {ref!r}"
                        ),
                    )
                )
                continue
            file_path = REPO_ROOT / _file_part(ref)
            if not file_path.exists():
                violations.append(
                    Violation(
                        check="check3_crossref_exists",
                        message=(
                            f"Concept '{concept_key}': cross_ref file does not "
                            f"exist: '{_file_part(ref)}'"
                        ),
                    )
                )
    return violations


def check_anchor_refs_exist(concepts: dict) -> list[Violation]:
    """Rule 4: every owner/cross_ref anchor must exist in its file."""
    violations: list[Violation] = []
    anchor_cache: dict[Path, set[str]] = {}

    def check_ref(concept_key: str, field: str, ref: str) -> None:
        anchor = _anchor_part(ref)
        if not anchor:
            return
        file_path = REPO_ROOT / _file_part(ref)
        if not file_path.exists():
            return
        anchors = anchor_cache.get(file_path)
        if anchors is None:
            anchors = collect_markdown_anchors(file_path)
            anchor_cache[file_path] = anchors
        if anchor not in anchors:
            violations.append(
                Violation(
                    check="check4_anchor_exists",
                    message=(
                        f"Concept '{concept_key}': {field} anchor does not "
                        f"exist: '{ref}'"
                    ),
                )
            )

    for concept_key, concept_data in concepts.items():
        if not _is_valid_concept(concept_data):
            continue
        owner = concept_data.get("owner", "")
        if isinstance(owner, str):
            check_ref(concept_key, "owner", owner)

        cross_refs = concept_data.get("cross_refs")
        if not isinstance(cross_refs, list):
            continue
        for ref in cross_refs:
            if isinstance(ref, str):
                check_ref(concept_key, "cross_ref", ref)
    return violations


def _run_command(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate common/meta/data/MANIFEST.yaml consistency."
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Print summary statistics even on success.",
    )
    args = parser.parse_args(argv)

    concepts = load_computed_concepts(REPO_ROOT, MANIFEST_PATH)

    if not concepts:
        print(
            "ERROR: No concepts found (MANIFEST.yaml + package contracts).",
            file=sys.stderr,
        )
        return 1

    violations: list[Violation] = []
    violations.extend(check_concept_schema(concepts))
    violations.extend(check_duplicate_owners(concepts))
    violations.extend(check_owner_files_exist(concepts))
    violations.extend(check_crossref_files_exist(concepts))
    violations.extend(check_anchor_refs_exist(concepts))

    if args.verbose or violations:
        print("=" * 72)
        print("SSOT Manifest check (tools/check_manifest.py)")
        print("=" * 72)
        print(f"  Concepts in manifest : {len(concepts)}")
        print()

    if not violations:
        if args.verbose:
            print("OK: manifest check passed.")
        return 0

    grouped: dict[str, list[Violation]] = {}
    for violation in violations:
        grouped.setdefault(violation.check, []).append(violation)

    print(
        f"FAIL: manifest check found {len(violations)} violation(s) "
        f"across {len(grouped)} check(s).",
        file=sys.stderr,
    )
    print("", file=sys.stderr)
    for check_name in sorted(grouped):
        items = grouped[check_name]
        print(f"[{check_name}] {len(items)} violation(s):", file=sys.stderr)
        for violation in items:
            print(f"  - {violation.message}", file=sys.stderr)
        print("", file=sys.stderr)

    return 1


def main(argv: Sequence[str] | None = None) -> int:
    try:
        status = _run_command(argv)
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else 1
    if status == 2:
        return 2
    findings = [] if status == 0 else [f"command returned status {status}"]
    return run_gate("MANIFEST", lambda _repo_root: findings, [], failure_status=status)


if __name__ == "__main__":
    raise SystemExit(main())
