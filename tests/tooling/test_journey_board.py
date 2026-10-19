"""AC-testing.journey-board — the core-journey board shows outcomes honestly (#2370)."""

from __future__ import annotations

import ast
import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from common.testing import journey_board as board
from common.testing.journey_board import (
    INDEX_CAP,
    Case,
    CheckpointMap,
    Checkpoint,
    Proof,
    build_index,
    build_record,
    load_checkpoint_map,
    load_records,
    merge_retry,
    proof_checkpoint_statuses,
    record_path,
    render_fragment,
    rollup_checkpoints,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = REPO_ROOT / ".github" / "workflows"

MAP = CheckpointMap(
    checkpoints=(
        Checkpoint("U1", "upload"),
        Checkpoint("U2", "parse"),
        Checkpoint("U3", "route", gap="#2370"),
        Checkpoint("U4", "review"),
    ),
    proofs=(Proof("mod_a::test_a", "tests/e2e/mod_a.py", ("U1", "U2", "U4")),),
)


def _junit(cases: list[tuple[str, str, list[str]]]) -> str:
    """JUnit XML in the pytest layout: (test id, outcome, reached checkpoints)."""
    body = []
    for test_id, outcome, reached in cases:
        classname, name = test_id.split("::")
        props = "".join(
            f'<property name="checkpoint.{cp}" value="reached" />' for cp in reached
        )
        child = {
            "failed": '<failure message="AssertionError" />',
            "error": '<error message="RuntimeError" />',
            "skipped": '<skipped message="skip" />',
            "passed": "",
        }[outcome]
        body.append(
            f'<testcase classname="{classname}" name="{name}" time="1.5">'
            f"<properties>{props}</properties>{child}</testcase>"
        )
    return (
        '<?xml version="1.0" encoding="utf-8"?><testsuites><testsuite name="pytest">'
        + "".join(body)
        + "</testsuite></testsuites>"
    )


def _artifact(
    tmp_path: Path,
    cases: list[tuple[str, str, list[str]]],
    *,
    corpus: str = "core_journey",
    outcome: str = "regression-failed",
    retry: list[tuple[str, str, list[str]]] | None = None,
) -> Path:
    root = tmp_path / "artifact"
    (root / "test-results").mkdir(parents=True)
    (root / "ci-context").mkdir()
    (root / "test-results" / "staging-ai-ocr-gate.xml").write_text(_junit(cases))
    if retry is not None:
        (root / "test-results" / "staging-ai-ocr-retry.xml").write_text(_junit(retry))
    (root / "ci-context" / "staging-ai-ocr-context.txt").write_text(
        "Staging AI/OCR Context\n======================\n"
        f"corpus={corpus}\nai_ocr_outcome={outcome}\n"
        "expected_version=v9.9.9\ntested_sha=" + "a" * 40 + "\n"
    )
    return root


# The GitHub run payload: "name" is the run-name, "path" names the workflow
# (run 37965691488: name "Deploy Staging v0.1.75", path deploy.yml).
RUN_SHAPES = {
    "Deploy": (".github/workflows/deploy.yml", "Deploy Staging v9.9.9"),
    "AI/OCR Audit Replay": (
        ".github/workflows/audit-replay.yml",
        "AI/OCR Audit Replay",
    ),
    "CI": (".github/workflows/ci.yml", "CI"),
}


def _run(
    workflow: str = "AI/OCR Audit Replay",
    run_id: int = 1,
    completed: str = "2026-10-12T00:00:00Z",
) -> dict:
    path, run_name = RUN_SHAPES[workflow]
    return {
        "id": run_id,
        "run_attempt": 1,
        "html_url": f"https://example.invalid/runs/{run_id}",
        "name": run_name,
        "path": path,
        "event": "workflow_dispatch",
        "updated_at": completed,
        "display_title": run_name,
    }


def test_AC_testing_journey_board_1_checkpoint_status_follows_reached_order() -> None:
    """AC-testing.journey-board.1: reached order decides passed, failed, blocked and unproven."""
    proof = MAP.proofs[0]
    failed = Case("mod_a::test_a", "failed", 1.0, reached=["U1"])
    assert proof_checkpoint_statuses(failed, proof) == {
        "U1": "passed",
        "U2": "failed",
        "U4": "blocked",
    }
    passed_short = Case("mod_a::test_a", "passed", 1.0, reached=["U1", "U2"])
    assert proof_checkpoint_statuses(passed_short, proof) == {
        "U1": "passed",
        "U2": "passed",
        "U4": "unproven",
    }
    passed_full = Case("mod_a::test_a", "passed", 1.0, reached=["U1", "U2", "U4"])
    assert set(proof_checkpoint_statuses(passed_full, proof).values()) == {"passed"}


def test_AC_testing_journey_board_2_retry_skip_and_absence_are_distinct() -> None:
    """AC-testing.journey-board.2: retry, skip, absence and no proof show different statuses."""
    first = [Case("mod_a::test_a", "failed", 1.0, reached=[])]
    retry = [Case("mod_a::test_a", "passed", 2.0, reached=["U1", "U2", "U4"])]
    merged = merge_retry(first, retry)
    assert merged[0].outcome == "passed-on-retry"
    assert merged[0].reached == ["U1", "U2", "U4"]
    assert (
        merge_retry(first, [Case("mod_a::test_a", "failed", 2.0)])[0].outcome
        == "failed"
    )
    # The retry re-runs whole files: a first-pass pass that fails on retry is a failure.
    passed_first = [Case("mod_a::test_a", "passed", 1.0, reached=["U1", "U2", "U4"])]
    flipped = merge_retry(
        passed_first, [Case("mod_a::test_a", "failed", 2.0, reached=["U1"])]
    )
    assert flipped[0].outcome == "failed"
    assert flipped[0].reached == ["U1"]

    skipped = rollup_checkpoints([Case("mod_a::test_a", "skipped", 0.0)], MAP)
    assert skipped["U1"]["status"] == "skipped"
    absent = rollup_checkpoints([Case("mod_b::other", "passed", 0.0)], MAP)
    assert absent["U1"]["status"] == "not-run"
    assert absent["U3"] == {"status": "not-covered", "gap": "#2370"}


def test_AC_testing_journey_board_2_worst_status_wins_across_proofs() -> None:
    """AC-testing.journey-board.2: one failed proof turns a checkpoint red; not-run never hides a pass."""
    two = CheckpointMap(
        checkpoints=(Checkpoint("U1", "upload"),),
        proofs=(
            Proof("mod_a::test_a", "a.py", ("U1",)),
            Proof("mod_b::test_b", "b.py", ("U1",)),
        ),
    )
    passed = Case("mod_a::test_a", "passed", 1.0, reached=["U1"])
    failed = Case("mod_b::test_b", "failed", 1.0, reached=[])
    assert rollup_checkpoints([passed, failed], two)["U1"]["status"] == "failed"
    assert rollup_checkpoints([passed], two)["U1"]["status"] == "passed"


# Job lists in the shapes GitHub reports (runs 37965691488 and 37964773709).
# A skipped reusable call shows as "Staging AI/OCR Gate" with no suffix.
DEPLOY_GATE_SKIPPED = [
    {"name": "Deploy Staging", "conclusion": "failure"},
    {"name": "Staging AI/OCR Gate", "conclusion": "skipped"},
    {"name": "Staging AI/OCR Gate", "conclusion": "skipped"},
]
DEPLOY_GATE_RAN = [
    {"name": "Deploy Staging", "conclusion": "success"},
    {"name": "Staging AI/OCR Gate", "conclusion": "skipped"},
    {"name": "Staging AI/OCR Gate / Staging AI/OCR Gate", "conclusion": "failure"},
]
TAG_PUSH_PROMOTION = [
    # The real shape of "Release Images v0.1.76" (run 38341095111).
    {"name": "Promote SHA images to release tag", "conclusion": "success"},
    {"name": "Staging AI/OCR Gate", "conclusion": "skipped"},
    {"name": "Deploy Staging", "conclusion": "skipped"},
    {"name": "Staging Provider Gate", "conclusion": "skipped"},
    {"name": "Staging AI/OCR Gate", "conclusion": "skipped"},
    {"name": "Post-merge Delivery", "conclusion": "skipped"},
]


def test_AC_testing_journey_board_3_missing_evidence_is_shown_not_hidden(
    tmp_path: Path,
) -> None:
    """AC-testing.journey-board.3: a skipped gate and a lost artifact are visible; a promotion run is not a record."""
    empty = tmp_path / "none"
    assert build_record(empty, _run("Deploy"), TAG_PUSH_PROMOTION, MAP) is None

    skipped_gate = build_record(
        empty, _run("Deploy"), DEPLOY_GATE_SKIPPED, MAP, resolved_sha="b" * 40
    )
    assert skipped_gate["status"] == "not-run"
    assert skipped_gate["reason"] == (
        "the staging AI/OCR gate job did not run (Deploy Staging concluded failure)"
    )
    assert skipped_gate["lane"] == "canary"
    assert skipped_gate["tested_sha"] == "b" * 40
    assert {
        cell["status"]
        for key, cell in skipped_gate["checkpoints"].items()
        if key != "U3"
    } == {"not-run"}

    lost = build_record(empty, _run("Deploy"), DEPLOY_GATE_RAN, MAP)
    assert lost["status"] == "no-evidence"

    replay_not_started = build_record(
        empty,
        _run(),
        [{"name": "Staging AI/OCR Gate", "conclusion": "skipped"}],
        MAP,
    )
    assert replay_not_started["status"] == "not-run"
    assert replay_not_started["lane"] == "audit_replay"

    no_xml = tmp_path / "noxml"
    (no_xml / "ci-context").mkdir(parents=True)
    (no_xml / "ci-context" / "staging-ai-ocr-context.txt").write_text(
        "corpus=core_journey\nai_ocr_outcome=version-check-failed\n"
    )
    record = build_record(no_xml, _run(), [], MAP)
    assert record["status"] == "version-check-failed"
    assert record["reason"] == "the gate wrote no JUnit file"
    assert record["junit"] is False
    assert record["checkpoints"]["U1"]["status"] == "not-run"


def test_AC_testing_journey_board_3_artifact_values_are_validated(
    tmp_path: Path,
) -> None:
    """AC-testing.journey-board.3: artifact values never escape the board directory or replace a resolved SHA."""
    artifact = _artifact(
        tmp_path / "a",
        [("mod_a::test_a", "passed", ["U1", "U2", "U4"])],
        outcome="passed",
    )
    context = artifact / "ci-context" / "staging-ai-ocr-context.txt"
    context.write_text(
        context.read_text().replace(
            "tested_sha=" + "a" * 40, "tested_sha=../../escaped"
        )
    )
    record = build_record(artifact, _run(), [], MAP, resolved_sha="c" * 40)
    assert record["tested_sha"] == "c" * 40
    assert record_path(tmp_path, record).parent == tmp_path / "records" / ("c" * 40)
    context.write_text(
        context.read_text().replace("tested_sha=../../escaped", "tested_sha=unknown")
    )
    assert (
        build_record(artifact, _run(), [], MAP, resolved_sha="c" * 40)["tested_sha"]
        == "c" * 40
    )

    context.write_text(
        context.read_text().replace("corpus=core_journey", "corpus=../../x")
    )
    with pytest.raises(ValueError, match="unknown lane"):
        build_record(artifact, _run(), [], MAP)
    with pytest.raises(ValueError, match="is not a .github/workflows/deploy.yml or"):
        build_record(artifact, _run("CI"), [], MAP)


def test_AC_testing_journey_board_3_cli_checks_repository_and_tested_map(
    tmp_path: Path,
) -> None:
    """AC-testing.journey-board.3: the CLI rejects a foreign run and uses the tested revision's map."""
    artifact = _artifact(
        tmp_path / "a", [("mod_a::test_a", "passed", [])], outcome="passed"
    )
    run = _run() | {"head_repository": {"full_name": "owner/repo"}}
    (tmp_path / "run.json").write_text(json.dumps(run))
    (tmp_path / "jobs.json").write_text(json.dumps({"jobs": []}))
    args = [
        "build-record",
        "--artifact-dir",
        str(artifact),
        "--run-json",
        str(tmp_path / "run.json"),
        "--jobs-json",
        str(tmp_path / "jobs.json"),
        "--board-dir",
        str(tmp_path / "board"),
    ]
    assert board.main([*args, "--repository", "fork/repo"]) == 2
    assert not (tmp_path / "board").exists()

    assert (
        board.main(
            [
                *args,
                "--repository",
                "owner/repo",
                "--checkpoint-map",
                str(tmp_path / "absent.json"),
            ]
        )
        == 0
    )
    [written] = (tmp_path / "board" / "records").rglob("*.json")
    record = json.loads(written.read_text())
    assert record["map_note"] == "the tested revision has no checkpoint map"
    assert {cell["status"] for cell in record["checkpoints"].values()} == {
        "not-covered"
    }


def test_AC_testing_journey_board_3_record_reads_the_gate_artifact(
    tmp_path: Path,
) -> None:
    """AC-testing.journey-board.3: a gate artifact becomes one record with retry merged."""
    # pytest-playwright 0.10 names a browser test "test_a[chromium]" (seen in
    # the #2383 run); the proof "mod_a::test_a" must still match.
    artifact = _artifact(
        tmp_path,
        [
            ("mod_a::test_a[chromium]", "failed", ["U1"]),
            ("mod_c::test_c", "passed", []),
        ],
        retry=[("mod_a::test_a[chromium]", "passed", ["U1", "U2", "U4"])],
    )
    record = build_record(artifact, _run(), [], MAP)
    assert record["tests"][0]["test"] == "mod_a::test_a"
    # The gate manifest keeps the suffix; the failure class must still attach.
    failed_browser = _artifact(
        tmp_path / "fb", [("mod_b::test_b[chromium]", "failed", [])]
    )
    (failed_browser / "test-results" / "staging-ai-ocr-manifest.json").write_text(
        json.dumps(
            {
                "cases": [
                    {
                        "test": "mod_b::test_b[chromium]",
                        "class": "regression",
                        "subtype": "app-assertion",
                    }
                ]
            }
        )
    )
    browser_record = build_record(failed_browser, _run(), [], MAP)
    assert browser_record["tests"][0] == {
        "test": "mod_b::test_b",
        "outcome": "failed",
        "seconds": 1.5,
        "failure_class": "app-assertion",
    }
    assert record["lane"] == "core_journey"
    assert record["tested_sha"] == "a" * 40
    assert record["expected_version"] == "v9.9.9"
    assert record["counts"] == {"total": 2, "passed": 2, "failed": 0, "skipped": 0}
    assert record["tests"][0]["outcome"] == "passed-on-retry"
    assert record["checkpoints"]["U4"]["status"] == "passed"
    assert (
        record_path(tmp_path, record)
        == tmp_path / "records" / ("a" * 40) / "core_journey-1-1.json"
    )


def test_AC_testing_journey_board_3_staging_change_during_the_run_invalidates_the_record(
    tmp_path: Path,
) -> None:
    """AC-testing.journey-board.3: a staging deploy during the run invalidates the record."""
    artifact = _artifact(
        tmp_path, [("mod_a::test_a", "passed", ["U1", "U2", "U4"])], outcome="passed"
    )
    context = artifact / "ci-context" / "staging-ai-ocr-context.txt"
    context.write_text(context.read_text() + "end_version=v9.9.10\n")
    record = build_record(artifact, _run(), [], MAP)
    assert record["status"] == "invalidated"
    assert record["original_status"] == "passed"
    assert record["reason"] == "staging changed from v9.9.9 to v9.9.10 during the run"
    assert record["checkpoints"]["U4"] == {
        "status": "invalidated",
        "original": "passed",
        "proofs": [{"test": "mod_a::test_a", "status": "passed"}],
    }
    assert record["checkpoints"]["U3"]["status"] == "not-covered"
    # An invalidated record never hides another lane's result for the SHA.
    other = build_record(
        _artifact(tmp_path / "other", [("mod_a::test_a", "failed", ["U1"])]),
        _run(run_id=2),
        [],
        MAP,
    )
    other["tested_sha"] = record["tested_sha"]
    other["lane"] = "canary"
    assert (
        board.combine_for_sha([record, other], record["tested_sha"])["U2"]["status"]
        == "failed"
    )

    context.write_text(
        context.read_text().replace("end_version=v9.9.10", "end_version=" + "c" * 40)
    )
    assert build_record(artifact, _run(), [], MAP)["status"] == "passed", (
        "tag versus SHA is not a change"
    )


def test_AC_testing_journey_board_4_index_and_fragment_are_regenerated_honestly(
    tmp_path: Path,
) -> None:
    """AC-testing.journey-board.4: the index comes from all records and the fragment never shows empty green."""
    empty_index = build_index([], MAP, generated_at="2026-10-12T00:00:00+00:00")
    assert 'class="bad">No lane run has published a record yet.' in render_fragment(
        empty_index
    )

    old_sha, new_sha = "1" * 40, "2" * 40
    canary = build_record(
        _artifact(tmp_path / "c", [], corpus="canary", outcome="passed"),
        _run("Deploy", run_id=10, completed="2026-10-12T02:00:00Z"),
        [
            {
                "name": "Staging AI/OCR Gate / Staging AI/OCR Gate",
                "conclusion": "success",
            }
        ],
        MAP,
    )
    canary["tested_sha"] = new_sha
    journey = build_record(
        _artifact(tmp_path / "j", [("mod_a::test_a", "failed", ["U1"])]),
        _run(run_id=9, completed="2026-10-12T01:00:00Z"),
        [],
        MAP,
    )
    journey["tested_sha"] = old_sha
    journey["tests"][0]["test"] = "<script>alert(1)</script>"
    for record in (canary, journey):
        target = record_path(tmp_path / "board", record)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(record))
    # A later publish of the same run attempt without a SHA (a failed artifact
    # download) sorts after every hex directory; it must not replace the record.
    degraded = dict(
        journey,
        tested_sha=None,
        status="no-evidence",
        recorded_at="2099-01-01T00:00:00+00:00",
    )
    duplicate = tmp_path / "board" / "records" / "unknown" / "republished.json"
    duplicate.parent.mkdir(parents=True)
    duplicate.write_text(json.dumps(degraded))

    records = load_records(tmp_path / "board")
    assert [record["run"]["id"] for record in records] == ["10", "9"]
    assert records[1]["status"] == "regression-failed"
    index = build_index(
        records * (INDEX_CAP + 1), MAP, generated_at="2026-10-12T03:00:00+00:00"
    )
    assert len(index["records"]) == INDEX_CAP

    fragment = render_fragment(
        build_index(records, MAP, generated_at="2026-10-12T03:00:00+00:00")
    )
    assert "STALE: did not test the newest staging deploy" in fragment
    # The canary passed with no test case: never green.
    assert (
        'class="bad"><a href="https://example.invalid/runs/10">passed (no test evidence)</a>'
        in fragment
    )
    assert "<script>" not in fragment
    assert "&lt;script&gt;" in fragment
    assert (
        'class="bad"><a href="https://example.invalid/runs/9">failed</a> (core_journey)'
        in fragment
    )


