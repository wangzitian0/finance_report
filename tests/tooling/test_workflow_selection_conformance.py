"""Workflow pytest-selection conformance (EPIC-008 AC8.23, issue #1557).

Every junit-emitting pytest invocation in .github/workflows/*.yml must be
registered in matrix.WORKFLOW_PYTEST_CONTRACTS with its marker expression and
explicit paths — fail-closed in both directions. Marker expressions live once
in common/testing/matrix.py; workflows keep literal text proven equal here.
"""

from __future__ import annotations

import os
import re
from html import escape
from pathlib import Path
from types import SimpleNamespace

from common.audit.base import (
    TraceRecord,
    TraceResult,
    TraceTargetClass,
    VersionedTraceRef,
)
from common.testing import matrix
from common.testing.ac_proof import PROOF_ATTR, AcProof
from common.testing.check_pr_ci_evidence import _module_for, collect_executed
from common.testing.executed_proof import (
    record_executed_proof,
    register_executed_proof_consumer,
)

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / ".github" / "workflows"


def _joined_lines(text: str) -> list[str]:
    """Join backslash-continued lines so one invocation is one string."""
    lines: list[str] = []
    buffer = ""
    for raw in text.splitlines():
        line = raw.rstrip()
        if line.endswith("\\"):
            buffer += line[:-1] + " "
            continue
        lines.append(buffer + line)
        buffer = ""
    if buffer:
        lines.append(buffer)
    return lines


def _pytest_invocations() -> dict[str, list[str]]:
    """All junit-emitting pytest invocation lines per workflow file."""
    found: dict[str, list[str]] = {}
    for wf in sorted(WORKFLOWS.glob("*.yml")):
        rel = wf.relative_to(ROOT).as_posix()
        for line in _joined_lines(wf.read_text(encoding="utf-8")):
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            if re.search(r"\bpytest\b", stripped) and "--junit-xml=" in stripped:
                found.setdefault(rel, []).append(stripped)
    return found


def test_AC8_23_1_every_workflow_pytest_invocation_is_registered() -> None:
    """AC-testing.conformance.1: AC8.23.1: fail-closed both ways — no unregistered invocation, no
    contract without a live invocation."""
    invocations = _pytest_invocations()
    anchors = [(c, c.anchor) for c in matrix.WORKFLOW_PYTEST_CONTRACTS]

    matched_lines: set[str] = set()
    for contract, anchor in anchors:
        lines = [
            line for line in invocations.get(contract.workflow, []) if anchor in line
        ]
        assert len(lines) == 1, (
            f"contract {contract.stage!r}: expected exactly one invocation with "
            f"anchor {anchor!r} in {contract.workflow}, found {len(lines)}"
        )
        matched_lines.add(lines[0])

    for workflow, lines in invocations.items():
        for line in lines:
            assert line in matched_lines, (
                f"UNREGISTERED pytest invocation in {workflow}: {line!r}. "
                "Register it in matrix.WORKFLOW_PYTEST_CONTRACTS (the selection "
                "SSOT) before adding it to a workflow."
            )


def _selection_tokens(line: str) -> set[str]:
    """Extract the test-selection tokens from a pytest invocation line:
    literal test paths/nodes plus test-array shell expansions."""
    tokens = set()
    for token in line.split():
        if token.startswith("tests/"):
            tokens.add(token)
        elif token.startswith('"${') and "TESTS" in token:
            tokens.add(token)
    return tokens


def test_AC8_23_2_registered_invocations_match_matrix_selection() -> None:
    """AC-testing.conformance.2: AC8.23.2: each invocation's -m expression and its FULL set of
    selection tokens equal the matrix contract — an extra path argument
    added to a workflow without updating the SSOT fails too."""
    invocations = _pytest_invocations()
    for contract in matrix.WORKFLOW_PYTEST_CONTRACTS:
        line = next(
            line for line in invocations[contract.workflow] if contract.anchor in line
        )
        if contract.marker is not None:
            assert f'-m "{contract.marker}"' in line, (
                f"{contract.stage}: marker drifted from matrix constant.\n"
                f'  expected: -m "{contract.marker}"\n  line: {line}'
            )
        assert _selection_tokens(line) == set(contract.paths), (
            f"{contract.stage}: selection tokens drifted from the matrix "
            f"contract.\n  expected: {sorted(contract.paths)}\n"
            f"  found: {sorted(_selection_tokens(line))}\n  line: {line}"
        )


def test_AC8_23_3_staging_ai_ocr_corpus_aligns_with_matrix_llm_rows() -> None:
    """AC-testing.conformance.3: AC8.23.3: the staging AI/OCR corpus (derived from @ac_proof metadata)
    and the matrix llm rows describe the same set of provider-dependent
    specs — the two derivations cannot drift apart silently."""
    from common.testing.staging_ai_ocr_gate_contract import gate_files

    corpus = set(gate_files())
    llm_rows = {
        row.file for row in matrix.E2E_ROWS if matrix.NEEDS_LLM_PROVIDER in row.needs
    }
    # The connectivity probe runs in deploy.yml's dedicated provider gate, not
    # the corpus; everything else llm-dependent must be corpus-covered.
    connectivity = {"tests/e2e/test_ai_provider_connectivity.py"}
    assert corpus <= llm_rows, f"corpus files missing llm rows: {corpus - llm_rows}"
    assert llm_rows - corpus == connectivity, (
        "llm-marked matrix rows not covered by the staging corpus (and not the "
        f"connectivity probe): {llm_rows - corpus - connectivity}"
    )


