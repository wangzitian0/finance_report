#!/usr/bin/env python3
import argparse
import ast
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

# EPIC classification: which EPICs are feature vs infra
FEATURE_EPICS = {1, 2, 3, 4, 5, 6, 8, 11, 13, 15, 16, 17, 18, 19, 20, 21, 22, 23}
INFRA_EPICS = {7, 9, 10, 12, 14, 26}

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
    23: "llm-provider-abstraction",
    24: "frontend-observability",
    26: "ac-authority-tiers",
}


AC_PATTERN = re.compile(r"\b(AC(\d+)\.(\d+)\.(\d+))\b")

# Authority tier vocabulary (SSOT: docs/ssot/authority-tiers.md). One AC = one
# tier; the tier dictates what KIND of proof is valid for the AC's behavior.
AC_TIERS = ("PC", "CP", "HU", "LP", "PL")

# Definition-site tier marker, e.g. ``{tier:PC}``. Declared next to the AC text
# in the EPIC doc so the tier travels with the behavior it describes. The marker
# is parsed out of the line and lifted into the registry value; it never leaks
# into the AC description.
_TIER_MARKER_RE = re.compile(r"\{tier:\s*(PC|CP|HU|LP|PL)\s*\}", re.IGNORECASE)

# Proof-kind vocabulary (SSOT: docs/ssot/authority-tiers.md). The KIND of proof
# an AC's tests provide; an AC's tier dictates which kinds are VALID for it (the
# tier->proof matrix, enforced by tools/check_ac_proof_kind.py for tier-tagged
# ACs). ``exact`` = deterministic exact/golden assertion; ``property`` /
# ``invariant`` = an asserted invariant that holds across inputs (e.g. a balance
# chain); ``eval`` = graded/quality eval; ``evidence`` = an evidence-chain
# assertion (HU); ``smoke`` = guardrail/quality smoke (PL).
AC_PROOF_KINDS = ("property", "invariant", "eval", "exact", "evidence", "smoke")

# Definition-site proof-kind marker, e.g. ``{proof:property}``. Declared next to
# the AC text the same way as ``{tier:XX}`` and lifted into the registry value as
# ``proof_kind``; stripped from the description so it never leaks.
_PROOF_MARKER_RE = re.compile(
    r"\{proof:\s*(property|invariant|eval|exact|evidence|smoke)\s*\}",
    re.IGNORECASE,
)

# When an AC declares a tier but no explicit ``{proof:KIND}`` marker, its
# proof_kind defaults to the tier's CANONICAL valid kind, so the registry value
# is always a kind the matrix accepts (never a sentinel the gate must reject).
# Untagged ACs get no proof_kind key at all.
_TIER_DEFAULT_PROOF = {
    "PC": "exact",
    "CP": "exact",
    "HU": "evidence",
    "LP": "property",
    "PL": "smoke",
}


def _extract_tier(text: str) -> tuple[str, str | None]:
    """Split an inline ``{tier:XX}`` marker out of *text*.

    Returns ``(text_without_marker, tier_or_None)``. The tier code is upper-cased
    to the canonical vocabulary. Text with no marker is returned unchanged.
    """
    match = _TIER_MARKER_RE.search(text)
    if not match:
        return text, None
    tier = match.group(1).upper()
    cleaned = _TIER_MARKER_RE.sub("", text)
    return cleaned, tier


def _extract_proof(text: str) -> tuple[str, str | None]:
    """Split an inline ``{proof:KIND}`` marker out of *text*.

    Returns ``(text_without_marker, proof_kind_or_None)``. The kind is
    lower-cased to the canonical vocabulary. Text with no marker is unchanged.
    """
    match = _PROOF_MARKER_RE.search(text)
    if not match:
        return text, None
    proof_kind = match.group(1).lower()
    cleaned = _PROOF_MARKER_RE.sub("", text)
    return cleaned, proof_kind


