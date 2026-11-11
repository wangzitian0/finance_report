#!/usr/bin/env python3
"""Concept-ownership Manifest consistency checker."""

from __future__ import annotations

import argparse
import re
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import NamedTuple

from common.meta.base.gate_cli import run_cli_command

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
    return ref.split("#")[0]


def _anchor_part(ref: str) -> str | None:
    return ref.split("#", 1)[1] if "#" in ref else None


HTML_ID_PATTERN = re.compile(r"""id\s*=\s*["'](?P<id>[^"']+)["']""", re.IGNORECASE)
MARKDOWN_HEADING_PATTERN = re.compile(r"^\s{0,3}#{1,6}\s+(?P<heading>.+?)\s*$")
HTML_TAG_PATTERN = re.compile(r"<[^>]+>")
NON_SLUG_CHARS = re.compile(r"[^a-z0-9 _-]")
WHITESPACE_OR_DASH = re.compile(r"[\s_-]+")


def _github_heading_slug(heading: str) -> str:
    text = HTML_TAG_PATTERN.sub("", heading).replace("`", "").strip().lower()
    text = NON_SLUG_CHARS.sub("", text)
    return WHITESPACE_OR_DASH.sub("-", text).strip("-")


def collect_markdown_anchors(path: Path) -> set[str]:
    text = path.read_text(encoding="utf-8", errors="ignore")
    anchors = {match.group("id") for match in HTML_ID_PATTERN.finditer(text)}
    for line in text.splitlines():
        match = MARKDOWN_HEADING_PATTERN.match(line)
        if match:
            slug = _github_heading_slug(match.group("heading"))
            if slug:
                anchors.add(slug)
    return anchors


def _is_valid_concept(concept_data: object) -> bool:
    return isinstance(concept_data, dict)


def load_manifest(path: Path) -> dict:
    if not path.exists():
        print(f"ERROR: MANIFEST.yaml not found at {path}", file=sys.stderr)
        sys.exit(1)
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def _concept_record_dict(concept: object) -> dict:
    return {
        "owner": concept.owner,  # type: ignore[attr-defined]
        "description": concept.description,  # type: ignore[attr-defined]
        "cross_refs": list(concept.cross_refs),  # type: ignore[attr-defined]
        "proofs": list(concept.proofs),  # type: ignore[attr-defined]
        "family": concept.family,  # type: ignore[attr-defined]
        "kind": concept.kind,  # type: ignore[attr-defined]
        "authority": concept.authority,  # type: ignore[attr-defined]
        "parent": concept.parent,  # type: ignore[attr-defined]
    }


def load_computed_concepts(repo_root: Path, manifest_path: Path) -> dict:
    residual = load_manifest(manifest_path).get("concepts", {})
    concepts: dict = dict(residual)
    owner_source: dict[str, str] = {key: "MANIFEST.yaml (residual)" for key in residual}
    for pkg in discover_packages(repo_root):
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
    return [
        Violation(
            "check0_concept_schema",
            f"Concept '{key}' must be a YAML mapping but got "
            f"{type(data).__name__!r}. Expected keys: owner, description, cross_refs.",
        )
        for key, data in concepts.items()
        if not _is_valid_concept(data)
    ]


def check_duplicate_owners(concepts: dict) -> list[Violation]:
    owner_to_concepts: dict[str, list[str]] = {}
    for key, data in concepts.items():
        if _is_valid_concept(data) and data.get("owner"):
            owner_to_concepts.setdefault(data["owner"], []).append(key)
    return [
        Violation(
            "check1_duplicate_owners",
            f"Owner '{owner}' is claimed by multiple concepts: {', '.join(sorted(keys))}",
        )
        for owner, keys in owner_to_concepts.items()
        if len(keys) > 1
    ]


def check_owner_files_exist(concepts: dict) -> list[Violation]:
    violations: list[Violation] = []
    for key, data in concepts.items():
        if not _is_valid_concept(data):
            continue
        owner = data.get("owner", "")
        if not owner:
            violations.append(
                Violation(
                    "check2_owner_exists", f"Concept '{key}' has no 'owner' field."
                )
            )
        elif not (REPO_ROOT / _file_part(owner)).exists():
            violations.append(
                Violation(
                    "check2_owner_exists",
                    f"Concept '{key}': owner file does not exist: '{_file_part(owner)}'",
                )
            )
    return violations