def _checkpoint_calls(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "checkpoint"
        and len(node.args) == 2
        and isinstance(node.args[1], ast.Constant)
    ]
    return [
        call.args[1].value
        for call in sorted(calls, key=lambda call: (call.lineno, call.col_offset))
    ]


def _checkpoint_sequence(path: Path, function_name: str) -> list[str]:
    """Checkpoint marks in execution order, from one test function.

    A call to a function of the same module is expanded in place (its
    arguments first, then its body), so a helper that is defined but not
    called proves nothing. Branches are not evaluated.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    functions = {
        node.name: node
        for node in tree.body
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
    }
    marks: list[str] = []
    expanded: set[str] = set()

    def visit(node: ast.AST) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.Call) and isinstance(child.func, ast.Name):
                name = child.func.id
                if (
                    name == "checkpoint"
                    and len(child.args) == 2
                    and isinstance(child.args[1], ast.Constant)
                ):
                    marks.append(child.args[1].value)
                    continue
                if name in functions and name not in expanded:
                    for argument in [*child.args, *child.keywords]:
                        visit(argument)
                    expanded.add(name)
                    visit(functions[name])
                    continue
            visit(child)

    expanded.add(function_name)
    visit(functions[function_name])
    return marks


def _pytest_markers(path: Path, function_name: str) -> set[str]:
    """The ``@pytest.mark.<name>`` decorators of one test function."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    function = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
        and node.name == function_name
    )
    return {
        decorator.attr
        for decorator in function.decorator_list
        if isinstance(decorator, ast.Attribute)
        and isinstance(decorator.value, ast.Attribute)
        and decorator.value.attr == "mark"
    }


