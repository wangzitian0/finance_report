"""Package layer boundaries, tier imports, dependency graph, base purity, and banned models."""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest

from common.meta.base.dependency_graph import (
    DependencyEdge,
    DependencyKind,
    build_dependency_graph,
)
from common.meta.extension import check_app_boundary
from common.meta.extension import check_tier_imports as tier_gate
from common.meta.extension.app_boundary import (
    APP_ENTRYPOINT_MODULES,
    APP_REMAINDER_SUBDIRS,
    cross_boundary_edges,
    discover_and_compute_edges,
    l4_deep_import_edges,
)
from common.meta.extension.base_purity import discover_impurities
from common.meta.extension.check_base_purity import BASELINE_BASE_IMPURITIES
from common.meta.extension.check_base_purity import main as base_purity_main
from common.meta.extension.check_base_purity import violations as base_purity_violations

ROOT = Path(__file__).resolve().parents[2]
BANNED_MODEL_RE = re.compile(r"glm-?4\.?6v", re.IGNORECASE)
RECORDED_DATA = "tests/fixtures/readings/ground_truth/"
THIS_FILE = Path(__file__).resolve().relative_to(ROOT).as_posix()
TEXT_SUFFIXES = {
    ".py",
    ".md",
    ".yml",
    ".yaml",
    ".json",
    ".toml",
    ".txt",
    ".sh",
    ".ts",
    ".tsx",
    ".js",
    ".mjs",
    ".example",
    ".ctmpl",
    ".hcl",
}


@dataclass(frozen=True)
class _Decl:
    name: str
    depends_on: tuple[str, ...]


def _make_pkg(
    backend_src: Path, name: str, all_symbols: list[str], internal_body: str = ""
) -> None:
    pkg = backend_src / name
    (pkg / "extension").mkdir(parents=True, exist_ok=True)
    (pkg / "__init__.py").write_text(f"__all__ = {all_symbols!r}\n", encoding="utf-8")
    (pkg / "extension" / "internal.py").write_text(
        internal_body or "SECRET = 1\n", encoding="utf-8"
    )


def _tracked_text_files() -> list[str]:
    out = subprocess.run(
        ["git", "ls-files", "-z"], cwd=ROOT, check=True, capture_output=True, text=True
    ).stdout
    return [
        p
        for p in out.split("\x00")
        if p
        and (Path(p).suffix in TEXT_SUFFIXES or p.endswith(".env.example"))
        and p != THIS_FILE
    ]


def test_AC26_7_1_tier_imports_real_and_synthetic(tmp_path: Path) -> None:
    """AC-authority.7.1 EPIC-026"""
    assert tier_gate.missing_protected_globs(ROOT) == []
    assert tier_gate.resolve_protected_files(ROOT), "protected set resolved to nothing"
    assert tier_gate.violations(ROOT) == []
    assert tier_gate.main(["--repo-root", str(ROOT)]) == 0

    for source, expected in (
        (
            "from src.llm.extension.client import LLMClient\n\ndef calc():\n    return 1\n",
            [("src.llm.extension.client", "src.llm")],
        ),
        ("import anthropic\n", [("anthropic", "anthropic")]),
        (
            "from apps.backend.src.llm.extension.factory import make\n",
            [("apps.backend.src.llm.extension.factory", "apps.backend.src.llm")],
        ),
        ("from src import llm\n", [("src.llm", "src.llm")]),
        (
            "from apps.backend.src import llm\n",
            [("apps.backend.src.llm", "apps.backend.src.llm")],
        ),
        (
            "from decimal import Decimal\nfrom src.audit.money.money import Money\nimport src.reporting.extension.reporting_calc as calc\n",
            [],
        ),
        ("import src.llmx\nfrom src.llm_helpers import noop\nimport openairy\n", []),
    ):
        assert tier_gate.forbidden_imports_in_source(source) == expected

    money_dir = tmp_path / "apps" / "backend" / "src" / "audit" / "money"
    money_dir.mkdir(parents=True)
    (money_dir / "money.py").write_text(
        "from src.llm.extension.client import LLMClient\n", encoding="utf-8"
    )
    for glob in tier_gate.PROTECTED_MODULE_GLOBS:
        target = tmp_path / glob.replace("/**/*.py", "/__init__.py")
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            target.write_text("from decimal import Decimal\n", encoding="utf-8")
    assert tier_gate.missing_protected_globs(tmp_path) == []
    found = tier_gate.violations(tmp_path)
    assert (
        "apps/backend/src/audit/money/money.py",
        "src.llm.extension.client",
        "src.llm",
    ) in found
    assert tier_gate.main(["--repo-root", str(tmp_path)]) == 1

    empty_root = tmp_path / "_empty"
    empty_root.mkdir()
    assert set(tier_gate.missing_protected_globs(empty_root)) == set(
        tier_gate.PROTECTED_MODULE_GLOBS
    )
    assert tier_gate.main(["--repo-root", str(empty_root)]) == 1


