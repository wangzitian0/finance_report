from __future__ import annotations

from pathlib import Path

from common.meta.extension.app_boundary import (
    APP_REMAINDER_SUBDIRS,
    cross_boundary_edges,
    discover_and_compute_edges,
    l4_deep_import_edges,
)

REPO_ROOT = Path(__file__).resolve().parents[2]


def _make_pkg(
    backend_src: Path, name: str, all_symbols: list[str], internal_body: str = ""
) -> None:
    pkg = backend_src / name
    (pkg / "extension").mkdir(parents=True, exist_ok=True)
    (pkg / "__init__.py").write_text(f"__all__ = {all_symbols!r}\n", encoding="utf-8")
    (pkg / "extension" / "internal.py").write_text(
        internal_body or "SECRET = 1\n", encoding="utf-8"
    )


def test_inbound_leak_detected(tmp_path: Path) -> None:
    src = tmp_path / "apps/backend/src"
    (src / "services").mkdir(parents=True)
    _make_pkg(src, "extraction", ["PublicThing"])
    (src / "services" / "leaky.py").write_text(
        "from src.extraction.extension.internal import SECRET\n", encoding="utf-8"
    )
    edges = cross_boundary_edges(
        backend_src=src,
        carved={"extraction": "extraction"},
        published={"extraction": {"PublicThing"}},
        repo_root=tmp_path,
    )
    assert any(e.startswith("in::") and "SECRET" in e for e in edges)

    ok_tmp = tmp_path / "_ok"
    ok_tmp.mkdir(exist_ok=True)
    ok_src = ok_tmp / "apps/backend/src"
    (ok_src / "services").mkdir(parents=True)
    _make_pkg(ok_src, "extraction", ["PublicThing"])
    (ok_src / "services" / "ok.py").write_text(
        "from src.extraction import PublicThing\n", encoding="utf-8"
    )
    ok_edges = cross_boundary_edges(
        backend_src=ok_src,
        carved={"extraction": "extraction"},
        published={"extraction": {"PublicThing"}},
        repo_root=ok_tmp,
    )
    assert ok_edges == []


def test_AC_meta_dependency_governance_3_l4_deep_imports_are_exact(
    tmp_path: Path,
) -> None:
    "AC-meta.dependency-governance.3"
    src = tmp_path / "apps/backend/src"
    (src / "routers").mkdir(parents=True)
    (src / "audit").mkdir(parents=True)
    (src / "routers" / "reports.py").write_text(
        "from src.audit.money import Money\n", encoding="utf-8"
    )
    (src / "routers" / "health.py").write_text(
        "from src.audit import Money\n", encoding="utf-8"
    )
    assert l4_deep_import_edges(src, {"audit"}) == [
        "routers/reports.py::from src.audit.money import Money"
    ]
    (src / "routers" / "imports.py").write_text(
        "import src.audit.money\n", encoding="utf-8"
    )
    assert l4_deep_import_edges(src, {"audit"}) == [
        "routers/imports.py::import src.audit.money",
        "routers/reports.py::from src.audit.money import Money",
    ]

    out_tmp = tmp_path / "_out"
    out_tmp.mkdir(exist_ok=True)
    out_src = out_tmp / "apps/backend/src"
    (out_src / "services").mkdir(parents=True)
    _make_pkg(out_src, "extraction", ["PublicThing"])
    (out_src / "extraction" / "extension" / "reaches_up.py").write_text(
        "from src.services.storage import redact\n", encoding="utf-8"
    )
    out_edges = cross_boundary_edges(
        backend_src=out_src,
        carved={"extraction": "extraction"},
        published={"extraction": {"PublicThing"}},
        repo_root=out_tmp,
    )
    assert any(e.startswith("out::") and "src.services.storage" in e for e in out_edges)

    infra_tmp = tmp_path / "_infra"
    infra_tmp.mkdir(exist_ok=True)
    infra_src = infra_tmp / "apps/backend/src"
    (infra_src / "database").mkdir(parents=True)
    _make_pkg(infra_src, "ledger", ["Account"])
    (infra_src / "ledger" / "extension" / "repo.py").write_text(
        "from src.database import get_session\n", encoding="utf-8"
    )
    infra_edges = cross_boundary_edges(
        backend_src=infra_src,
        carved={"ledger": "ledger"},
        published={"ledger": {"Account"}},
        repo_root=infra_tmp,
    )
    assert infra_edges == []


def test_app_remainder_subdirs_are_the_app_domain_logic() -> None:
    from common.meta.extension.check_app_boundary import main

    assert APP_REMAINDER_SUBDIRS == frozenset({"services", "routers", "prompts"})
    assert discover_and_compute_edges(REPO_ROOT) == []
    assert main(["--repo-root", str(REPO_ROOT)]) == 0


def test_gate_fails_when_cross_boundary_or_l4_deep_edge_appears(
    tmp_path: Path, monkeypatch
) -> None:
    from common.meta.extension import check_app_boundary

    monkeypatch.setattr(
        check_app_boundary,
        "discover_and_compute_edges",
        lambda _root: [
            "in::apps/backend/src/services/new_leak.py::src.extraction.extension.x::SECRET"
        ],
    )
    monkeypatch.setattr(
        check_app_boundary, "discover_l4_deep_import_edges", lambda _root: []
    )
    assert check_app_boundary.main(["--repo-root", str(tmp_path)]) == 1

    monkeypatch.setattr(
        check_app_boundary, "discover_and_compute_edges", lambda _root: []
    )
    monkeypatch.setattr(
        check_app_boundary,
        "discover_l4_deep_import_edges",
        lambda _root: ["routers/reports.py::from src.audit.money import Money"],
    )
    assert check_app_boundary.main(["--repo-root", str(tmp_path)]) == 1