def _function_names(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
    }


def test_AC_testing_journey_board_5_checkpoint_map_matches_test_source() -> None:
    """AC-testing.journey-board.5: every proof's test marks exactly its checkpoints, in order."""
    checkpoint_map = load_checkpoint_map()
    assert checkpoint_map.proofs, "the board needs at least one core-journey proof"
    by_file: dict[str, list[Proof]] = {}
    for proof in checkpoint_map.proofs:
        by_file.setdefault(proof.file, []).append(proof)
    for file, proofs in by_file.items():
        path = REPO_ROOT / file
        assert path.is_file(), file
        assert len(proofs) == 1, (
            f"{file}: one core-journey proof per file keeps the order check exact"
        )
        proof = proofs[0]
        module, name = proof.test.split("::")
        assert module == path.stem, proof.test
        assert name in _function_names(path), proof.test
        assert _checkpoint_sequence(path, name) == list(proof.reaches), proof.test
    marked = {
        path.relative_to(REPO_ROOT).as_posix()
        for path in (REPO_ROOT / "tests" / "e2e").glob("test_*.py")
        if _checkpoint_calls(path)
    }
    assert marked == set(by_file), (
        "a test that marks checkpoints must be a mapped proof"
    )


def test_AC_testing_journey_board_6_publisher_wiring_keeps_gates_read_only() -> None:
    """AC-testing.journey-board.6: a separate publisher writes gh-pages; the gates stay read-only."""
    publisher = yaml.safe_load((WORKFLOWS / "journey-board.yml").read_text())
    triggers = publisher.get(True) or publisher["on"]
    assert set(triggers["workflow_run"]["workflows"]) == {
        "Deploy",
        "AI/OCR Audit Replay",
    }
    assert triggers["workflow_run"]["types"] == ["completed"]
    # Two triggers: an hourly reconcile publishes runs a workflow_run missed;
    # a dispatch replays one run, or reconciles when run_id is empty.
    assert triggers["schedule"] == [{"cron": "17 * * * *"}]
    assert triggers["workflow_dispatch"]["inputs"]["run_id"]["required"] is False
    select = next(
        step
        for step in publisher["jobs"]["publish"]["steps"]
        if step.get("id") == "select"
    )["run"]
    assert "7 days ago" in select and '"Release Images "*) continue' in select
    assert publisher["permissions"] == {"contents": "write", "actions": "read"}
    assert "concurrency" not in publisher, (
        "a concurrency group cancels pending publishes"
    )

    for gate in ("staging-ai-ocr-gate.yml", "audit-replay.yml"):
        text = (WORKFLOWS / gate).read_text()
        assert "contents: write" not in text, f"{gate} must stay read-only"

    benchmark = yaml.safe_load((WORKFLOWS / "benchmark.yml").read_text())
    pages_steps = [
        step
        for job in benchmark["jobs"].values()
        for step in job["steps"]
        if str(step.get("uses", "")).startswith("peaceiris/actions-gh-pages")
    ]
    assert pages_steps, "benchmark.yml publishes to gh-pages"
    for step in pages_steps:
        assert step["with"].get("keep_files") is True
        assert not step["with"].get("force_orphan"), (
            "gh-pages history must never be rewritten"
        )

    tree = ast.parse(Path(board.__file__).read_text(encoding="utf-8"))
    imported = {
        alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {
        node.module.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module and node.level == 0
    }
    assert imported <= set(sys.stdlib_module_names) | {"__future__"}, imported


@pytest.mark.parametrize("bad", [["U1", "U9"], ["U1", "U1"]])
def test_AC_testing_journey_board_5_map_rejects_unknown_or_repeated_checkpoints(
    tmp_path: Path, bad: list[str]
) -> None:
    """AC-testing.journey-board.5: the map loader rejects an unknown or repeated checkpoint."""
    path = tmp_path / "map.json"
    path.write_text(
        json.dumps(
            {
                "checkpoints": [{"id": "U1", "title": "upload"}],
                "proofs": [{"test": "m::t", "file": "m.py", "reaches": bad}],
            }
        )
    )
    with pytest.raises(ValueError):
        load_checkpoint_map(path)


def _record_and_finish_script() -> str:
    workflow = yaml.safe_load((WORKFLOWS / "staging-ai-ocr-gate.yml").read_text())
    step = next(
        s
        for s in workflow["jobs"]["run"]["steps"]
        if s.get("id") == "staging_ai_ocr_tests"
    )
    script = step["run"]
    start = script.index("record_and_finish() {")
    end = script.index("\n}\n", start)
    return script[start : end + len("\n}\n")]


def _run_record_and_finish(tmp_path: Path, corpus: str) -> dict:
    tmp_path.mkdir(parents=True)
    calls = tmp_path / "gh_calls.jsonl"
    fake_gh = tmp_path / "gh"
    fake_gh.write_text(
        "#!/bin/bash\n"
        f'python3 -c \'import json,sys; open(sys.argv[1], "a").write(json.dumps(sys.argv[2:]) + "\\n")\' "{calls}" "$@"\n'
        "exit 0\n"
    )
    fake_gh.chmod(0o755)
    output = tmp_path / "out.txt"
    script = _record_and_finish_script() + '\nrecord_and_finish 1 "regression-failed"\n'
    result = subprocess.run(
        ["bash", "-c", script],
        env={
            "PATH": f"{tmp_path}:/usr/bin:/bin",
            "GITHUB_OUTPUT": str(output),
            "CORPUS": corpus,
            "APP_URL": "https://example.invalid",
        },
        capture_output=True,
        text=True,
        timeout=30,
        cwd=tmp_path,
    )
    gh_calls = (
        [json.loads(line) for line in calls.read_text().splitlines()]
        if calls.exists()
        else []
    )
    return {
        "exit_code": result.returncode,
        "gh_calls": gh_calls,
        "output": output.read_text(),
    }


def test_AC_testing_journey_board_7_core_journey_lane_runs_after_deploy_and_files_no_alert(
    tmp_path: Path,
) -> None:
    """AC-testing.journey-board.7: the post-deploy core_journey lane is red on failure, files no alert, and blocks nothing."""
    from common.testing import staging_ai_ocr_gate_contract as contract

    proofs = load_checkpoint_map().proofs
    proof_nodes = sorted(
        f"{proof.file}::{proof.test.split('::', 1)[1]}" for proof in proofs
    )
    assert contract.core_journey_tests() == proof_nodes, (
        "only the proof tests run, not their whole files"
    )
    # Every proof is selectable by the gate marker "llm or journey"; a proof
    # without either marker would be deselected with no error.
    for proof in proofs:
        markers = _pytest_markers(REPO_ROOT / proof.file, proof.test.split("::", 1)[1])
        assert markers & {"llm", "journey"}, (
            f"{proof.test} carries neither llm nor journey"
        )

    journey = _run_record_and_finish(tmp_path / "journey", "core_journey")
    assert journey["exit_code"] == 1
    assert journey["gh_calls"] == []
    assert "ai_ocr_status=regression-failed" in journey["output"]
    # Only audit_replay files the alert issue (the alert set before #2370), so
    # a corpus-scoped auto-close stays correct (AC-testing.deploy-gates.45).
    canary = _run_record_and_finish(tmp_path / "canary", "canary")
    assert canary["exit_code"] == 1
    assert canary["gh_calls"] == []
    replay = _run_record_and_finish(tmp_path / "replay", "audit_replay")
    assert replay["exit_code"] == 1
    assert any(call[:2] == ["issue", "create"] for call in replay["gh_calls"])

    gate = (WORKFLOWS / "staging-ai-ocr-gate.yml").read_text()
    # Inputs (commit_ref comes from a manual version_ref) reach every gate
    # script through env, never inline in bash (#2370 audit).
    gate_steps = yaml.safe_load(gate)["jobs"]["run"]["steps"]
    inline = [
        step["name"] for step in gate_steps if "${{ inputs." in step.get("run", "")
    ]
    assert inline == [], f"inline inputs in gate scripts: {inline}"
    guard_at = gate.index('if [ "${#STAGING_AI_OCR_TESTS[@]}" -eq 0 ]; then')
    assert (
        gate.index("--preflight")
        < guard_at
        < gate.index('pytest "${STAGING_AI_OCR_TESTS[@]}"')
    )

    deploy = yaml.safe_load((WORKFLOWS / "deploy.yml").read_text())
    delivery = deploy["jobs"]["post-merge-delivery"]
    assert delivery["permissions"] == {"contents": "read", "actions": "write"}
    dispatch = delivery["steps"][0]
    assert dispatch["continue-on-error"] is True
    assert dispatch["if"] == (
        "${{ needs.build-and-deploy.result == 'success' && "
        "needs.build-and-deploy.outputs.staging_required == 'true' }}"
    )
    assert "gh workflow run audit-replay.yml" in dispatch["run"]
    assert "-f corpus=core_journey" in dispatch["run"]
    assert (
        dispatch["env"]["DEPLOYED_VERSION_REF"]
        == "${{ needs.build-and-deploy.outputs.deployed_version_ref }}"
    )
    # The deploy does not wait for the replay, and the release never reads it.
    assert "--watch" not in dispatch["run"]
    assert "gh run watch" not in dispatch["run"]
    for path in (
        WORKFLOWS / "release.yml",
        REPO_ROOT / "common/runtime/release_evidence.py",
    ):
        assert "audit-replay" not in path.read_text(), (
            f"{path.name} must not depend on the replay"
        )


def test_AC_testing_journey_board_8_release_shows_the_row_and_true_canary_evidence(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """AC-testing.journey-board.8: a release shows its board row before approval and reads the real canary job."""
    from datetime import UTC, datetime

    from common.runtime import release_evidence

    sha = "d" * 40
    canary = build_record(
        _artifact(
            tmp_path / "c",
            [("mod_c::test_c", "passed", [])],
            corpus="canary",
            outcome="passed",
        ),
        _run("Deploy", run_id=20, completed="2026-10-12T00:00:00Z"),
        [
            {
                "name": "Staging AI/OCR Gate / Staging AI/OCR Gate",
                "conclusion": "success",
            }
        ],
        MAP,
    )
    canary["tested_sha"] = sha
    replay = build_record(
        _artifact(
            tmp_path / "r", [("mod_a::test_a", "failed", ["U1"])], corpus="audit_replay"
        ),
        _run(run_id=21, completed="2026-10-01T00:00:00Z"),
        [],
        MAP,
    )
    row = board.render_release_row(
        [canary, replay],
        MAP,
        sha=sha,
        version_ref="v9.9.9",
        now=datetime(2026, 10, 12, tzinfo=UTC),
    )
    assert "| canary | passed |" in row
    empty_canary = dict(
        canary, counts={"total": 0, "passed": 0, "failed": 0, "skipped": 0}
    )
    empty_row = board.render_release_row(
        [empty_canary],
        MAP,
        sha=sha,
        version_ref="v9.9.9",
        now=datetime(2026, 10, 12, tzinfo=UTC),
    )
    assert "| canary | passed (no test evidence) |" in empty_row
    assert "| core_journey | NO RECORD for this revision |" in row
    assert "| U3 route | not-covered #2370 |" in row
    assert "11.0 days old (STALE)" in row
    # The newest audit replay line uses the evidence rule too (no green while empty).
    empty_replay = dict(
        replay,
        status="passed",
        junit=False,
        counts={"total": 0, "passed": 0, "failed": 0, "skipped": 0},
    )
    replay_row = board.render_release_row(
        [canary, empty_replay],
        MAP,
        sha=sha,
        version_ref="v9.9.9",
        now=datetime(2026, 10, 2, tzinfo=UTC),
    )
    assert "Newest audit replay: passed (no test evidence) on" in replay_row
    assert "1.0 days old." in replay_row and "STALE" not in replay_row, (
        "a fresh replay is not stale"
    )
    # Every lane shows, the manual "all" lane included.
    all_lane = dict(canary, lane="all", status="regression-failed")
    assert "| all | regression-failed |" in board.render_release_row(
        [canary, all_lane],
        MAP,
        sha=sha,
        version_ref="v9.9.9",
        now=datetime(2026, 10, 12, tzinfo=UTC),
    )
    # A checkpoint that the record holds but the map dropped still shows.
    dropped = dict(
        canary, checkpoints={**canary["checkpoints"], "U99": {"status": "failed"}}
    )
    assert (
        "| U99 (not in the current checkpoint map) | failed |"
        in board.render_release_row(
            [dropped],
            MAP,
            sha=sha,
            version_ref="v9.9.9",
            now=datetime(2026, 10, 12, tzinfo=UTC),
        )
    )
    # An unreadable board is not missing evidence.
    outage = board.render_release_row(
        [],
        MAP,
        sha=sha,
        version_ref="v9.9.9",
        now=datetime(2026, 10, 12, tzinfo=UTC),
        board_available=False,
    )
    assert "Board unavailable: no board records could be read" in outage
    assert "NO RECORD" not in outage
    unresolved = board.render_release_row(
        [], MAP, sha=None, version_ref="v9.9.9", now=datetime.now(UTC)
    )
    assert "Board unavailable: the release SHA could not be resolved." in unresolved

    jobs = [
        {"name": "Staging AI/OCR Gate", "conclusion": "skipped"},
        {"name": "Staging AI/OCR Gate / Staging AI/OCR Gate", "conclusion": "failure"},
    ]
    assert (
        release_evidence._optional_job(jobs, "Staging AI/OCR Gate")["conclusion"]
        == "failure"
    )
    assert (
        release_evidence._optional_job(list(reversed(jobs)), "Staging AI/OCR Gate")[
            "conclusion"
        ]
        == "failure"
    )
    assert (
        release_evidence._optional_job(jobs[:1], "Staging AI/OCR Gate")["conclusion"]
        == "skipped"
    )
    assert release_evidence._optional_job([], "Staging AI/OCR Gate") is None
    both_ran = [
        {"name": "Staging AI/OCR Gate", "conclusion": "success"},
        {"name": "Staging AI/OCR Gate / Staging AI/OCR Gate", "conclusion": "failure"},
    ]
    assert (
        release_evidence._optional_job(both_ran, "Staging AI/OCR Gate")["conclusion"]
        == "failure"
    ), "the reusable call wins over the manual job"
    no_call = [
        {"name": "Staging AI/OCR Gate", "conclusion": "skipped"},
        {"name": "Staging AI/OCR Gate / retry", "conclusion": "success"},
    ]
    assert (
        release_evidence._optional_job(no_call, "Staging AI/OCR Gate")["name"]
        == "Staging AI/OCR Gate / retry"
    ), "a job that ran wins over a skipped one"

    def fake_gh_json(args: list[str]) -> object:
        if "list" in args:
            return [
                {
                    "databaseId": 7,
                    "status": "completed",
                    "displayTitle": "Deploy Staging v9.9.9",
                    "headSha": "e" * 40,
                }
            ]
        return {
            "jobs": [
                {"name": "Deploy Staging", "conclusion": "success"},
                {"name": "Staging Provider Gate", "conclusion": "success"},
                *jobs,
            ]
        }

    with pytest.raises(
        RuntimeError, match="No completed Deploy Staging run found for v9.9.9"
    ):
        release_evidence.verify_staging(
            repository="o/r",
            version_ref="v9.9.9",
            release_sha="e" * 40,
            gh_json=fake_gh_json,
        )
    printed = capsys.readouterr().out
    assert "release-critical jobs missing=['Financial Benchmark']" in printed

    def fake_gh_json_ok(args: list[str]) -> object:
        if "list" in args:
            return [
                {
                    "databaseId": 7,
                    "status": "completed",
                    "displayTitle": "Deploy Staging v9.9.9",
                    "headSha": "e" * 40,
                }
            ]
        return {
            "jobs": [
                {"name": "Deploy Staging", "conclusion": "success"},
                {"name": "Staging Provider Gate", "conclusion": "success"},
                {"name": "Staging AI/OCR Gate", "conclusion": "success"},
                {"name": "Financial Benchmark", "conclusion": "success"},
            ]
        }

    assert (
        release_evidence.verify_staging(
            repository="o/r",
            version_ref="v9.9.9",
            release_sha="e" * 40,
            gh_json=fake_gh_json_ok,
        )
        == "7"
    )

    # The CLI never fails a release: a malformed record or a non-SHA argument
    # still prints a row and exits 0.
    bad = tmp_path / "bad-board"
    (bad / "records" / "x").mkdir(parents=True)
    (bad / "records" / "x" / "r.json").write_text("[]")
    assert (
        board.main(
            [
                "release-row",
                "--board-dir",
                str(bad),
                "--sha",
                sha,
                "--version-ref",
                "v9.9.9",
            ]
        )
        == 0
    )
    assert "Board unavailable" in capsys.readouterr().out
    assert (
        board.main(
            [
                "release-row",
                "--board-dir",
                str(tmp_path / "no-board"),
                "--sha",
                "v9.9.9^{commit}",
                "--version-ref",
                "v9.9.9",
            ]
        )
        == 0
    )
    assert "the release SHA could not be resolved" in capsys.readouterr().out

    release = yaml.safe_load((WORKFLOWS / "release.yml").read_text())
    board_job = release["jobs"]["journey-board"]
    row_step = next(step for step in board_job["steps"] if step.get("id") == "row")
    assert (
        'git rev-parse --verify --quiet "refs/tags/${VERSION_REF}^{commit}"'
        in row_step["run"]
    )
    assert board_job["outputs"]["sha"] == "${{ steps.row.outputs.sha }}"
    warn = next(
        step
        for step in release["jobs"]["deploy"]["steps"]
        if step["name"] == "Warn when the board row described another commit"
    )
    assert "exit 1" not in warn["run"] and "::warning::" in warn["run"]
    assert board_job["permissions"] == {"contents": "read"}
    assert "environment" not in board_job
    assert release["jobs"]["deploy"]["needs"] == ["journey-board"]
    assert release["jobs"]["deploy"]["if"] == "${{ !cancelled() && !inputs.dry_run }}"


def test_AC_testing_journey_board_3_rerun_reads_the_artifact_of_its_own_attempt(
    tmp_path: Path,
) -> None:
    """AC-testing.journey-board.3: a rerun record reads its own attempt's artifact, never the earlier one."""
    # The real shape of run 38341155894: attempt 2 started at 03:35:33 and
    # both attempts uploaded "staging-ai-ocr-test-context".
    run = {
        "id": 38341155894,
        "run_attempt": 2,
        "run_started_at": "2026-10-13T03:35:33Z",
    }
    artifacts = [
        {
            "id": 11787345837,
            "name": "staging-provider-gate-test-context",
            "created_at": "2026-10-13T03:24:22Z",
            "expired": False,
        },
        {
            "id": 11787147257,
            "name": "staging-ai-ocr-test-context",
            "created_at": "2026-10-13T03:30:19Z",
            "expired": False,
        },
        {
            "id": 11787003613,
            "name": "staging-ai-ocr-test-context",
            "created_at": "2026-10-13T03:37:19Z",
            "expired": False,
        },
    ]
    assert board.pick_artifact(artifacts, run)["id"] == 11787003613
    assert board.pick_artifact(artifacts[:2], run) is None, (
        "an earlier attempt's artifact is not this attempt's"
    )
    expired = [dict(artifacts[2], expired=True)]
    assert board.pick_artifact(expired, run) is None

    (tmp_path / "artifacts.json").write_text(json.dumps({"artifacts": artifacts}))
    (tmp_path / "run.json").write_text(json.dumps(run))
    assert (
        board.main(
            [
                "pick-artifact",
                "--artifacts-json",
                str(tmp_path / "artifacts.json"),
                "--run-json",
                str(tmp_path / "run.json"),
            ]
        )
        == 0
    )