def test_AC_llm_banned_models_1_no_tracked_file_names_glm_4_6v() -> None:
    """AC-llm.banned-models.1"""
    tracked = _tracked_text_files()
    assert len(tracked) > 500, len(tracked)
    for expected in (
        "common/llm/readme.md",
        "apps/backend/src/config.py",
        ".github/workflows/ci.yml",
    ):
        assert expected in tracked, expected

    hits: dict[str, list[int]] = {}
    for rel in tracked:
        try:
            lines = (ROOT / rel).read_text(encoding="utf-8").splitlines()
        except (UnicodeDecodeError, OSError):
            continue
        numbers = [n for n, line in enumerate(lines, 1) if BANNED_MODEL_RE.search(line)]
        if numbers:
            hits[rel] = numbers

    live_hits = {p: n for p, n in hits.items() if not p.startswith(RECORDED_DATA)}
    assert not live_hits, f"glm-4.6v is banned; remove it from: {live_hits}"
    exempt = {p for p in hits if p.startswith(RECORDED_DATA)}
    assert all(p.endswith(".truth.json") for p in exempt), sorted(exempt)

    for spelling in (
        "glm-4.6v",
        "GLM-4.6V",
        "glm-4.6V",
        "glm4.6v",
        "zai/glm-4.6v",
        "openai/GLM-4.6V",
    ):
        assert BANNED_MODEL_RE.search(spelling), spelling
    for allowed in (
        "glm-4.5v",
        "glm-5.3-flash",
        "glm-5.2",
        "glm-4.6",
        "test-vision-model",
        "gpt-4o",
    ):
        assert not BANNED_MODEL_RE.search(allowed), allowed


def test_AC_meta_dependency_governance_3_app_boundary_and_l4_deep_imports(
    tmp_path: Path, monkeypatch
) -> None:
    """AC-meta.dependency-governance.3"""
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
    ok_src = ok_tmp / "apps/backend/src"
    (ok_src / "services").mkdir(parents=True)
    _make_pkg(ok_src, "extraction", ["PublicThing"])
    (ok_src / "services" / "ok.py").write_text(
        "from src.extraction import PublicThing\n", encoding="utf-8"
    )
    assert (
        cross_boundary_edges(
            backend_src=ok_src,
            carved={"extraction": "extraction"},
            published={"extraction": {"PublicThing"}},
            repo_root=ok_tmp,
        )
        == []
    )

    deep_src = tmp_path / "_deep/apps/backend/src"
    (deep_src / "routers").mkdir(parents=True)
    (deep_src / "audit").mkdir(parents=True)
    (deep_src / "routers" / "reports.py").write_text(
        "from src.audit.money import Money\n", encoding="utf-8"
    )
    (deep_src / "routers" / "health.py").write_text(
        "from src.audit import Money\n", encoding="utf-8"
    )
    assert l4_deep_import_edges(deep_src, {"audit"}) == [
        "routers/reports.py::from src.audit.money import Money"
    ]
    (deep_src / "routers" / "imports.py").write_text(
        "import src.audit.money\n", encoding="utf-8"
    )
    assert l4_deep_import_edges(deep_src, {"audit"}) == [
        "routers/imports.py::import src.audit.money",
        "routers/reports.py::from src.audit.money import Money",
    ]

    out_tmp = tmp_path / "_out"
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

    (out_src / "extraction" / "extension" / "reverse_leak.py").write_text(
        "def run():\n    from src.composition import compose_thing\n    return compose_thing()\n",
        encoding="utf-8",
    )
    comp_edges = cross_boundary_edges(
        backend_src=out_src,
        carved={"extraction": "extraction"},
        published={"extraction": {"PublicThing"}},
        repo_root=out_tmp,
    )
    assert any(
        e.startswith("out::") and "src.composition::compose_thing" in e
        for e in comp_edges
    )

    infra_tmp = tmp_path / "_infra"
    infra_src = infra_tmp / "apps/backend/src"
    (infra_src / "database").mkdir(parents=True)
    _make_pkg(infra_src, "ledger", ["Account"])
    (infra_src / "ledger" / "extension" / "repo.py").write_text(
        "from src.database import get_session\n", encoding="utf-8"
    )
    assert (
        cross_boundary_edges(
            backend_src=infra_src,
            carved={"ledger": "ledger"},
            published={"ledger": {"Account"}},
            repo_root=infra_tmp,
        )
        == []
    )

    assert APP_REMAINDER_SUBDIRS == frozenset({"services", "routers", "prompts"})
    assert APP_ENTRYPOINT_MODULES == frozenset(
        {"composition", "statement_flow", "main"}
    )
    assert not (ROOT / "common/meta/data/delivery-layer-baseline.json").exists()
    assert discover_and_compute_edges(ROOT) == []
    assert check_app_boundary.main(["--repo-root", str(ROOT)]) == 0

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


