"""AC8.13.139: one AC-keyed graph, derived views, exactly TWO gates.

The cross-cutting proof/vision/status indexes are unified onto ONE AC-keyed
graph (``common/ssot/ac_graph.py``). The critical-proof matrix, vision-proof
matrix, and README EPIC-status table are DERIVED on demand and never
committed-materialized, and the gate over that graph is exactly TWO gates:

* **Gate A — INTEGRITY (hard).** Every AC is managed (enumerated with a
  protection record — an all-empty record is valid) and there is no dangling
  reference: every ``@ac_proof`` resolves to a real test + real AC, every vision
  item with an owner EPIC backs an AC, every macro outcome's proof_ids resolve.
  The mandatory-AC traceability obligation is enforced by the folded CI-stage
  traceability check Gate A calls (``check_ac_traceability``), strictly stronger
  than a graph-level mirror. The per-edge-type error wording is preserved
  verbatim from the legacy checks.
* **Gate B — PROTECTION RATCHET (soft, monotonic, per type).** Part 1 is the
  per-AC behavioural-score floor (``ac-score-baseline.jsonl``, unchanged); part 2
  is the per-type COUNT floor (``protection-floor.json``): current count of
  mandatory active ACs at each type must be ``>=`` the committed floor. Adding
  protection raises the current count and passes WITHOUT editing the floor file;
  the floor is bumped only by the explicit ``--update-floor`` action. The default
  all-zero / missing floor is valid.

These tests assert Gate A PASSES on a consistent tree and FAILS on each
dangling/missing case (dangling vision item, ``@ac_proof`` pointing at a missing
test/AC, a mandatory AC with no proof, a dead macro outcome) with the SPECIFIC
message, that an all-empty protection record is still "managed", that Gate B's
count floor FAILS on a regression and PASSES (no regression) when protection is
added, that the default empty floor passes, that ``--update-floor`` raises floors,
and that no committed materialized matrix/vision/status file is required.
"""

from __future__ import annotations

import json
from pathlib import Path

from common.ssot import (
    check_ac_index as gate,
    check_ac_score_baseline as ratchet,
    protection,
)
from common.ssot.ac_graph import AcGraph, AcNode, Outcome, ProofEdge, VisionItem
from common.ssot.ac_score_baseline_format import write_jsonl

REPO_ROOT = Path(__file__).resolve().parents[2]

# A real test file + function that exists in this repo, so a proof edge that
# names it resolves to a real test (this very test module).
REAL_FILE = "tests/tooling/test_ac_index_consistency.py"
REAL_TEST = "test_AC8_13_139_gate_passes_on_consistent_tree"


def _ac(ac_id: str, *, mandatory: bool = True, has_test: bool = True) -> AcNode:
    return AcNode(
        id=ac_id,
        epic=int(ac_id[2:].split(".")[0]),
        epic_name="testing-strategy",
        description=f"{ac_id} description",
        mandatory=mandatory,
        real_test_files=(REAL_FILE,) if has_test else (),
        proof_ids=(),
        score=None,
    )


def _proof(proof_id: str, ac_ids: tuple[str, ...], *, file: str, test: str) -> ProofEdge:
    return ProofEdge(
        proof_id=proof_id,
        file=file,
        test=test,
        ac_ids=ac_ids,
        ci_tier="pr_ci",
        scope="behavioral",
        required_markers=(),
        fields={"id": proof_id, "ac_ids": list(ac_ids), "file": file, "test": test},
    )


def _consistent_graph() -> AcGraph:
    """A minimal but internally consistent graph the gate must accept."""
    nodes = {
        "AC8.13.139": _ac("AC8.13.139"),
        "AC8.13.99": _ac("AC8.13.99"),
    }
    proofs = [
        _proof("p-1", ("AC8.13.139",), file=REAL_FILE, test=REAL_TEST),
    ]
    vision = [
        VisionItem(
            anchor="axiom-a",
            label="Axiom A",
            owner_epics=("EPIC-008",),
            ac_ids=("AC8.13.139",),
        ),
        # Parked anchor with no owner EPIC: allowed, not a dangling promise.
        VisionItem(anchor="parked", label="Parked", owner_epics=(), ac_ids=()),
    ]
    outcomes = [Outcome(id="o-1", proof_ids=("p-1",), raw={"id": "o-1"})]
    return AcGraph(
        repo_root=REPO_ROOT,
        nodes=nodes,
        proofs=proofs,
        vision_items=vision,
        outcomes=outcomes,
        outcomes_doc={"outcomes": [{"id": "o-1", "proof_ids": ["p-1"]}]},
    )


