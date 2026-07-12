#!/usr/bin/env python3
"""SSOT Manifest consistency checker (closes meta-issue horizontal-axis).

Validates ``docs/ssot/MANIFEST.yaml`` against the following rules:

  1. No two concepts may share the same owner (file + optional anchor).
  2. Every owner *file* path (ignoring ``#anchor``) MUST exist on disk.
  3. Every cross_ref *file* path (ignoring ``#anchor``) MUST exist on disk.
  4. Every ``#anchor`` in owner and cross_ref entries MUST resolve to an
     explicit HTML id or Markdown heading slug in the referenced file.
  5. (AC-meta.manifest.1) Every file physically present in ``docs/ssot/``
     MUST be referenced by name in ``docs/ssot/README.md`` — the pointer
     page that classifies every surviving file (cross-cutting infra, live
     gate data, generated artifact, or migrated pointer stub, #1664). This
     is the anti-drift check that stands in for a full computed concept
     index (tracked as a follow-up, see docs/ssot/README.md).

The script exits 0 on success and 1 on any violation.

Usage::

    python tools/check_manifest.py
    python tools/check_manifest.py --verbose

Run in CI alongside ``tools/lint_doc_consistency.py``.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import NamedTuple

try:
    import yaml
except ImportError:  # pragma: no cover
    print("ERROR: PyYAML not installed. Run: pip install pyyaml", file=sys.stderr)
    sys.exit(1)

REPO_ROOT = Path(__file__).resolve().parents[3]
MANIFEST_PATH = REPO_ROOT / "docs" / "ssot" / "MANIFEST.yaml"


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


# Files that are the registry/index itself, not a concept the registry
# classifies — excluded from check5 so the check doesn't self-flag.
DOCS_SSOT_CLASSIFICATION_EXEMPT: frozenset[str] = frozenset({"README.md", "MANIFEST.yaml"})


def check_docs_ssot_files_classified() -> list[Violation]:
    """Rule 5 (AC-meta.manifest.1, anti-drift): every file physically present
    in ``docs/ssot/`` must be referenced by name in ``docs/ssot/README.md``.

    ``docs/ssot/README.md`` is the pointer page recording *why* each
    surviving file is there (cross-cutting infra doc, live gate-data input,
    generated artifact, or a migrated-domain-doc pointer stub — migration
    closeout wave 3, #1664). A file dropped into ``docs/ssot/`` without a
    matching README entry is exactly the silent, unclassified drift #1664
    closed out; this check keeps it closed without requiring the full
    computed-concept-index rewrite (tracked as a follow-up).

    This does not replace ``check_owner_files_exist`` / ``check_anchor_refs_exist``
    (which validate MANIFEST *concept* entries) — it validates the directory
    listing directly, so it also catches a file that has no MANIFEST concept
    pointing at it at all.
    """
    violations: list[Violation] = []
    ssot_dir = REPO_ROOT / "docs" / "ssot"
    readme_path = ssot_dir / "README.md"
    if not readme_path.exists():
        return [
            Violation(
                check="check5_docs_ssot_classified",
                message=f"{readme_path.relative_to(REPO_ROOT)} is missing.",
            )
        ]
    readme_text = readme_path.read_text(encoding="utf-8", errors="ignore")

    for path in sorted(ssot_dir.iterdir()):
        if not path.is_file() or path.name in DOCS_SSOT_CLASSIFICATION_EXEMPT:
            continue
        if path.name not in readme_text:
            violations.append(
                Violation(
                    check="check5_docs_ssot_classified",
                    message=(
                        f"docs/ssot/{path.name} is not referenced anywhere in "
                        "docs/ssot/README.md. Every surviving docs/ssot/ file "
                        "must be classified there — as cross-cutting infra "
                        "(Cross-Cutting Classification table), live gate data "
                        "(Gate Data Directory section), a generated artifact, "
                        "or a migrated pointer stub — so ownership stays "
                        "explicit and machine-greppable (#1664)."
                    ),
                )
            )
    return violations


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate docs/ssot/MANIFEST.yaml consistency."
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Print summary statistics even on success.",
    )
    args = parser.parse_args()

    data = load_manifest(MANIFEST_PATH)
    concepts: dict = data.get("concepts", {})

    if not concepts:
        print("ERROR: No concepts found in MANIFEST.yaml.", file=sys.stderr)
        return 1

    violations: list[Violation] = []
    violations.extend(check_concept_schema(concepts))
    violations.extend(check_duplicate_owners(concepts))
    violations.extend(check_owner_files_exist(concepts))
    violations.extend(check_crossref_files_exist(concepts))
    violations.extend(check_anchor_refs_exist(concepts))
    violations.extend(check_docs_ssot_files_classified())

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


if __name__ == "__main__":
    sys.exit(main())
