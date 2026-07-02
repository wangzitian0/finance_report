"""AC8.13.141: exactly TWO CI gates — the old standalone traceability and
critical-proof-matrix gate STEPS are retired and their logic is folded into
``check_ac_index``'s Gate A (INTEGRITY) by CALLING those modules as libraries.

The single AC-index gate entry point (`tools/check_ac_index.py`) now enforces:

* **Gate A — INTEGRITY**: the graph obligations PLUS, via ``check_repo_contracts``,
  the two folded contracts —
    1. CI-stage traceability (``check_ac_traceability.run_traceability`` +
       ``traceability_failure_messages``): a mandatory active AC's real test
       reference must land in a CI-required execution stage, with the
       placeholder-only / stub-only / unexecuted-only / missing classifications;
    2. the critical-proof contract (``check_critical_proof_matrix.validate_matrix_contract``):
       trust_mode / mirror / required_markers / scope / ci_tier / manual_gate
       evidence / macro-outcome shape.
* **Gate B — PROTECTION RATCHET** (unchanged).

These tests prove (a) the green tree passes identically through the consolidated
gate and the two old gates, (b) every old failure mode is still caught by the
consolidated gate with an equivalent, specific message, and (c) the old
standalone gate STEPS are gone from ci.yml while the job names / required
contexts are unchanged — so no protection was weakened.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from common.testing import (
    check_ac_index as gate,
    check_ac_traceability as traceability,
    check_critical_proof_matrix as cpm,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
CI_YML = REPO_ROOT / ".github" / "workflows" / "ci.yml"


# ---------------------------------------------------------------------------
# (a) Green-tree equivalence: old gates pass <=> consolidated gate passes.
# ---------------------------------------------------------------------------


def test_AC8_13_141_green_tree_old_gates_and_consolidated_agree() -> None:
    """AC8.13.141: on the real (green) tree the folded contracts report no errors.

    The two old gates pass on green main; the consolidated ``check_repo_contracts``
    runs the SAME library code and therefore must also report zero errors, and the
    one-entry gate exits 0.
    """
    # The folded repo contracts (traceability stage-enforcement + critical-proof
    # matrix) — the exact code the old standalone gates ran — report nothing.
    assert gate.check_repo_contracts(REPO_ROOT) == []
    # And the single AC-index gate entry point passes end to end.
    assert gate.main(["--repo-root", str(REPO_ROOT)]) == 0


def test_AC8_13_141_old_traceability_library_passes_on_green_tree() -> None:
    """AC8.13.141: the old traceability module still passes as a library."""
    result = traceability.run_traceability(REPO_ROOT)
    assert traceability.traceability_failure_messages(result) == []


def test_AC8_13_141_old_critical_proof_library_passes_on_green_tree() -> None:
    """AC8.13.141: the old critical-proof module still passes as a library."""
    assert cpm.validate_matrix_contract(REPO_ROOT).errors == []


# ---------------------------------------------------------------------------
# (b1) Traceability stage-enforcement: each old failure mode is still caught
#      by the consolidated gate, with the verbatim TRACEABILITY GATE message.
# ---------------------------------------------------------------------------


def _write_traceability_repo(
    repo_root: Path,
    *,
    test_rel: str,
    test_body: str,
    ci_required: bool,
) -> None:
    """Lay down a minimal repo: one mandatory AC + one referencing test file.

    ``test_rel`` is the test path relative to repo root; ``ci_required`` controls
    whether the execution matrix marks that path as a CI-required stage.
    """
    docs = repo_root / "docs"
    (docs / "project").mkdir(parents=True, exist_ok=True)
    (docs / "ac_registry.yaml").write_text(
        """
version: '1.0'
groups:
  AC8:
    AC8.13:
      - id: AC8.13.500
        epic: 8
        epic_name: testing-strategy
        description: folded traceability fixture AC
        mandatory: true
