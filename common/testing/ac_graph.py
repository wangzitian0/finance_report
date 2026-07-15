#!/usr/bin/env python3
"""One AC-keyed graph model for every cross-cutting proof/vision/status view.

The repo accumulated several committed, globally-aggregated "index" files that
were each a different PROJECTION of the SAME underlying graph::

    EPIC -> AC -> Proof (-> behavioral score, -> vision item)

Because each projection was committed-materialized and CI byte-compared it,
EVERY PR that touched ANY AC rewrote them, producing constant merge conflicts.
This module replaces that with ONE in-memory model:

    build_ac_graph(repo_root) -> AcGraph

``AcGraph`` is keyed by AC id. Every concern is just additional FIELDS on the
one AC key:

* AC nodes (id, epic, epic_name, description, mandatory) come from the EPIC docs
  via the registry loader (``build_registry_entries``).
* proof edges come from the ``@ac_proof(...)`` decorators co-located on tests
  (reusing the static AST scan from ``generate_critical_proof_matrix``).
* score/floor per AC comes from ``common/testing/data/ac-score-baseline.jsonl``.
* vision items + their required ACs/proofs come from ``vision.md`` (reusing
  ``generate_vision_proof_matrix``'s parsing).
* macro outcomes come from the small hand-maintained
  ``common/testing/data/critical-proof-outcomes.yaml``.

The aggregate views (critical-proof matrix, vision-proof matrix, README EPIC
status) are DERIVED on demand by the ``render_*`` projections in the existing
generators that call ``build_ac_graph()``. None of those views is
committed-materialized; only the sharded sources (EPIC docs, ``@ac_proof``
decorators, vision.md, outcomes YAML) and the single persisted ratchet
(``ac-score-baseline.jsonl``, union-merge) live on disk, so two PRs touching
DIFFERENT ACs never collide on a common committed aggregate file.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from common.testing.ac_score_baseline_format import load_jsonl
from common.testing.ac_traceability_refs import AC_PATTERN, classify_reference_file
from common.meta.extension.generate_ac_registry import build_registry_entries
from common.testing.generate_critical_proof_matrix import (
    CollectedProof,
    collect_proofs,
)
from common.testing.ac_proof_execution import normalize_proof_execution
from common.testing.test_surface import default_ac_test_dirs

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTCOMES = (
    REPO_ROOT / "common" / "testing" / "data" / "critical-proof-outcomes.yaml"
)
DEFAULT_BASELINE = REPO_ROOT / "common" / "testing" / "data" / "ac-score-baseline.jsonl"

EXCLUDED_DIRS = {"node_modules", "__pycache__", ".next", "dist", ".cache"}
TEST_FILE_SUFFIXES = ("_test.py", ".test.ts", ".test.tsx", ".spec.ts", ".spec.tsx")


@dataclass(frozen=True)
class AcNode:
    """One acceptance criterion plus every concern projected onto its key."""

    id: str
    epic: int
    epic_name: str
    description: str
    mandatory: bool
    # Real (non-stub, non-placeholder) test files that reference this AC id.
    real_test_files: tuple[str, ...] = ()
    # ``@ac_proof`` proof ids that name this AC id.
    proof_ids: tuple[str, ...] = ()
    # Persisted ratchet floor for this AC, if any.
    score: float | None = None


@dataclass(frozen=True)
class ProofEdge:
    """One ``@ac_proof`` declaration, the proof side of the AC graph."""

    proof_id: str
    file: str
    test: str
    ac_ids: tuple[str, ...]
    stage: str
    task_category: str
    ci_tier: str
    scope: str
    required_markers: tuple[str, ...]
    fields: dict[str, Any]


@dataclass(frozen=True)
class VisionItem:
    """One vision.md anchor and the ACs/proofs that back it."""

    anchor: str
    label: str
    owner_epics: tuple[str, ...]
    ac_ids: tuple[str, ...]


@dataclass(frozen=True)
class Outcome:
    """One macro README -> EPIC -> E2E outcome from the outcomes source file."""

    id: str
    proof_ids: tuple[str, ...]
    raw: dict[str, Any]


@dataclass
class AcGraph:
    """The single AC-keyed graph, built once from the sharded sources."""

    repo_root: Path
    nodes: dict[str, AcNode]
    proofs: list[ProofEdge]
    vision_items: list[VisionItem]
    outcomes: list[Outcome]
    outcomes_doc: dict[str, Any] = field(default_factory=dict)

    def proof_by_id(self, proof_id: str) -> ProofEdge | None:
        for proof in self.proofs:
            if proof.proof_id == proof_id:
                return proof
        return None


def _is_test_file(name: str) -> bool:
    return name.startswith("test_") or name.endswith(TEST_FILE_SUFFIXES)


def _iter_test_files(repo_root: Path) -> list[Path]:
    found: list[Path] = []
    for base in default_ac_test_dirs(repo_root):
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if not path.is_file():
                continue
            if any(part in EXCLUDED_DIRS for part in path.parts):
                continue
            if _is_test_file(path.name):
                found.append(path)
    return sorted(found)


def _collect_real_refs(repo_root: Path) -> dict[str, set[str]]:
    """Return ``{ac_id: {test_file, ...}}`` for real (non-stub/placeholder) refs.

    Single authoritative scan of the AC test universe shared by every
    projection, so all views agree on which tests exist (no per-view drift).
    """
    refs: dict[str, set[str]] = {}
    for path in _iter_test_files(repo_root):
        try:
            content = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if classify_reference_file(path, content) != "real":
            continue
        rel = path.relative_to(repo_root).as_posix()
        for match in AC_PATTERN.finditer(content):
            refs.setdefault(match.group(0), set()).add(rel)
    return refs


def _proof_edges(proofs: list[CollectedProof]) -> list[ProofEdge]:
    edges: list[ProofEdge] = []
    for proof in proofs:
        fields = proof.fields
        stage, task_category = normalize_proof_execution(fields)
        edges.append(
            ProofEdge(
                proof_id=proof.proof_id,
                file=proof.file,
                test=proof.test,
                ac_ids=tuple(str(ac_id) for ac_id in fields.get("ac_ids", [])),
                stage=stage,
                task_category=task_category,
                ci_tier=str(fields.get("ci_tier", "")),
                scope=str(fields.get("scope", "")),
                required_markers=tuple(
                    str(marker) for marker in fields.get("required_markers", [])
                ),
                fields=fields,
            )
        )
    edges.sort(key=lambda edge: edge.proof_id)
    return edges


def _vision_items(repo_root: Path) -> list[VisionItem]:
    # Reuse the vision matrix parsing (vision.md anchors + EPIC anchor map +
    # registries). Imported lazily so the heavy vision build only runs when the
    # graph is actually constructed.
    from common.testing import generate_vision_proof_matrix as vision

    # build_matrix is memoized per repo_root; clear so we never reuse a stale
    # process cache, and pass THIS graph's repo_root so vision.md/EPIC/registry
    # parsing is sourced from the SAME checkout as the rest of the graph (a
    # non-default root — temp worktree/tests — must not read the real repo).
    vision.build_matrix.cache_clear()
    matrix = vision.build_matrix(repo_root)
    items: list[VisionItem] = []
    for node in matrix.get("vision_nodes", []):
        items.append(
            VisionItem(
                anchor=str(node["anchor"]),
                label=str(node.get("label", "")),
                owner_epics=tuple(str(e) for e in node.get("owner_epics", [])),
                ac_ids=tuple(str(ac["id"]) for ac in node.get("acs", [])),
            )
        )
    return items


def _outcomes(outcomes_doc: dict[str, Any]) -> list[Outcome]:
    outcomes: list[Outcome] = []
    for raw in outcomes_doc.get("outcomes", []) or []:
        if not isinstance(raw, dict):
            continue
        outcomes.append(
            Outcome(
                id=str(raw.get("id", "")),
                proof_ids=tuple(str(pid) for pid in raw.get("proof_ids", []) or []),
                raw=raw,
            )
        )
    return outcomes


def _load_scores(baseline_path: Path) -> dict[str, float]:
    if not baseline_path.exists():
        return {}
    payload = load_jsonl(baseline_path)
    acs = payload.get("acs", {})
    scores: dict[str, float] = {}
    if isinstance(acs, dict):
        for ac_id, record in acs.items():
            try:
                scores[str(ac_id)] = float(record.get("score", 0.0))
            except (TypeError, ValueError):
                continue
    return scores


@dataclass(frozen=True)
class ProofsOnlyGraph:
    """The minimal proofs+outcomes slice of the AC graph.

    Carries only what the critical-proof matrix payload needs: the
    ``@ac_proof`` proof edges and the hand-maintained outcomes doc. It exposes
    the same ``proofs`` / ``outcomes_doc`` attributes as :class:`AcGraph`, so
    ``generate_critical_proof_matrix.build_matrix_from_graph`` consumes either
    one interchangeably and yields the identical matrix payload. Use it when the
    AC-reference scan and the vision build are pure overhead (the staging gate
    and the critical-proof validator).
    """

    repo_root: Path
    proofs: list[ProofEdge]
    outcomes_doc: dict[str, Any]


def build_proofs_only(
    repo_root: Path = REPO_ROOT,
    *,
    outcomes_path: Path | None = None,
) -> ProofsOnlyGraph:
    """Build only the proofs + outcomes slice — no AC-ref scan, no vision build.

    The lightweight path: a pure ``@ac_proof`` AST scan plus the hand-maintained
    ``critical-proof-outcomes.yaml``. It deliberately skips the AC test-universe
    reference scan and the heavy vision-matrix build that ``build_ac_graph``
    performs, because the critical-proof matrix payload depends on neither. The
    ``proofs``/``outcomes_doc`` it carries are byte-for-byte what ``build_ac_graph``
    would have produced, so any matrix derived from it is identical — just faster
    to start up.
    """
    repo_root = repo_root.resolve()
    outcomes_path = outcomes_path or (
        repo_root / DEFAULT_OUTCOMES.relative_to(REPO_ROOT)
    )

    proofs = _proof_edges(collect_proofs(repo_root))

    outcomes_doc = yaml.safe_load(outcomes_path.read_text(encoding="utf-8")) or {}
    if not isinstance(outcomes_doc, dict):
        outcomes_doc = {}

    return ProofsOnlyGraph(
        repo_root=repo_root, proofs=proofs, outcomes_doc=outcomes_doc
    )


def build_ac_graph(
    repo_root: Path = REPO_ROOT,
    *,
    outcomes_path: Path | None = None,
    baseline_path: Path | None = None,
) -> AcGraph:
    """Build the single AC-keyed graph from the sharded sources.

    ONE parse, one model: the AC test universe is scanned once, the
    ``@ac_proof`` decorators are collected once, and every projection
    (critical-proof matrix, vision matrix, EPIC status, traceability) reads from
    this materialized model instead of re-reading the sources independently.
    """
    repo_root = repo_root.resolve()
    outcomes_path = outcomes_path or (
        repo_root / DEFAULT_OUTCOMES.relative_to(REPO_ROOT)
    )
    baseline_path = baseline_path or (
        repo_root / DEFAULT_BASELINE.relative_to(REPO_ROOT)
    )

    # AC nodes from EPIC docs (via the registry loader) + overrides.
    registry = build_registry_entries(epic_source=repo_root / "docs" / "project")

    # Proof edges from co-located @ac_proof decorators (static AST scan).
    collected = collect_proofs(repo_root)
    proofs = _proof_edges(collected)
    proofs_by_ac: dict[str, list[str]] = {}
    for proof in proofs:
        for ac_id in proof.ac_ids:
            proofs_by_ac.setdefault(ac_id, []).append(proof.proof_id)

    # Real test references (one shared scan).
    real_refs = _collect_real_refs(repo_root)

    # Persisted ratchet floors.
    scores = _load_scores(baseline_path)

    nodes: dict[str, AcNode] = {}
    for ac_id, entry in registry.items():
        nodes[ac_id] = AcNode(
            id=ac_id,
            epic=int(entry.get("epic", 0)),
            epic_name=str(entry.get("epic_name", "")),
            description=str(entry.get("description", "")),
            mandatory=bool(entry.get("mandatory", True)),
            real_test_files=tuple(sorted(real_refs.get(ac_id, set()))),
            proof_ids=tuple(sorted(proofs_by_ac.get(ac_id, []))),
            score=scores.get(ac_id),
        )

    outcomes_doc = yaml.safe_load(outcomes_path.read_text(encoding="utf-8")) or {}
    if not isinstance(outcomes_doc, dict):
        outcomes_doc = {}

    return AcGraph(
        repo_root=repo_root,
        nodes=nodes,
        proofs=proofs,
        vision_items=_vision_items(repo_root),
        outcomes=_outcomes(outcomes_doc),
        outcomes_doc=outcomes_doc,
    )