def test_AC_meta_dependency_governance_4_base_impurity_is_exact(tmp_path: Path) -> None:
    """AC-meta.dependency-governance.4"""
    src = tmp_path / "apps/backend/src"
    (src / "ledger/base").mkdir(parents=True)
    (src / "ledger/base/rule.py").write_text(
        "from src.ledger.orm.journal import JournalEntry\n", encoding="utf-8"
    )
    (src / "ledger/base/pure.py").write_text(
        "from decimal import Decimal\n", encoding="utf-8"
    )
    assert discover_impurities(src) == [
        "ledger/base/rule.py::from src.ledger.orm.journal import JournalEntry"
    ]
    assert not (ROOT / "common/meta/data/base-purity-baseline.json").exists()
    assert len(BASELINE_BASE_IMPURITIES) == 0
    assert base_purity_main([]) == 0

    stale_tmp = tmp_path / "_stale"
    stale_src = stale_tmp / "apps/backend/src/ledger/base"
    stale_src.mkdir(parents=True)
    (stale_src / "rule.py").write_text("import src.config\n", encoding="utf-8")
    baseline = stale_tmp / "baseline.json"
    baseline.write_text(
        json.dumps(["retired/base.py::import src.config"]), encoding="utf-8"
    )
    findings = base_purity_violations(stale_tmp, baseline)
    assert any("new base impurity" in f for f in findings)
    assert any("stale base-purity baseline" in f for f in findings)

    empty_tmp = tmp_path / "_empty_base"
    empty_tmp.mkdir()
    empty_baseline = empty_tmp / "baseline.json"
    empty_baseline.write_text("[]\n", encoding="utf-8")
    assert any(
        "cannot scan package base layers" in f
        for f in base_purity_violations(empty_tmp, empty_baseline)
    )


def test_AC_meta_dependency_governance_1_graph_builds_edges_and_rejects_cycles() -> (
    None
):
    """AC-meta.dependency-governance.1"""
    provider = _Decl("provider", ())
    middle = _Decl("middle", ("provider",))
    consumer = _Decl("consumer", ("middle",))
    graph = build_dependency_graph([consumer, provider, middle])
    assert graph.edges == (
        DependencyEdge(
            "consumer", "middle", DependencyKind.COMPILE, "PackageContract.depends_on"
        ),
        DependencyEdge(
            "middle", "provider", DependencyKind.COMPILE, "PackageContract.depends_on"
        ),
    )
    with pytest.raises(ValueError, match="unknown package"):
        build_dependency_graph([_Decl("broken", ("missing",))])
    with pytest.raises(ValueError, match="duplicate package"):
        build_dependency_graph([provider, provider])
    with pytest.raises(ValueError, match="duplicate dependency"):
        build_dependency_graph([provider, _Decl("duplicate", ("provider", "provider"))])
    with pytest.raises(ValueError, match="cannot depend on itself"):
        build_dependency_graph([_Decl("selfish", ("selfish",))])
    with pytest.raises(ValueError, match="dependency cycle"):
        build_dependency_graph(
            [_Decl("first", ("second",)), _Decl("second", ("first",))]
        )