""".strip()
        + "\n",
        encoding="utf-8",
    )
    (docs / "infra_registry.yaml").write_text(
        "version: '1.0'\ngroups: {}\n", encoding="utf-8"
    )
    # Execution matrix: classify the test path with the requested ci_required.
    stage_dir = str(Path(test_rel).parent) + "/"
    (docs / "ssot").mkdir(parents=True, exist_ok=True)
    (docs / "ssot" / "test-execution-matrix.yaml").write_text(
        yaml.safe_dump(
            {
                "rules": [
                    {
                        "path": stage_dir,
                        "stage": "fixture_stage",
                        "ci_required": ci_required,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    test_path = repo_root / test_rel
    test_path.parent.mkdir(parents=True, exist_ok=True)
    test_path.write_text(test_body, encoding="utf-8")


def _consolidated_traceability_errors(repo_root: Path) -> list[str]:
    """The traceability half of the folded Gate A, anchored at repo_root."""
    return traceability.traceability_failure_messages(
        traceability.run_traceability(repo_root)
    )


def test_AC8_13_141_unexecuted_only_is_caught(tmp_path: Path) -> None:
    """AC8.13.141: a real ref ONLY in a non-CI-required stage is caught (folded)."""
    _write_traceability_repo(
        tmp_path,
        test_rel="apps/backend/tests/e2e/test_fixture.py",
        test_body='def test_x():\n    """AC8.13.500: real behavior."""\n    assert 1 == 1\n',
        ci_required=False,
    )
    errors = _consolidated_traceability_errors(tmp_path)
    assert any(
        "real references only in non-CI-required stages" in e for e in errors
    ), errors


def test_AC8_13_141_placeholder_only_is_caught(tmp_path: Path) -> None:
    """AC8.13.141: an AC covered only by placeholder assertions is caught (folded)."""
    _write_traceability_repo(
        tmp_path,
        test_rel="tests/tooling/test_fixture.py",
        # pytest.skip with an AC ref and no behavioral token => placeholder.
        test_body='import pytest\n\ndef test_x():\n    """AC8.13.500: placeholder."""\n    pytest.skip("todo")\n',
        ci_required=True,
    )
    errors = _consolidated_traceability_errors(tmp_path)
    assert any(
        "covered only by placeholder assertions" in e for e in errors
    ), errors


def test_AC8_13_141_stub_only_is_caught(tmp_path: Path) -> None:
    """AC8.13.141: an AC covered only by an _ac_stubs reference is caught (folded)."""
    _write_traceability_repo(
        tmp_path,
        test_rel="tests/tooling/_ac_stubs/test_fixture.py",
        test_body='# AC8.13.500 generated stub\n',
        ci_required=True,
    )
    errors = _consolidated_traceability_errors(tmp_path)
    assert any("covered only by _ac_stubs" in e for e in errors), errors


def test_AC8_13_141_missing_is_caught(tmp_path: Path) -> None:
    """AC8.13.141: a mandatory AC with no test reference at all is caught (folded)."""
    _write_traceability_repo(
        tmp_path,
        test_rel="tests/tooling/test_fixture.py",
        test_body='def test_x():\n    """No AC reference here."""\n    assert True\n',
        ci_required=True,
    )
    errors = _consolidated_traceability_errors(tmp_path)
    assert any("have no test reference" in e for e in errors), errors


# ---------------------------------------------------------------------------
# (b2) Critical-proof contract: each old failure mode is still caught by the
#      same code the fold calls (validate_matrix / validate_matrix_contract),
#      and the consolidated gate surfaces those errors.
# ---------------------------------------------------------------------------


def _cpm_registry(repo_root: Path) -> None:
    docs = repo_root / "docs"
    (docs / "project").mkdir(parents=True, exist_ok=True)
    (docs / "ac_registry.yaml").write_text(
        """
version: '1.0'
groups:
  AC8:
    AC8.13:
      - id: AC8.13.1
        epic: 8
        epic_name: testing-strategy
        description: core proof
        mandatory: true
