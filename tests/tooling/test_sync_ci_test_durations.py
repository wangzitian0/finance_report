"""Tests for common/testing/sync_ci_test_durations.py (AC-testing.ci-structure.13)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch
from xml.etree import ElementTree

import pytest

import tools.sync_ci_test_durations
from common.testing.sync_ci_test_durations import (
    case_to_node_id,
    extract_durations_from_xmls,
    main,
    report_backend_balance,
    sync_from_directory,
    update_duration_seed,
)


def test_case_to_node_id_simple() -> None:
    """AC-testing.ci-structure.13: map JUnit testcase to pytest node ID."""
    case = ElementTree.Element(
        "testcase",
        {"classname": "tests.api.test_foo", "name": "test_bar", "time": "1.23"},
    )
    assert case_to_node_id(case) == "tests/api/test_foo.py::test_bar"


def test_case_to_node_id_with_test_class() -> None:
    """AC-testing.ci-structure.13: map JUnit testcase with class to pytest node ID."""
    case = ElementTree.Element(
        "testcase",
        {
            "classname": "tests.api.test_foo.TestClass",
            "name": "test_bar",
            "time": "0.5",
        },
    )
    assert case_to_node_id(case) == "tests/api/test_foo.py::TestClass::test_bar"


def test_extract_durations_from_xmls(tmp_path: Path) -> None:
    """AC-testing.ci-structure.13: extract test durations from valid and invalid XMLs."""
    xml_content = """<?xml version="1.0" encoding="utf-8"?>
<testsuite name="pytest" errors="0" failures="0" skipped="0" tests="2" time="1.5">
  <testcase classname="tests.api.test_demo" name="test_one" time="0.456" />
  <testcase classname="tests.api.test_demo" name="test_two" time="1.000" />
