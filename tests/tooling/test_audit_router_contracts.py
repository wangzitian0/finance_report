"""Contracts for the router contract-maturity audit (#1000 kickoff, #1055 PR3)."""

from __future__ import annotations

from pathlib import Path

from common.ssot import audit_router_contracts as audit

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