""".strip()
        + "\n",
        encoding="utf-8",
    )
    (docs / "infra_registry.yaml").write_text(
        "version: '1.0'\ngroups: {}\n", encoding="utf-8"
    )


def test_AC8_13_141_critical_proof_invalid_trust_mode_caught(tmp_path: Path) -> None:
    """AC8.13.141: an invalid trust_mode is rejected by the folded contract."""
    _cpm_registry(tmp_path)
    test_dir = tmp_path / "apps" / "backend" / "tests"
    test_dir.mkdir(parents=True)
    (test_dir / "test_core.py").write_text(
        'def test_core():\n    """AC8.13.1: proof."""\n    assert True\n',
        encoding="utf-8",
    )
    payload = {
        "proofs": [
            {
                "id": "bad-trust",
                "scope": "behavioral",
                "ci_tier": "pr_ci",
                "trust_mode": "made_up_mode",
                "source_classes": ["bank_statement"],
                "file": "apps/backend/tests/test_core.py",
                "test": "test_core",
                "ac_ids": ["AC8.13.1"],
            }
        ]
    }
    results = cpm.validate_matrix(tmp_path, payload)
    errors = [e for r in results for e in r.errors]
    assert "bad-trust: invalid trust_mode 'made_up_mode'" in errors


def test_AC8_13_141_critical_proof_llm_missing_mirror_caught(tmp_path: Path) -> None:
    """AC8.13.141: an llm_ocr_post_merge proof without a mirror is rejected (folded)."""
    _cpm_registry(tmp_path)
    test_dir = tmp_path / "tests" / "e2e"
    test_dir.mkdir(parents=True)
    (test_dir / "test_core.py").write_text(
        'def test_core():\n    """AC8.13.1: proof."""\n    assert True\n',
        encoding="utf-8",
    )
    payload = {
        "proofs": [
            {
                "id": "llm-flow",
                "scope": "behavioral",
                "ci_tier": "post_merge_environment",
                "trust_mode": "llm_ocr_post_merge",
                "source_classes": ["bank_statement"],
                "file": "tests/e2e/test_core.py",
                "test": "test_core",
                "ac_ids": ["AC8.13.1"],
            }
        ]
    }
    results = cpm.validate_matrix(tmp_path, payload)
    errors = [e for r in results for e in r.errors]
    assert "llm-flow: llm_ocr_post_merge proof requires mirror_proof_id" in errors


def test_AC8_13_141_critical_proof_missing_marker_caught(tmp_path: Path) -> None:
    """AC8.13.141: a required pytest marker absent from the test is rejected (folded)."""
    _cpm_registry(tmp_path)
    test_dir = tmp_path / "apps" / "backend" / "tests"
    test_dir.mkdir(parents=True)
    (test_dir / "test_core.py").write_text(
        'def test_core():\n    """AC8.13.1: proof."""\n    assert True\n',
        encoding="utf-8",
    )
    payload = {
        "proofs": [
            {
                "id": "needs-marker",
                "scope": "behavioral",
                "ci_tier": "pr_ci",
                "file": "apps/backend/tests/test_core.py",
                "test": "test_core",
                "required_markers": ["critical"],
                "ac_ids": ["AC8.13.1"],
            }
        ]
    }
    results = cpm.validate_matrix(tmp_path, payload)
    errors = [e for r in results for e in r.errors]
    assert any("missing pytest markers on test_core: critical" in e for e in errors)


def test_AC8_13_141_critical_proof_manual_gate_without_evidence_caught(
    tmp_path: Path,
) -> None:
    """AC8.13.141: a manual_gate proof without evidence is rejected (folded)."""
    _cpm_registry(tmp_path)
    payload = {
        "proofs": [
            {
                "id": "manual-only",
                "scope": "manual_gate",
                "ci_tier": "manual",
                "ac_ids": ["AC8.13.1"],
            }
        ]
    }
    results = cpm.validate_matrix(tmp_path, payload)
    errors = [e for r in results for e in r.errors]
    assert "manual-only: evidence is required for manual_gate" in errors


def test_AC8_13_141_workflow_error_annotation_escapes_newlines() -> None:
    """AC8.13.141: multi-line folded messages survive the ::error annotation.

    The folded traceability messages embed newlines; a GitHub Actions workflow
    command truncates at the first newline, so the gate must escape %/CR/LF before
    emitting ``::error::`` or the annotation loses the actionable second line.
    """
    raw = "TRACEABILITY GATE FAILED: x\n  Move a proof into a CI-required stage. 50%"
    escaped = gate._escape_workflow_command(raw)
    assert "\n" not in escaped
    assert "%0A" in escaped  # newline preserved as an escape
    assert "%25" in escaped  # literal percent escaped
    # The human-readable content is still recoverable from the escapes.
    assert "Move a proof into a CI-required stage" in escaped


def test_AC8_13_141_consolidated_gate_surfaces_critical_proof_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC8.13.141: critical-proof errors flow through ``check_repo_contracts``.

    The fold wires ``validate_matrix_contract`` straight into Gate A; this proves
    that wiring surfaces the contract's errors (so a real critical-proof failure
    fails the one consolidated gate, exactly as the old standalone step did).
    """
    sentinel = "synthetic-proof: invalid trust_mode 'x'"
    fake = cpm.MatrixValidation(
        proofs=[
            cpm.ProofResult(
                proof_id="synthetic-proof",
                scope="behavioral",
                ci_tier="pr_ci",
                file="f",
                test="t",
                ac_ids=["AC8.13.1"],
                status="fail",
                errors=[sentinel],
            )
        ],
        outcomes=[],
    )
    # check_repo_contracts imports validate_matrix_contract locally from the cpm
    # module, so patching that module's attribute is what the local import sees.
    monkeypatch.setattr(cpm, "validate_matrix_contract", lambda repo_root: fake)
    errors = gate.check_repo_contracts(REPO_ROOT)
    assert sentinel in errors