def test_AC8_13_139_gate_passes_on_consistent_tree() -> None:
    """AC8.13.139: the gate reports no errors on a consistent graph."""
    assert gate.check_integrity(_consistent_graph()) == []


def test_AC8_13_139_gate_fails_on_dangling_vision_item() -> None:
    """AC8.13.139: a vision item owning an EPIC but backing no AC is dangling."""
    graph = _consistent_graph()
    graph.vision_items.append(
        VisionItem(
            anchor="dangling",
            label="Dangling promise",
            owner_epics=("EPIC-099",),
            ac_ids=(),
        )
    )
    errors = gate.check_integrity(graph)
    assert any("dangling" in e and "dangling vision" in e for e in errors), errors


def test_AC8_13_139_gate_fails_on_proof_missing_test_or_ac() -> None:
    """AC8.13.139: an @ac_proof must point at a real test AND real AC ids."""
    # (a) proof names an AC id that is not in the registry.
    graph = _consistent_graph()
    graph.proofs.append(_proof("p-bad-ac", ("AC9.9.9",), file=REAL_FILE, test=REAL_TEST))
    errors = gate.check_integrity(graph)
    assert any("unknown AC id" in e and "AC9.9.9" in e for e in errors), errors

    # (b) proof names a test function that does not exist.
    graph2 = _consistent_graph()
    graph2.proofs.append(_proof("p-bad-test", ("AC8.13.139",), file=REAL_FILE, test="no_such_test_fn"))
    errors2 = gate.check_integrity(graph2)
    assert any("does not resolve to a real test" in e for e in errors2), errors2


def test_AC8_13_139_gate_fails_on_mandatory_ac_without_proof(tmp_path) -> None:
    """AC8.13.139: a mandatory, active AC with no real test reference fails.

    This failure mode is owned by the folded CI-stage traceability check that
    Gate A calls (``check_ac_traceability.run_traceability`` +
    ``traceability_failure_messages``) — strictly stronger than the retired
    graph-level mirror — not by a graph obligation in ``check_integrity``. A
    deprecated (strikethrough) AC with no test is excluded, not a failure.
    """
    from common.ssot import check_ac_traceability as traceability

    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "ac_registry.yaml").write_text(
        "\n".join(
            [
                "version: '1.0'",
                "groups:",
                "  AC8:",
                "    AC8.13:",
                "      - id: AC8.13.140",
                "        epic: 8",
                "        epic_name: testing-strategy",
                "        description: active mandatory behavior",
                "        mandatory: true",
                "      - id: AC8.13.900",
                "        epic: 8",
                "        epic_name: testing-strategy",
                "        description: ~~retired criterion~~",
                "        mandatory: true",
                "",
            ]
        ),
        encoding="utf-8",
    )
    (docs / "infra_registry.yaml").write_text(
        "version: '1.0'\ngroups: {}\n", encoding="utf-8"
    )

    result = traceability.run_traceability(tmp_path)
    # The active mandatory AC with no reference is flagged missing...
    assert "AC8.13.140" in result.missing
    assert any(
        "have no test reference" in message
        for message in traceability.traceability_failure_messages(result)
    )
    # ...but the deprecated (strikethrough) one is excluded, not a failure.
    assert "AC8.13.900" not in result.missing


def test_AC8_13_139_gate_fails_on_macro_outcome_missing_proof() -> None:
    """AC8.13.139: a macro outcome's proof_ids must resolve to a declared proof."""
    graph = _consistent_graph()
    graph.outcomes.append(Outcome(id="o-bad", proof_ids=("no-such-proof",), raw={"id": "o-bad"}))
    errors = gate.check_integrity(graph)
    assert any("no-such-proof" in e and "does not resolve" in e for e in errors), errors


