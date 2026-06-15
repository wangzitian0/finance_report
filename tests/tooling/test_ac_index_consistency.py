"""AC8.13.139: one AC-keyed graph, derived views, one consistency gate.

The cross-cutting proof/vision/status indexes are unified onto ONE AC-keyed
graph (``common/ssot/ac_graph.py``). The critical-proof matrix, vision-proof
matrix, and README EPIC-status table are DERIVED on demand and never
committed-materialized, and ONE internal-consistency gate
(``tools/check_ac_index.py``) enforces no dangling/missing link — never a shifted
total.

These tests assert the gate PASSES on a consistent tree and FAILS on each of the
four dangling/missing cases (dangling vision item, ``@ac_proof`` pointing at a
missing test/AC, a mandatory AC with no proof, a ratchet regression), and that no
committed materialized matrix/vision/status file is required.
"""

from __future__ import annotations

import json
from pathlib import Path

from common.ssot import check_ac_index as gate, check_ac_score_baseline as ratchet
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
    assert gate.check_graph(_consistent_graph()) == []


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
    errors = gate.check_graph(graph)
    assert any("dangling" in e and "dangling vision" in e for e in errors), errors


def test_AC8_13_139_gate_fails_on_proof_missing_test_or_ac() -> None:
    """AC8.13.139: an @ac_proof must point at a real test AND real AC ids."""
    # (a) proof names an AC id that is not in the registry.
    graph = _consistent_graph()
    graph.proofs.append(_proof("p-bad-ac", ("AC9.9.9",), file=REAL_FILE, test=REAL_TEST))
    errors = gate.check_graph(graph)
    assert any("unknown AC id" in e and "AC9.9.9" in e for e in errors), errors

    # (b) proof names a test function that does not exist.
    graph2 = _consistent_graph()
    graph2.proofs.append(_proof("p-bad-test", ("AC8.13.139",), file=REAL_FILE, test="no_such_test_fn"))
    errors2 = gate.check_graph(graph2)
    assert any("does not resolve to a real test" in e for e in errors2), errors2


def test_AC8_13_139_gate_fails_on_mandatory_ac_without_proof() -> None:
    """AC8.13.139: a mandatory, active AC with no real test reference fails."""
    graph = _consistent_graph()
    graph.nodes["AC8.13.140"] = _ac("AC8.13.140", mandatory=True, has_test=False)
    errors = gate.check_graph(graph)
    assert any("AC8.13.140" in e and "no real test reference" in e for e in errors), errors

    # A deprecated (strikethrough) AC with no test is excluded, not a failure.
    graph2 = _consistent_graph()
    deprecated = AcNode(
        id="AC8.13.141",
        epic=8,
        epic_name="testing-strategy",
        description="~~retired criterion~~",
        mandatory=True,
        real_test_files=(),
        proof_ids=(),
        score=None,
    )
    graph2.nodes["AC8.13.141"] = deprecated
    assert all("AC8.13.141" not in e for e in gate.check_graph(graph2))


def test_AC8_13_139_gate_fails_on_macro_outcome_missing_proof() -> None:
    """AC8.13.139: a macro outcome's proof_ids must resolve to a declared proof."""
    graph = _consistent_graph()
    graph.outcomes.append(Outcome(id="o-bad", proof_ids=("no-such-proof",), raw={"id": "o-bad"}))
    errors = gate.check_graph(graph)
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