# ---------------------------------------------------------------------------
# (c) ci.yml contract: old standalone gate STEPS removed, single gate remains,
#     job names / required contexts unchanged.
# ---------------------------------------------------------------------------


def _ci_text() -> str:
    return CI_YML.read_text(encoding="utf-8")


def test_AC8_13_141_old_standalone_gate_steps_removed_from_ci() -> None:
    """AC8.13.141: the standalone traceability + critical-proof gate STEPS are gone.

    No CI step invokes ``tools/check_ac_traceability.py`` or
    ``tools/check_critical_proof_matrix.py`` any more — their protection now runs
    inside the single ``check_ac_index`` gate.
    """
    text = _ci_text()
    assert "tools/check_ac_traceability.py" not in text
    assert "tools/check_critical_proof_matrix.py" not in text


def test_AC8_13_141_single_ac_index_gate_runs_exactly_once_per_required_path() -> None:
    """AC8.13.141: ``check_ac_index`` is the one index gate, not duplicated.

    It runs in the fast ``lint`` job (static, no junit). The ``ac-traceability``
    job no longer re-runs it — so the index gate is not executed twice.
    """
    # Count actual INVOCATIONS (a `... python tools/check_ac_index.py` command
    # line), not incidental mentions in comments.
    invocations = [
        line
        for line in _ci_text().splitlines()
        if "tools/check_ac_index.py" in line
        and "python" in line
        and not line.lstrip().startswith("#")
    ]
    # Exactly one invocation across CI (the lint job). The ratchet's own
    # --ratchet-current hook is enforced separately in ac-behavioral-ratchet.
    assert len(invocations) == 1, f"check_ac_index.py invoked {len(invocations)} times, expected 1: {invocations}"


def test_AC8_13_141_ci_job_names_and_required_contexts_unchanged() -> None:
    """AC8.13.141: required status-context job names are NOT renamed.

    Branch protection keys on these job ids; the consolidation only removes/edits
    STEPS inside jobs, never the job names or the ``finish`` needs list.
    """
    workflow = yaml.safe_load(_ci_text())
    jobs = set(workflow["jobs"])
    for required in ("lint", "ac-traceability", "ac-behavioral-ratchet", "finish"):
        assert required in jobs, f"job {required} must still exist"
    finish_needs = workflow["jobs"]["finish"]["needs"]
    for required in ("lint", "ac-traceability", "ac-behavioral-ratchet"):
        assert required in finish_needs, f"finish must still gate on {required}"