def test_AC8_23_4_pr_ci_evidence_reconciliation_gate(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """AC-testing.conformance.4: AC8.23.4: a behavioral pr_ci proof absent from PR junit evidence fails
    the reconciliation gate; present proofs pass; skipped-only warns."""
    from common.testing.check_pr_ci_evidence import run_check

    # Real reconciliation over a synthetic junit containing every scoped
    # proof: build the junit from the proof graph itself, then drop one.
    from common.testing.ac_graph import build_proofs_only
    from common.testing.generate_critical_proof_matrix import build_matrix_from_graph

    proofs = [
        p
        for p in build_matrix_from_graph(build_proofs_only()).get("proofs", [])
        if p.get("scope") == "behavioral"
        and p.get("ci_tier") == "pr_ci"
        and matrix.classify_stage(p.get("file", "")) in matrix.PR_EVIDENCE_STAGES
    ]
    assert proofs, "expected at least one scoped pr_ci proof in the repo"
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("GITHUB_REPOSITORY", "wangzitian0/finance_report")
    monkeypatch.setenv("GITHUB_SHA", "a" * 40)
    monkeypatch.setenv("GITHUB_RUN_ID", "123")
    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", "2")

    def junit_for(subset: list[dict]) -> Path:
        cases = []
        for proof in subset:
            properties = ""
            if proof.get("scenario_id"):
                test = lambda: None  # noqa: E731
                setattr(
                    test,
                    PROOF_ATTR,
                    AcProof(
                        proof_id=proof["id"],
                        ac_ids=tuple(proof["ac_ids"]),
                        stage=proof["stage"],
                        task_category=proof["task_category"],
                        scope=proof["scope"],
                        ci_tier=proof["ci_tier"],
                        trust_mode=proof.get("trust_mode", ""),
                        source_classes=tuple(proof.get("source_classes", ())),
                        issue=proof.get("issue", ""),
                        scenario_id=proof["scenario_id"],
                        oracle_kind=proof["oracle_kind"],
                        required_observation_kind=proof.get(
                            "required_observation_kind", ""
                        ),
                    ),
                )
                item = SimpleNamespace(
                    obj=test,
                    nodeid=f"{proof['file']}::{proof['test']}",
                    user_properties=[],
                )
                required_kind = proof.get("required_observation_kind", "")
                if required_kind:

                    def required_observation(record, kind=required_kind):
                        return TraceRecord.observation(
                            scope=record.scope,
                            target=record.target,
                            target_class=TraceTargetClass.GENERAL,
                            assertion=VersionedTraceRef(
                                kind,
                                record.assertion.id,
                                record.assertion.version,
                            ),
                            authority=record.authority,
                            result=TraceResult.PASS,
                            execution_id=record.execution_id,
                            evidence_manifest_digest=record.evidence_manifest_digest,
                            occurred_at=record.occurred_at,
                            score=None,
                            reason_code="required_observation_passed",
                        )

                    register_executed_proof_consumer(item, required_observation)
                record_executed_proof(
                    item,
                    SimpleNamespace(when="call", passed=True, user_properties=[]),
                    environ=os.environ,
                )
                properties = (
                    "<properties>"
                    + "".join(
                        f'<property name="{escape(name)}" value="{escape(value)}"/>'
                        for name, value in item.user_properties
                    )
                    + "</properties>"
                )
            cases.append(
                f'<testcase classname="{_module_for(proof["file"])}" '
                f'name="{proof["test"]}" time="0.1">{properties}</testcase>'
            )
        path = tmp_path / f"junit-{len(subset)}.xml"
        path.write_text(
            f'<testsuite name="s" tests="{len(subset)}">{"".join(cases)}</testsuite>',
            encoding="utf-8",
        )
        return path

    assert run_check([junit_for(proofs)]) == 0
    assert run_check([junit_for(proofs[1:])]) == 1

    # Skipped-only is a hard fail (#1558): a pr_ci proof that only ever skips
    # pre-merge is not executing its promise.
    skipped = tmp_path / "skipped.xml"
    scenario = next(proof for proof in proofs if proof.get("scenario_id"))
    without_scenario = [proof for proof in proofs if proof is not scenario]
    skipped.write_text(
        f'<testsuite name="s" tests="1"><testcase classname="{_module_for(scenario["file"])}"'
        f' name="{scenario["test"]}"><skipped/></testcase></testsuite>',
        encoding="utf-8",
    )
    import common.testing.check_pr_ci_evidence as evidence_gate

    def reject_match_for_nonexecuted_proof(*args, **kwargs):
        raise AssertionError("a skipped proof must not enter TraceRecord validation")

    with monkeypatch.context() as skipped_gate:
        skipped_gate.setattr(
            evidence_gate,
            "_has_exact_executed_proof",
            reject_match_for_nonexecuted_proof,
        )
        assert run_check([junit_for(without_scenario), skipped]) == 1
    # ...but a skip in one shard with a real run in another still passes.
    assert run_check([junit_for(proofs), skipped]) == 0


def test_AC8_23_4_junit_parsing_handles_params_and_classes(tmp_path: Path) -> None:
    """AC8.23.4: parametrized ids and class-nested testcases still count."""
    junit = tmp_path / "j.xml"
    junit.write_text(
        '<testsuite name="s" tests="2">'
        '<testcase classname="tests.x.test_mod.TestK" name="test_a[case-1]"/>'
        '<testcase classname="tests.x.test_mod" name="test_b"/>'
        "</testsuite>",
        encoding="utf-8",
    )
    executed = collect_executed([junit])
    assert ("tests.x.test_mod.TestK", "test_a") in executed
    assert ("tests.x.test_mod", "test_b") in executed