def _default_proof_for_tier(tier: str | None) -> str | None:
    """Canonical proof kind for a tier when no ``{proof:KIND}`` marker is given."""
    if not tier:
        return None
    return _TIER_DEFAULT_PROOF.get(tier.upper())


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


def _extract_ac_definition(
    line: str,
) -> tuple[str, int, str, str | None, str | None] | None:
    """Extract one AC definition from a Markdown table, bullet, or plain line.

    Returns ``(ac_id, epic, description, tier, proof_kind)`` where ``tier`` is the
    optional authority-tier code declared via a ``{tier:XX}`` marker (one of
    :data:`AC_TIERS`) and ``proof_kind`` the optional proof-kind code declared via
    a ``{proof:KIND}`` marker (one of :data:`AC_PROOF_KINDS`); each is ``None``
    when its marker is absent. Both markers are stripped from the description so
    neither leaks into the registry text, and may appear anywhere on the line
    (any cell of a table row).
    """
    if _is_reference_only_line(line):
        return None

    stripped = line.strip()
    if not stripped:
        return None

    # Strip both definition-site markers BEFORE splitting table cells, so a
    # marker in any cell is lifted and never leaks into the description.
    stripped, tier = _extract_tier(stripped)
    stripped, proof_kind = _extract_proof(stripped)

    if stripped.startswith("|"):
        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        if not cells:
            return None
        match = AC_PATTERN.fullmatch(cells[0])
        if not match:
            return None
        desc = _clean_description(cells[1] if len(cells) > 1 else "")
        return match.group(1), int(match.group(2)), desc, tier, proof_kind

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
    return ac_id, ac_epic, desc, tier, proof_kind


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


_HEADING_AC_PATTERN = re.compile(r"^#{2,6}\s+(AC\d+\.\d+)\b")


def _epic_files(epic_dir: str | Path | None = None) -> list[Path]:
    source_dir = Path(epic_dir or EPIC_DIR)
    return [
        source_dir / f
        for f in sorted(os.listdir(source_dir))
        if re.match(r"EPIC-\d+.*\.md", f)
        and "IMPLEMENTATION" not in f
        and "ENCODING" not in f
    ]


def find_ac_collisions(
    epic_dir: str | Path | None = None,
) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    """Find AC identity collisions in EPIC docs.

    Returns ``(duplicate_definitions, duplicate_headings)``:

    - ``duplicate_definitions``: ``ACx.y.z`` defined by more than one Markdown
      **table row** (``| ACx.y.z | ... |``). ``extract_acs`` keeps the first and
      silently drops the rest, so a collision can hide a real, differently-scoped
      AC (and its test) from the registry. Only table rows count — checklist
      bullets that merely restate an AC are not competing definitions.
    - ``duplicate_headings``: ``### ACx.y`` group heading repeated within one EPIC,
      which makes the group's namespace and "next free index" ambiguous.
    """
    def_locations: dict[str, list[str]] = {}
    heading_locations: dict[str, list[str]] = {}
    for path in _epic_files(epic_dir):
        with open(path, encoding="utf-8") as f:
            for line in f:
                stripped = line.strip()
                heading = _HEADING_AC_PATTERN.match(stripped)
                if heading:
                    heading_locations.setdefault(
                        f"{path.name}:{heading.group(1)}", []
                    ).append(path.name)
                    continue
                if not stripped.startswith("|"):
                    continue
                cells = [cell.strip() for cell in stripped.strip("|").split("|")]
                if cells and AC_PATTERN.fullmatch(cells[0]):
                    def_locations.setdefault(cells[0], []).append(path.name)
    duplicate_definitions = {k: v for k, v in def_locations.items() if len(v) > 1}
    duplicate_headings = {k: v for k, v in heading_locations.items() if len(v) > 1}
    return duplicate_definitions, duplicate_headings


# Package contracts (``common/<pkg>/contract.py``) are a SECOND, additive source
# of ACs: a package's ``roadmap`` owns its ACs directly, so they no longer need a
# mirrored EPIC table. Discovery reuses the governance gate's scanner so the two
# stay in lockstep.