</testsuite>
"""
    valid_file = tmp_path / "valid.xml"
    valid_file.write_text(xml_content, encoding="utf-8")

    corrupted_file = tmp_path / "corrupted.xml"
    corrupted_file.write_text("invalid xml <><", encoding="utf-8")

    missing_file = tmp_path / "missing.xml"

    durations = extract_durations_from_xmls([valid_file, corrupted_file, missing_file])
    assert durations == {
        "tests/api/test_demo.py::test_one": 0.456,
        "tests/api/test_demo.py::test_two": 1.000,
    }


def test_update_duration_seed(tmp_path: Path) -> None:
    """AC-testing.ci-structure.13: merge and serialize duration seed files."""
    seed_file = tmp_path / "seed.json"
    initial = {"tests/a.py::test_1": 0.5, "tests/b.py::test_2": 1.2}
    seed_file.write_text(json.dumps(initial), encoding="utf-8")

    new_durations = {"tests/a.py::test_1": 0.8, "tests/c.py::test_3": 2.0}
    total, updated = update_duration_seed(seed_file, new_durations, dry_run=False)

    assert total == 3
    assert updated == 2

    saved = json.loads(seed_file.read_text(encoding="utf-8"))
    assert saved == {
        "tests/a.py::test_1": 0.8,
        "tests/b.py::test_2": 1.2,
        "tests/c.py::test_3": 2.0,
    }


def test_update_duration_seed_prunes_missing_files(tmp_path: Path) -> None:
    """AC-testing.ci-structure.13: prune obsolete test keys when file does not exist."""
    repo = tmp_path / "repo"
    repo.mkdir(parents=True)
    tests_dir = repo / "tests"
    tests_dir.mkdir(parents=True)
    (tests_dir / "exists.py").write_text("def test_1(): pass\n", encoding="utf-8")

    seed_file = tmp_path / "seed.json"
    initial = {
        "tests/exists.py::test_1": 0.5,
        "tests/deleted.py::test_old": 1.2,
    }
    seed_file.write_text(json.dumps(initial), encoding="utf-8")

    total, updated = update_duration_seed(
        seed_file,
        {"tests/exists.py::test_1": 0.9},
        repo_root=repo,
        prune_missing=True,
    )
    assert total == 1
    assert updated == 1
    saved = json.loads(seed_file.read_text(encoding="utf-8"))
    assert saved == {"tests/exists.py::test_1": 0.9}


def test_report_backend_balance(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """AC-testing.ci-structure.13: compute backend shard balance report."""
    test_dir = tmp_path / "tests"
    test_dir.mkdir(parents=True)
    (test_dir / "test_one.py").write_text("def test_a(): pass\n", encoding="utf-8")
    (test_dir / "test_two.py").write_text("def test_b(): pass\n", encoding="utf-8")

    durations = {
        "tests/test_one.py::test_a": 1.5,
        "tests/test_two.py::test_b": 2.5,
    }
    report_backend_balance(tmp_path, durations, splits=2)
    captured = capsys.readouterr().out
    assert "Backend Shard Partition Balance (2 splits)" in captured
    assert "Spread:" in captured


def test_sync_from_directory_and_main(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """AC-testing.ci-structure.13: end-to-end sync from directory and CLI invocation."""
    repo_root = tmp_path / "repo"
    backend_tests = repo_root / "apps" / "backend" / "tests"
    backend_tests.mkdir(parents=True)
    (backend_tests / "test_demo.py").write_text(
        "def test_demo(): pass\n", encoding="utf-8"
    )

    junit_root = tmp_path / "junits"
    b_dir = junit_root / "backend-shard-1-test-context"
    b_dir.mkdir(parents=True)
    (b_dir / "test.xml").write_text(
        '<testsuite><testcase classname="tests.test_demo" name="test_demo" time="0.5"/></testsuite>',
        encoding="utf-8",
    )

    t_dir = junit_root / "coverage-tooling-1"
    t_dir.mkdir(parents=True)
    (t_dir / "test.xml").write_text(
        '<testsuite><testcase classname="tests.tooling.test_gate" name="test_gate" time="0.2"/></testsuite>',
        encoding="utf-8",
    )

    # Run sync
    sync_from_directory(junit_root, repo_root, dry_run=False)
    out = capsys.readouterr().out
    assert "Backend: 1 XMLs -> 1 tests updated" in out
    assert "Tooling: 1 XMLs -> 1 tests updated" in out

    # Empty directory test
    empty_root = tmp_path / "empty"
    empty_root.mkdir()
    sync_from_directory(empty_root, repo_root, dry_run=True)
    empty_out = capsys.readouterr().out
    assert "no backend-shard XML files found" in empty_out
    assert "no coverage-tooling XML files found" in empty_out

    # Test main with --junit-dir
    exit_code = main(
        ["--junit-dir", str(junit_root), "--repo-root", str(repo_root), "--dry-run"]
    )
    assert exit_code == 0

    # Test main with missing required args
    with pytest.raises(SystemExit):
        main([])


def test_main_run_id_download(tmp_path: Path) -> None:
    """AC-testing.ci-structure.13: main downloads artifacts when --run-id is provided."""
    repo_root = tmp_path / "repo"
    repo_root.mkdir()

    def fake_subprocess_run(cmd: list[str], check: bool = True) -> None:
        target_dir = Path(cmd[cmd.index("--dir") + 1])
        b_dir = target_dir / "backend-shard-1-test-context"
        b_dir.mkdir(parents=True)
        (b_dir / "test.xml").write_text(
            '<testsuite><testcase classname="tests.test_demo" name="test_demo" time="0.5"/></testsuite>',
            encoding="utf-8",
        )

    with patch("subprocess.run", side_effect=fake_subprocess_run):
        exit_code = main(
            ["--run-id", "99999", "--repo-root", str(repo_root), "--dry-run"]
        )
        assert exit_code == 0


def test_tool_shim_entrypoint() -> None:
    """AC-testing.ci-structure.13: verify tools/sync_ci_test_durations.py thin wrapper."""
    assert callable(tools.sync_ci_test_durations.main)
    with pytest.raises(SystemExit):
        tools.sync_ci_test_durations.main(["--invalid-argument"])