def check_crossref_files_exist(concepts: dict) -> list[Violation]:
    violations: list[Violation] = []
    for key, data in concepts.items():
        if not _is_valid_concept(data):
            continue
        cross_refs = data.get("cross_refs")
        if cross_refs is None:
            continue
        if not isinstance(cross_refs, list):
            violations.append(
                Violation(
                    "check3_crossref_exists",
                    f"Concept '{key}': 'cross_refs' must be a YAML list but got "
                    f"{type(cross_refs).__name__!r}. Expected format: `cross_refs: [file1.md, file2.md]`",
                )
            )
            continue
        for ref in cross_refs:
            if not isinstance(ref, str):
                violations.append(
                    Violation(
                        "check3_crossref_exists",
                        f"Concept '{key}': cross_ref entry must be a string but got {type(ref).__name__!r}: {ref!r}",
                    )
                )
            elif not (REPO_ROOT / _file_part(ref)).exists():
                violations.append(
                    Violation(
                        "check3_crossref_exists",
                        f"Concept '{key}': cross_ref file does not exist: '{_file_part(ref)}'",
                    )
                )
    return violations


def check_anchor_refs_exist(concepts: dict) -> list[Violation]:
    violations: list[Violation] = []
    anchor_cache: dict[Path, set[str]] = {}

    def check_ref(concept_key: str, field: str, ref: str) -> None:
        anchor = _anchor_part(ref)
        file_path = REPO_ROOT / _file_part(ref) if anchor else None
        if not anchor or file_path is None or not file_path.exists():
            return
        anchors = anchor_cache.setdefault(
            file_path, collect_markdown_anchors(file_path)
        )
        if anchor not in anchors:
            violations.append(
                Violation(
                    "check4_anchor_exists",
                    f"Concept '{concept_key}': {field} anchor does not exist: '{ref}'",
                )
            )

    for key, data in concepts.items():
        if not _is_valid_concept(data):
            continue
        owner = data.get("owner", "")
        if isinstance(owner, str):
            check_ref(key, "owner", owner)
        cross_refs = data.get("cross_refs")
        if isinstance(cross_refs, list):
            for ref in cross_refs:
                if isinstance(ref, str):
                    check_ref(key, "cross_ref", ref)
    return violations


def _main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate common/meta/data/MANIFEST.yaml consistency."
    )
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args(argv)

    concepts = load_computed_concepts(REPO_ROOT, MANIFEST_PATH)
    if not concepts:
        print(
            "ERROR: No concepts found (MANIFEST.yaml + package contracts).",
            file=sys.stderr,
        )
        return 1

    violations = [
        *check_concept_schema(concepts),
        *check_duplicate_owners(concepts),
        *check_owner_files_exist(concepts),
        *check_crossref_files_exist(concepts),
        *check_anchor_refs_exist(concepts),
    ]
    if args.verbose or violations:
        print("=" * 72)
        print("SSOT Manifest check (tools/check_manifest.py)")
        print("=" * 72)
        print(f"  Concepts in manifest : {len(concepts)}\n")
    if not violations:
        if args.verbose:
            print("OK: manifest check passed.")
        return 0

    grouped: dict[str, list[Violation]] = {}
    for violation in violations:
        grouped.setdefault(violation.check, []).append(violation)
    print(
        f"FAIL: manifest check found {len(violations)} violation(s) "
        f"across {len(grouped)} check(s).\n",
        file=sys.stderr,
    )
    for check_name in sorted(grouped):
        items = grouped[check_name]
        print(f"[{check_name}] {len(items)} violation(s):", file=sys.stderr)
        for violation in items:
            print(f"  - {violation.message}", file=sys.stderr)
        print("", file=sys.stderr)
    return 1


def main(argv: Sequence[str] | None = None) -> int:
    return run_cli_command(_main, argv)


if __name__ == "__main__":
    raise SystemExit(main())