def _repo_root_for(source_dir: Path) -> Path:
    """Derive the repo root from the EPIC ``source_dir`` (``<root>/docs/project``).

    Package contracts live at ``<root>/common/*/contract.py``, so the package
    scan must use the SAME root the EPIC scan does. Deriving it from
    ``source_dir`` (rather than the module-level ``REPO_ROOT``) keeps the two
    sources aligned and lets tests that point ``EPIC_DIR`` at a tmp repo isolate
    package discovery too (a tmp repo with no ``common/`` yields no package ACs).
    """
    parts = source_dir.resolve().parts
    if len(parts) >= 2 and parts[-2:] == ("docs", "project"):
        return source_dir.resolve().parents[1]
    return source_dir.resolve()


def _ac_record_field(call: ast.Call, field: str) -> str | None:
    """Return the literal string value of an ``ACRecord(...)`` keyword, or None.

    Reads a keyword argument from an ``ACRecord(...)`` AST call node, returning
    its value only when it is a string constant or a parenthesised concatenation
    of string constants (the implicit ``("a" "b")`` form the contracts use).
    Non-literal values (unlikely for these fields) yield ``None``.
    """
    for kw in call.keywords:
        if kw.arg != field:
            continue
        node = kw.value
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value
        # Implicit string concatenation parses as nested BinOp/JoinedStr-free
        # Constants under ``ast.Constant`` only when adjacent literals; CPython
        # folds ``("a" "b")`` into a single Constant, so the branch above covers
        # it. Anything else (a Name, an f-string) is treated as absent.
    return None


def _roadmap_acs_from_contract(contract_path: Path) -> list[dict]:
    """Statically read a contract's ``roadmap`` ``ACRecord(...)`` entries.

    Parses ``common/<pkg>/contract.py`` with :mod:`ast` (no import, so no
    pydantic/governance dependency — this runs in every tooling environment) and
    returns one dict per ``ACRecord`` in the ``roadmap=[...]`` list, with its
    ``id``/``statement``/``tier``/``proof_kind`` literals.
    """
    tree = ast.parse(contract_path.read_text(encoding="utf-8"))
    records: list[dict] = []
    for node in ast.walk(tree):
        # The single ``CONTRACT = PackageContract(...)`` assignment; find its
        # ``roadmap=[...]`` keyword and read each ``ACRecord(...)`` element.
        if not (
            isinstance(node, ast.Call) and _call_name(node.func) == "PackageContract"
        ):
            continue
        for kw in node.keywords:
            if kw.arg != "roadmap" or not isinstance(kw.value, (ast.List, ast.Tuple)):
                continue
            for elt in kw.value.elts:
                if not (
                    isinstance(elt, ast.Call) and _call_name(elt.func) == "ACRecord"
                ):
                    continue
                ac_id = _ac_record_field(elt, "id")
                if not ac_id:
                    continue
                records.append(
                    {
                        "id": ac_id,
                        "statement": _ac_record_field(elt, "statement") or "",
                        "tier": _ac_record_field(elt, "tier"),
                        "proof_kind": _ac_record_field(elt, "proof_kind"),
                    }
                )
    return records


