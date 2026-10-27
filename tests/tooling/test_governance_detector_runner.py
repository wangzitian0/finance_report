"""One runner for the package governance detectors (#2759).

AC-meta.governance-ratchet.10: every package detector provider delegates to
``common.meta.base.detector_runner`` and fails closed on a seeded violation.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
from common.meta.base.detector_runner import (
    all_of,
    missing_fragments,
    requires,
    run_detectors,
)
from common.meta.contract import CONTRACT as META_CONTRACT
from common.meta.extension.governance_detector import detect_governance

REPO_ROOT = Path(__file__).resolve().parents[2]
PROVIDERS = sorted(REPO_ROOT.glob("common/*/extension/governance_detector.py"))
OLD_SHAPE = """
def _source(repo_root, relative): ...
def _contains(repo_root, relative, fragments): ...
def detect_governance(*, repo_root):
    observations = []
    for guarantee_id, check in _CHECKS:
        observations.append(check(repo_root))
    return observations
"""


SEEDED_SHAPE = """
async def _contains(repo_root, relative, fragments): ...
def _peek(path):
    return path.read_text(encoding="utf-8")
def detect_governance(*, repo_root):
    return run_detectors("demo", {}, repo_root)
"""


def _shape_violations(source: str) -> list[str]:
    """Return why a provider keeps its own runner or file reader instead of using the runner."""
    funcs = {
        node.name: node
        for node in ast.parse(source).body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    findings = [f"defines {name}" for name in ("_source", "_contains") if name in funcs]
    findings += [
        f"{name} calls read_text"
        for name, node in funcs.items()
        if any(
            isinstance(call, ast.Call) and getattr(call.func, "attr", "") == "read_text"
            for call in ast.walk(node)
        )
    ]
    calls = [
        node
        for node in funcs["detect_governance"].body
        if not (isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant))
    ]
    if not (
        len(calls) == 1
        and isinstance(calls[0], ast.Return)
        and isinstance(calls[0].value, ast.Call)
        and getattr(calls[0].value.func, "id", "") == "run_detectors"
    ):
        findings.append("detect_governance is not one run_detectors call")
    return findings


def test_AC_meta_governance_ratchet_10_providers_delegate_to_one_runner() -> None:
    """AC-meta.governance-ratchet.10: no provider keeps a private runner loop or file reader."""
    assert [path.parts[-3] for path in PROVIDERS] == [
        "extraction",
        "meta",
        "reconciliation",
        "reporting",
    ]
    for path in PROVIDERS:
        assert _shape_violations(path.read_text(encoding="utf-8")) == [], path
    assert _shape_violations(OLD_SHAPE) == [
        "defines _source",
        "defines _contains",
        "detect_governance is not one run_detectors call",
    ]
    assert _shape_violations(SEEDED_SHAPE) == [
        "defines _contains",
        "_peek calls read_text",
    ]


def test_AC_meta_governance_ratchet_10_runner_observations_and_exception_policy() -> (
    None
):
    """AC-meta.governance-ratchet.10: the runner owns prefix, counts, and the catch set."""

    def broken(_: object) -> list[str]:
        raise FileNotFoundError("gone.py")

    def bug(_: object) -> list[str]:
        raise TypeError("defect")

    checks = {"holds": lambda _: [], "breaks": lambda arg: [f"bad {arg}", "worse"]}
    assert run_detectors("demo", checks, "ctx") == [
        {"guarantee_id": "demo/holds", "current": 0, "target": 0, "findings": []},
        {
            "guarantee_id": "demo/breaks",
            "current": 2,
            "target": 0,
            "findings": ["bad ctx", "worse"],
        },
    ]
    [read] = run_detectors("demo", {"read": broken}, None)
    assert read["findings"] == ["read: check failed (FileNotFoundError): gone.py"]
    with pytest.raises(TypeError):
        run_detectors("demo", {"bug": bug}, None)
    [wide] = run_detectors("demo", {"bug": bug}, None, catch=(Exception,))
    assert wide["findings"] == ["bug: check failed (TypeError): defect"]


def test_AC_meta_governance_ratchet_10_runner_rejects_empty_input() -> None:
    """AC-meta.governance-ratchet.10: no detector passes on an empty table or no fragment."""
    with pytest.raises(ValueError, match="no checks"):
        run_detectors("demo", {})
    with pytest.raises(ValueError, match="at least one fragment"):
        requires("a.py")
    with pytest.raises(ValueError, match="at least one check"):
        all_of()


def test_AC_meta_governance_ratchet_10_missing_fragments_ignores_layout_only(
    tmp_path: Path,
) -> None:
    """AC-meta.governance-ratchet.10: layout is not a finding; a lost fragment or file is."""
    (tmp_path / "ok.py").write_text("value = (\n    1,\n    2,\n)\n", encoding="utf-8")
    (tmp_path / "broken.py").write_text("def broken(:\n", encoding="utf-8")
    (tmp_path / "notes.md").write_text("def broken(:\n", encoding="utf-8")
    check = all_of(
        requires("ok.py", "value = ( 1, 2, )"), requires("notes.md", "def broken(:")
    )
    assert check(tmp_path) == []
    assert requires("ok.py", "value = 3")(tmp_path) == ["ok.py: missing value = 3"]
    assert missing_fragments(tmp_path, "gone.py", ("x",)) == [
        "gone.py: file does not exist"
    ]
    [syntax] = requires("broken.py", "def broken(:")(tmp_path)
    assert syntax.startswith("broken.py: syntax error (SyntaxError)")


def test_AC_meta_governance_ratchet_10_meta_provider_fails_closed_on_a_vacuous_repo(
    tmp_path: Path,
) -> None:
    """AC-meta.governance-ratchet.10: the meta provider reports its contract guarantees; empty is red."""
    expected = {
        f"meta/{guarantee.id}"
        for initiative in META_CONTRACT.governance
        if initiative.id == "app-and-frontend-governance"
        for guarantee in initiative.guarantees
    }
    assert {
        item["guarantee_id"] for item in detect_governance(repo_root=REPO_ROOT)
    } == expected
    red = {
        item["guarantee_id"]
        for item in detect_governance(repo_root=tmp_path)
        if item["current"] > 0 and item["findings"]
    }
    assert red == {
        "meta/python-boundary-denominator",
        "meta/frontend-export-denominator",
        "meta/operation-consumer-truth",
        "meta/non-vacuity",
        "meta/governance-integration",
    }