def test_AC8_13_139_gate_fails_on_ratchet_regression(tmp_path) -> None:
    """AC8.13.139: the persisted JSONL ratchet still catches a score regression."""
    baseline = tmp_path / "baseline.jsonl"
    write_jsonl(
        baseline,
        {
            "version": 1,
            "acs": {"AC1.1.1": {"score": 0.9, "metric": "m", "provenance": "deterministic"}},
        },
    )
    regressed = tmp_path / "current.json"
    regressed.write_text(
        json.dumps(
            {
                "version": 1,
                "acs": {
                    "AC1.1.1": {
                        "code": "pass",
                        "score": 0.4,
                        "metric": "m",
                        "provenance": "deterministic",
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    # Directly via the ratchet (the gate delegates to this exact code path).
    assert ratchet.main([str(regressed), "--baseline", str(baseline)]) == 1
    # And via the unified gate's --ratchet-current wiring.
    assert (
        gate.main(
            [
                "--ratchet-current",
                str(regressed),
                "--ratchet-baseline",
                str(baseline),
            ]
        )
        == 1
    )


# ---------------------------------------------------------------------------
# Gate A — INTEGRITY: "every AC is managed" (all-empty record is valid)
# ---------------------------------------------------------------------------


def test_AC8_13_140_every_ac_managed_with_empty_protection_passes() -> None:
    """AC8.13.140: an AC with an all-empty protection record is still 'managed'.

    Managed means present in the structure, NOT that it has any test. A node with
    no real test files, no proofs, and no score is a VALID managed record and must
    NOT make Gate A fail on the 'managed' obligation.
    """
    node = AcNode(
        id="AC8.13.200",
        epic=8,
        epic_name="testing-strategy",
        description="AC8.13.200 description",
        mandatory=False,  # non-mandatory so traceability does not require a test
        real_test_files=(),
        proof_ids=(),
        score=None,
    )
    graph = _consistent_graph()
    graph.nodes["AC8.13.200"] = node
    # 'managed' is satisfied (node enumerated); no integrity error mentions it.
    assert all("AC8.13.200" not in e for e in gate.check_integrity(graph))


# ---------------------------------------------------------------------------
# Gate B part 2 — per-type COUNT floor (monotonic, conflict-safe)
# ---------------------------------------------------------------------------


def _floor_graph() -> AcGraph:
    """A graph whose mandatory active ACs give known per-type counts.

    AC8.13.139 has a real test ref + a proof (p-1) + a score; AC8.13.99 has a real
    test ref only. So: has_real_ref=2, has_proof=1, has_score=1, has_mirror=0.
    """
    graph = _consistent_graph()
    scored = graph.nodes["AC8.13.139"]
    graph.nodes["AC8.13.139"] = AcNode(
        id=scored.id,
        epic=scored.epic,
        epic_name=scored.epic_name,
        description=scored.description,
        mandatory=scored.mandatory,
        real_test_files=scored.real_test_files,
        proof_ids=("p-1",),
        score=0.5,
    )
    return graph


def test_AC8_13_140_count_floor_default_empty_passes(tmp_path) -> None:
    """AC8.13.140: a missing/empty floor file is valid (brand-new repo passes)."""
    missing = tmp_path / "no-such-floor.json"
    result = protection.check_count_floor(_floor_graph(), missing)
    assert result.errors == []
    assert result.floor == dict.fromkeys(protection.PROTECTION_TYPES, 0)


def test_AC8_13_140_load_floor_rejects_malformed_value(tmp_path) -> None:
    """AC8.13.140: a malformed floor value is a hard error, not a silent zero.

    Silently coercing a bad floor to 0 would weaken the ratchet (regressions
    would pass unnoticed), so a present non-integer/negative value raises.
    """
    floor_file = tmp_path / "protection-floor.json"
    floor_file.write_text(
        json.dumps({"version": 1, "floor": {"has_proof": -3}}), encoding="utf-8"
    )
    try:
        protection.load_floor(floor_file)
    except ValueError:
        pass
    else:  # pragma: no cover - defensive
        raise AssertionError("load_floor must reject a negative floor value")

    # A MISSING type still defaults to 0 (new repo / newly added type passes).
    floor_file.write_text(json.dumps({"version": 1, "floor": {}}), encoding="utf-8")
    assert protection.load_floor(floor_file) == dict.fromkeys(protection.PROTECTION_TYPES, 0)


def test_AC8_13_140_write_floor_creates_missing_parent(tmp_path) -> None:
    """AC8.13.140: write_floor creates the parent directory if it is absent."""
    nested = tmp_path / "does" / "not" / "exist" / "protection-floor.json"
    protection.write_floor(nested, dict.fromkeys(protection.PROTECTION_TYPES, 0))
    assert nested.exists()
    assert protection.load_floor(nested) == dict.fromkeys(protection.PROTECTION_TYPES, 0)


def test_AC8_13_140_count_floor_fails_when_type_drops_below_floor(tmp_path) -> None:
    """AC8.13.140: a type whose current count drops below its floor is a failure."""
    floor_file = tmp_path / "protection-floor.json"
    graph = _floor_graph()  # has_proof current = 1
    # Commit a floor that requires MORE proofs than currently exist.
    protection.write_floor(floor_file, {"has_real_ref": 2, "has_proof": 5, "has_score": 1, "has_mirror": 0})
    result = protection.check_count_floor(graph, floor_file)
    assert any("has_proof" in e and "regressed" in e for e in result.errors), result.errors


def test_AC8_13_140_count_floor_passes_when_protection_added(tmp_path) -> None:
    """AC8.13.140: adding protection raises the current count; floor file untouched.

    The floor is captured at the current level, then more protection is added. The
    new (higher) current count still satisfies ``current >= floor`` WITHOUT editing
    the floor file — the conflict-safety guarantee.
    """
    floor_file = tmp_path / "protection-floor.json"
    graph = _floor_graph()
    # Lock the floor in at the current counts.
    protection.update_floor(graph, floor_file)
    locked = protection.load_floor(floor_file)
    before = floor_file.read_text(encoding="utf-8")

    # Now ADD protection: give AC8.13.99 a proof too (has_proof 1 -> 2).
    node99 = graph.nodes["AC8.13.99"]
    graph.nodes["AC8.13.99"] = AcNode(
        id=node99.id,
        epic=node99.epic,
        epic_name=node99.epic_name,
        description=node99.description,
        mandatory=node99.mandatory,
        real_test_files=node99.real_test_files,
        proof_ids=("p-1",),
        score=node99.score,
    )
    result = protection.check_count_floor(graph, floor_file)
    assert result.errors == []  # adding protection never regresses
    assert result.counts["has_proof"] == locked["has_proof"] + 1
    # The floor FILE was not touched by adding protection.
    assert floor_file.read_text(encoding="utf-8") == before


def test_AC8_13_140_update_floor_raises_floors(tmp_path) -> None:
    """AC8.13.140: --update-floor raises floors to current counts (never lowers)."""
    floor_file = tmp_path / "protection-floor.json"
    protection.write_floor(floor_file, dict.fromkeys(protection.PROTECTION_TYPES, 0))

    graph = _floor_graph()
    counts = protection.count_protection_types(graph)
    raised = protection.update_floor(graph, floor_file)
    assert raised == counts
    # Re-running with a LOWER current count never lowers the locked floor.
    poorer = _consistent_graph()  # has_proof current = 0 (p-1 not bound here? see below)
    # Strip all proofs so has_proof current drops to 0.
    poorer.proofs.clear()
    for ac_id, node in list(poorer.nodes.items()):
        poorer.nodes[ac_id] = AcNode(
            id=node.id,
            epic=node.epic,
            epic_name=node.epic_name,
            description=node.description,
            mandatory=node.mandatory,
            real_test_files=node.real_test_files,
            proof_ids=(),
            score=None,
        )
    not_lowered = protection.update_floor(poorer, floor_file)
    assert not_lowered["has_proof"] >= raised["has_proof"]


def test_AC8_13_139_no_committed_materialized_index_files() -> None:
    """AC8.13.139: no committed materialized matrix/vision/status file is required.

    The aggregate views are derived on demand; the previously-committed copies
    must be absent, and the README EPIC-status block must hold the stable pointer
    (no per-EPIC numbers), so nothing churns when an AC changes.
    """
    for relative in (
        "docs/ssot/critical-proof-matrix.yaml",
        "docs/ssot/vision-proof-matrix.yaml",
        "docs/reference/vision-proof-matrix.md",
    ):
        assert not (REPO_ROOT / relative).exists(), f"{relative} must NOT be committed-materialized any more"

    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    assert "<!-- BEGIN GENERATED: epic-status -->" in readme
    # The de-materialized pointer block carries no per-EPIC numeric table.
    assert "generate_epic_status.py --stdout" in readme
    assert "| EPIC-001 |" not in readme


def test_AC8_13_139_real_repo_graph_passes_the_gate() -> None:
    """AC8.13.139: the gate passes on the real repository graph."""
    assert gate.main(["--repo-root", str(REPO_ROOT)]) == 0


def test_AC8_13_135_protection_dashboard_separates_reference_from_behavioral(
    capsys,
) -> None:
    """AC8.13.135: the gate's PROTECTION dashboard reports per-type counts
    (has_real_ref vs has_proof/has_score), never conflating L1 reference
    presence with behavioral proof, so a passing gate cannot be misread as
    behavioral assurance. (Re-anchored from the retired standalone traceability
    report; the honest disclosure now lives in the two-gate dashboard.)"""
    import re

    assert gate.main(["--repo-root", str(REPO_ROOT)]) == 0
    out = capsys.readouterr().out
    assert "PROTECTION dashboard" in out
    # Each protection type is reported on its own line — L1 reference presence
    # is NOT merged into a single behavioral-coverage number.
    for ptype in ("has_real_ref", "has_proof", "has_score", "has_mirror"):
        assert ptype in out

    def _count(t: str) -> int:
        m = re.search(rf"{t}: current (\d+)", out)
        return int(m.group(1)) if m else -1

    # L1 reference count is reported separately from — and far exceeds — the
    # behavioral has_proof count: the disclosure that prevents the misread.
    assert _count("has_real_ref") > _count("has_proof")