def _call_name(func: ast.expr) -> str | None:
    """Return the bare callee name of an ``ast.Call`` func (``Name`` or attr)."""
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def _package_roadmap_acs(source_dir: Path) -> dict[str, dict]:
    """Source ACs from every ``<root>/common/<pkg>/contract.py`` ``roadmap``.

    Each ``ACRecord`` becomes a registry entry keyed by its AC id, with the same
    shape an EPIC-table row produces: ``epic`` (parsed from the AC id),
    ``epic_name`` (from :data:`EPIC_NAMES` or the ``epic-NNN`` fallback),
    ``description``, ``mandatory=True``, and — when the record carries a
    ``tier`` — that tier plus its ``proof_kind`` (explicit, else the tier's
    canonical kind), exactly as the tier/proof markers did in an EPIC table.

    Read **statically** (AST), so this needs no pydantic/governance import and
    yields the SAME ACs in every tooling environment (no asymmetry, no silent
    drop): the heavy governance gate still validates the contracts elsewhere.
    """
    repo_root = _repo_root_for(source_dir)
    acs: dict[str, dict] = {}
    for contract_path in sorted(repo_root.glob("common/*/contract.py")):
        for record in _roadmap_acs_from_contract(contract_path):
            ac_id = record["id"]
            match = AC_PATTERN.fullmatch(ac_id)
            if not match:
                continue
            ac_epic = int(match.group(2))
            entry: dict = {
                "epic": ac_epic,
                "epic_name": EPIC_NAMES.get(ac_epic, f"epic-{ac_epic:03d}"),
                "description": _clean_description(record["statement"]),
                "mandatory": True,
            }
            tier = record["tier"]
            if tier:
                entry["tier"] = tier
                entry["proof_kind"] = record["proof_kind"] or _default_proof_for_tier(
                    tier
                )
            acs[ac_id] = entry
    return acs


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
            ac_id, ac_epic, desc, tier, proof_kind = definition
            if ac_id in all_acs:
                continue

            existing = existing_acs.get(ac_id, {})
            entry = {
                "epic": int(existing.get("epic", ac_epic)),
                "epic_name": existing.get(
                    "epic_name", EPIC_NAMES.get(ac_epic, f"epic-{ac_epic:03d}")
                ),
                "description": existing.get("description", desc),
                "mandatory": existing.get("mandatory", True),
            }
            # Tier is an attribute of the AC's behavior; the definition-site
            # marker is authoritative, falling back to any tier carried by an
            # existing/override entry. ACs with no declared tier stay untagged
            # (the ratchet gate tracks that debt).
            ac_tier = tier or existing.get("tier")
            if ac_tier:
                entry["tier"] = ac_tier
                # The proof KIND that this AC's tests provide. An explicit
                # {proof:KIND} marker wins; otherwise it falls back to an
                # existing/override value, then to the tier's canonical kind so
                # the registry value is always a kind the tier->proof matrix
                # accepts. Only tier-tagged ACs carry a proof_kind (the gate
                # only enforces the matrix for tier-tagged ACs).
                entry["proof_kind"] = (
                    proof_kind
                    or existing.get("proof_kind")
                    or _default_proof_for_tier(ac_tier)
                )
            all_acs[ac_id] = entry

    # Additively fold in package-contract roadmap ACs (from the SAME repo root the
    # EPIC scan used). EPIC-table definitions win on id collision (kept for
    # back-compat), so this only ADDS ACs whose sole home is now a package
    # contract — it can never drop or shadow an EPIC-sourced AC.
    for ac_id, entry in _package_roadmap_acs(source_dir).items():
        all_acs.setdefault(ac_id, entry)

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
        output_path = OUTPUT_FEATURE
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
                "tier",
                "proof_kind",
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
        duplicate_defs, duplicate_headings = find_ac_collisions()
        if duplicate_defs or duplicate_headings:
            if duplicate_defs:
                details = "; ".join(
                    f"{ac_id} defined in {', '.join(sorted(set(files)))}"
                    for ac_id, files in sorted(
                        duplicate_defs.items(), key=lambda kv: sort_key(kv[0])
                    )
                )
                print(
                    "ERROR: AC IDs are defined more than once (the registry keeps the "
                    f"first and silently drops the rest): {details}",
                    file=sys.stderr,
                )
            if duplicate_headings:
                heads = "; ".join(
                    f"{key.split(':', 1)[1]} in {key.split(':', 1)[0]}"
                    for key in sorted(duplicate_headings)
                )
                print(
                    f"ERROR: duplicate AC group headings make the namespace ambiguous: {heads}",
                    file=sys.stderr,
                )
            return 1
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
