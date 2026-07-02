"""Contracts for the router contract-maturity audit (#1000 kickoff, #1055 PR3)."""

from __future__ import annotations

from pathlib import Path

from common.testing import audit_router_contracts as audit

ROOT = Path(__file__).resolve().parents[2]


def test_detects_endpoint_without_response_model(tmp_path: Path) -> None:
    """An @router endpoint with no response_model is flagged; a typed one is not."""
    router = tmp_path / "apps" / "backend" / "src" / "routers" / "demo.py"
    router.parent.mkdir(parents=True)
    router.write_text(
        """
from fastapi import APIRouter

router = APIRouter()


@router.get("/typed", response_model=int)
async def typed() -> int:
    return 1


@router.post("/untyped")
async def untyped():
    return {"x": 1}
""".lstrip(),
        encoding="utf-8",
    )

    findings = audit.scan_dir(tmp_path / "apps" / "backend" / "src" / "routers", repo_root=tmp_path)

    assert len(findings) == 1
    assert findings[0].handler == "untyped"
    assert findings[0].method == "POST"
    assert findings[0].route == "/untyped"


def test_response_model_none_counts_as_untyped(tmp_path: Path) -> None:
    """response_model=None is an untyped contract — it must not silence the gate."""
    router = tmp_path / "demo.py"
    router.write_text(
        "from fastapi import APIRouter\n"
        "router = APIRouter()\n\n\n"
        '@router.get("/none", response_model=None)\n'
        "async def none_handler():\n    return {}\n",
        encoding="utf-8",
    )
    findings = audit.scan_file(router, repo_root=tmp_path)
    assert len(findings) == 1 and findings[0].handler == "none_handler"


def test_detects_endpoints_on_any_apirouter_variable(tmp_path: Path) -> None:
    """An untyped endpoint on a second APIRouter (not named 'router') is still caught."""
    router = tmp_path / "demo.py"
    router.write_text(
        "from fastapi import APIRouter\n"
        "router = APIRouter()\n"
        'conflicts_router = APIRouter(prefix="/review")\n\n\n'
        '@conflicts_router.delete("/{conflict_id}")\n'
        "async def drop_conflict():\n    return None\n",
        encoding="utf-8",
    )
    findings = audit.scan_file(router, repo_root=tmp_path)
    assert len(findings) == 1 and findings[0].handler == "drop_conflict"


def test_budget_gate_fails_on_growth(tmp_path: Path) -> None:
    """The CLI exits nonzero when untyped endpoints exceed the budget."""
    router = tmp_path / "apps" / "backend" / "src" / "routers" / "demo.py"
    router.parent.mkdir(parents=True)
    router.write_text(
        """
from fastapi import APIRouter

router = APIRouter()


@router.delete("/a")
async def a():
    return None
""".lstrip(),
        encoding="utf-8",
    )

    exit_code = audit.main(
        ["--repo-root", str(tmp_path), "--router-dir", str(router.parent), "--max-allowed", "0", "--check"]
    )
    assert exit_code == 1


def test_real_repo_within_budget() -> None:
    """The current untyped-endpoint count is a non-growth ceiling."""
    findings = audit.scan_dir(ROOT / "apps" / "backend" / "src" / "routers", repo_root=ROOT)
    assert len(findings) <= audit.DEFAULT_MAX_UNTYPED_ENDPOINTS, [
        f"{f.relative_path}:{f.line} {f.method} {f.route}" for f in findings
    ]


def test_findings_doc_is_in_sync() -> None:
    """The committed findings doc matches the current scan (regenerate on change)."""
    findings = audit.scan_dir(ROOT / "apps" / "backend" / "src" / "routers", repo_root=ROOT)
    expected = audit.render_markdown(findings)
    doc = (ROOT / "docs" / "reference" / "router-contract-maturity.md").read_text(encoding="utf-8")
    assert doc == expected, (
        "Run: python tools/audit_router_contracts.py --output docs/reference/router-contract-maturity.md"
    )


def test_cli_writes_output_and_reports_within_budget(tmp_path: Path, capsys) -> None:
    """--output writes the findings doc; a within-budget run prints and exits 0."""
    routers = tmp_path / "routers"
    routers.mkdir()
    (routers / "demo.py").write_text(
        'from fastapi import APIRouter\nrouter = APIRouter()\n\n\n@router.get("/ok", response_model=int)\nasync def ok() -> int:\n    return 1\n',
        encoding="utf-8",
    )
    out = tmp_path / "findings.md"
    code = audit.main(["--repo-root", str(tmp_path), "--router-dir", str(routers), "--output", str(out)])
    assert code == 0
    assert out.exists() and "Untyped Endpoints" in out.read_text(encoding="utf-8")
    assert "Untyped endpoints: 0" in capsys.readouterr().out


def test_route_literal_fallback_and_path_outside_repo(tmp_path: Path) -> None:
    """A non-literal route falls back to '?'; a file outside repo_root keeps its posix path."""
    router = tmp_path / "demo.py"
    router.write_text(
        "from fastapi import APIRouter\nrouter = APIRouter()\n_p = '/dyn'\n\n\n@router.get(_p)\nasync def dyn():\n    return {}\n",
        encoding="utf-8",
    )
    findings = audit.scan_file(router, repo_root=Path("/some/other/root"))
    assert len(findings) == 1
    assert findings[0].route == "?"
    assert findings[0].relative_path == router.as_posix()


def test_tools_wrapper_delegates_to_common() -> None:
    """The CLI wrapper delegates to the common implementation."""
    from tools import audit_router_contracts as wrapper

    assert wrapper.main is audit.main
