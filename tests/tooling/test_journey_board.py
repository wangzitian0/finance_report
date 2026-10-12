"""AC-testing.journey-board — the core-journey board shows outcomes honestly (#2370)."""

from __future__ import annotations

import ast
import json
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


def _run(
    name: str = "AI/OCR Audit Replay",
    run_id: int = 1,
    completed: str = "2026-10-12T00:00:00Z",
) -> dict:
    return {
        "id": run_id,
        "run_attempt": 1,
        "html_url": f"https://example.invalid/runs/{run_id}",
        "name": name,
        "event": "workflow_dispatch",
        "updated_at": completed,
        "display_title": name,
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


def test_AC_testing_journey_board_3_missing_evidence_is_shown_not_hidden(
    tmp_path: Path,
) -> None:
    """AC-testing.journey-board.3: no gate job, a skipped gate and a lost artifact are all visible."""
    empty = tmp_path / "none"
    build_only = build_record(
        empty, _run("Deploy"), [{"name": "Build", "conclusion": "success"}], MAP
    )
    assert build_only is None

    skipped_gate = build_record(
        empty,
        _run("Deploy"),
        [
            {
                "name": "Staging AI/OCR Gate / Staging AI/OCR Gate",
                "conclusion": "skipped",
            }
        ],
        MAP,
        resolved_sha="b" * 40,
    )
    assert skipped_gate["status"] == "not-run"
    assert skipped_gate["lane"] == "canary"
    assert skipped_gate["tested_sha"] == "b" * 40
    assert {
        cell["status"]
        for key, cell in skipped_gate["checkpoints"].items()
        if key != "U3"
    } == {"not-run"}

    lost = build_record(
        empty,
        _run("Deploy"),
        [
            {
                "name": "Staging AI/OCR Gate / Staging AI/OCR Gate",
                "conclusion": "failure",
            }
        ],
        MAP,
    )
    assert lost["status"] == "no-evidence"

    replay_not_started = build_record(
        empty,
        _run(),
        [
            {
                "name": "AI/OCR Audit Replay / Staging AI/OCR Gate",
                "conclusion": "skipped",
            }
        ],
        MAP,
    )
    assert replay_not_started["status"] == "not-run"
    assert replay_not_started["lane"] == "audit_replay"
    manual_only = build_record(
        empty,
        _run("Deploy"),
        [{"name": "Staging AI/OCR Gate", "conclusion": "skipped"}],
        MAP,
    )
    assert manual_only is None, "the skipped manual Deploy job is not the reusable gate"

    no_xml = tmp_path / "noxml"
    (no_xml / "ci-context").mkdir(parents=True)
    (no_xml / "ci-context" / "staging-ai-ocr-context.txt").write_text(
        "corpus=core_journey\nai_ocr_outcome=version-check-failed\n"
    )
    record = build_record(no_xml, _run(), [], MAP)
    assert record["status"] == "version-check-failed"
    assert record["reason"] == "the gate wrote no JUnit file"
    assert record["checkpoints"]["U1"]["status"] == "not-run"


def test_AC_testing_journey_board_3_record_reads_the_gate_artifact(
    tmp_path: Path,
) -> None:
    """AC-testing.journey-board.3: a gate artifact becomes one record with retry merged."""
    artifact = _artifact(
        tmp_path,
        [("mod_a::test_a", "failed", ["U1"]), ("mod_c::test_c", "passed", [])],
        retry=[("mod_a::test_a", "passed", ["U1", "U2", "U4"])],
    )
    record = build_record(artifact, _run(), [], MAP)
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
    duplicate = tmp_path / "board" / "records" / "unknown" / "republished.json"
    duplicate.parent.mkdir(parents=True)
    duplicate.write_text(json.dumps(journey))

    records = load_records(tmp_path / "board")
    assert [record["run"]["id"] for record in records] == ["10", "9"]
    index = build_index(
        records * (INDEX_CAP + 1), MAP, generated_at="2026-10-12T03:00:00+00:00"
    )
    assert len(index["records"]) == INDEX_CAP

    fragment = render_fragment(
        build_index(records, MAP, generated_at="2026-10-12T03:00:00+00:00")
    )
    assert "STALE: did not test the newest staging deploy" in fragment
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
        assert _checkpoint_calls(path) == list(proof.reaches), file
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
