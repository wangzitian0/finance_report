from __future__ import annotations

import textwrap
from pathlib import Path

import pytest
from pydantic import ValidationError

import common.meta.extension.check_package_contract as cpc
from common.meta.extension.check_package_contract import (
    DiscoveredPackage,
    _package_all,
    _resolve_test,
    check_package,
    check_single_package,
    clear_run_cache,
    discover_packages,
    main,
    run,
)
from common.meta.package_contract import (
    TIER_DEFAULT_PROOF_KIND,
    TIER_VALID_PROOF_KINDS,
    ACRecord,
    CommandBoundary,
    Invariant,
    PackageClass,
    PackageContract,
    PackageStatus,
    PackageTier,
)

REPO = Path(__file__).resolve().parents[2]


def _write_package(
    repo_root: Path,
    name: str,
    *,
    klass: PackageClass = "infra",
    all_names: list[str] | None = None,
    interface: list[str] | None = None,
    depends_on: list[str] | None = None,
    invariants: list[Invariant] | None = None,
    roadmap: list[ACRecord] | None = None,
    extra_module: tuple[str, str] | None = None,
    tier: PackageTier = "CODE-ONLY",
    status: PackageStatus = "active",
    command_boundaries: list[CommandBoundary] | None = None,
) -> DiscoveredPackage:
    names = ["K"] if all_names is None else all_names
    iface = list(names) if interface is None else interface
    impl_rel = f"apps/backend/src/{name}"
    impl_dir = repo_root / impl_rel
    impl_dir.mkdir(parents=True)
    (impl_dir / "__init__.py").write_text(f"__all__ = {names!r}\n", encoding="utf-8")
    if extra_module is not None:
        (impl_dir / extra_module[0]).write_text(extra_module[1], encoding="utf-8")
    contract = PackageContract(
        name=name,
        klass=klass,
        tier=tier,
        status=status,
        depends_on=depends_on or [],
        interface=iface,
        events=[],
        invariants=invariants or [],
        roadmap=roadmap or [],
        command_boundaries=command_boundaries or [],
        implementations={"be": impl_rel, "fe": None},
    )
    spec_dir = repo_root / "common" / name
    spec_dir.mkdir(parents=True)
    (spec_dir / "readme.md").write_text(f"# {name}\n", encoding="utf-8")
    (spec_dir / "contract.py").write_text(
        f"from common.meta.package_contract import PackageContract\n"
        f"CONTRACT = PackageContract.model_validate({contract.model_dump()!r})\n",
        encoding="utf-8",
    )
    return DiscoveredPackage(
        name=name, spec_dir=spec_dir, impl_dir=impl_dir, contract=contract
    )


@pytest.fixture
def synthetic_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(cpc, "REPO_ROOT", tmp_path)
    (tmp_path / "apps" / "backend" / "src").mkdir(parents=True)
    (tmp_path / "common").mkdir(parents=True)
    clear_run_cache()
    return tmp_path


def test_contained_impl_dir_accepts_repo_relative(tmp_path: Path) -> None:
    assert (
        cpc._contained_impl_dir("apps/backend/src/counter", tmp_path)
        == (tmp_path / "apps" / "backend" / "src" / "counter").resolve()
    )
    sub = tmp_path / "sub"
    sub.mkdir()
    assert cpc._contained_impl_dir(".", sub) == sub.resolve()
    for bad in ("/etc", "../../outside", None):
        assert cpc._contained_impl_dir(bad, sub) is None


def test_escaping_be_path_reported_not_crashed(synthetic_repo: Path) -> None:
    pkg = _write_package(synthetic_repo, "escaper")
    pkg = DiscoveredPackage(
        name=pkg.name,
        spec_dir=pkg.spec_dir,
        impl_dir=cpc._contained_impl_dir("../escape", synthetic_repo),
        contract=pkg.contract,
    )
    errors = check_package(pkg, {"escaper": "infra"}, synthetic_repo)
    assert any("implementations['be'] is missing" in e for e in errors)


def test_interface_must_equal_all_passes_when_aligned(synthetic_repo: Path) -> None:
    pkg = _write_package(
        synthetic_repo, "aligned", all_names=["A", "B"], interface=["B", "A"]
    )
    assert check_package(pkg, {"aligned": "infra"}, synthetic_repo) == []


def test_interface_mismatch_is_reported(synthetic_repo: Path) -> None:
    pkg = _write_package(synthetic_repo, "drift", all_names=["A", "B"], interface=["A"])
    errors = check_package(pkg, {"drift": "infra"}, synthetic_repo)
    assert any("interface != __all__" in e for e in errors)


def test_duplicate_public_function_exports_are_rejected(synthetic_repo: Path) -> None:
    for name in ("first", "second"):
        _write_package(synthetic_repo, name, all_names=["shared_function"])
    ok, messages = run(synthetic_repo)
    assert not ok
    assert any(
        "public function 'shared_function' is exported by multiple packages" in m
        for m in messages
    )


def test_repeated_public_function_in_one_package_is_not_multi_owner(
    synthetic_repo: Path,
) -> None:
    _write_package(synthetic_repo, "single", all_names=["one_function", "one_function"])
    ok, messages = run(synthetic_repo)
    assert ok, messages


def test_unresolved_invariant_and_roadmap_refs_are_reported(
    synthetic_repo: Path,
) -> None:
    pkg = _write_package(
        synthetic_repo,
        "refs",
        invariants=[Invariant(id="INV1", statement="s", test="no/such/file.py::f")],
        roadmap=[
            ACRecord(
                id="AC1",
                statement="s",
                test="no/such/file.py::g",
                priority="P0",
                status="open",
            )
        ],
    )
    errors = check_package(pkg, {"refs": "infra"}, synthetic_repo)
    assert any("invariant 'INV1'" in e for e in errors)
    assert any("roadmap 'AC1'" in e for e in errors)


def test_resolve_test_branches(synthetic_repo: Path) -> None:
    test_dir = synthetic_repo / "t"
    test_dir.mkdir()
    (test_dir / "test_ok.py").write_text(
        "def test_real():\n    pass\n\nasync def test_async_real():\n    pass\n",
        encoding="utf-8",
    )
    for bad in (
        "t/test_ok.py",
        "t/missing.py::test_real",
        "t/test_ok.py::test_absent",
        "t/test_ok.py::TestSuite::test_real",
    ):
        assert _resolve_test(bad, synthetic_repo) is not None
    assert _resolve_test("t/test_ok.py::test_real", synthetic_repo) is None
    assert _resolve_test("t/test_ok.py::test_async_real", synthetic_repo) is None


def _write_ts_test_file(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        textwrap.dedent(
            """
            import { describe, expect, it, test } from "vitest";
            describe("money conformance", () => {
              it("AC-audit.20.2 real vitest test", () => { expect(1 + 1).toBe(2); });
              test("a real test() declaration", () => { expect(true).toBe(true); });
              test.only(`a template-literal title with ${1 + 1} inlined`, () => { expect(true).toBe(true); });
            });
            """
        ),
        encoding="utf-8",
    )


def test_resolve_test_frontend_branches(synthetic_repo: Path) -> None:
    rel = "apps/frontend/src/money.test.ts"
    _write_ts_test_file(synthetic_repo / rel)
    assert (
        _resolve_test("apps/frontend/src/missing.test.ts::x", synthetic_repo)
        is not None
    )
    err = _resolve_test(f"{rel}::no such test", synthetic_repo)
    assert err is not None and "not found" in err
    for title in (
        "AC-audit.20.2 real vitest test",
        "a real test() declaration",
        "a template-literal title with ${1 + 1} inlined",
    ):
        assert _resolve_test(f"{rel}::{title}", synthetic_repo) is None


def test_resolve_test_frontend_suffix_variants_all_resolve(
    synthetic_repo: Path,
) -> None:
    for suffix in (".test.tsx", ".spec.ts", ".spec.tsx"):
        rel = f"apps/frontend/src/money{suffix}"
        _write_ts_test_file(synthetic_repo / rel)
        assert (
            _resolve_test(f"{rel}::AC-audit.20.2 real vitest test", synthetic_repo)
            is None
        )
        assert _resolve_test(f"{rel}::not a real title", synthetic_repo) is not None


def test_unresolved_frontend_roadmap_ref_is_reported(synthetic_repo: Path) -> None:
    pkg = _write_package(
        synthetic_repo,
        "fefrefs",
        roadmap=[
            ACRecord(
                id="AC1",
                statement="s",
                test="apps/frontend/src/no/such/file.test.ts::whatever",
                status="open",
            )
        ],
    )
    errors = check_package(pkg, {"fefrefs": "infra"}, synthetic_repo)
    assert any("roadmap 'AC1'" in e and "test file does not exist" in e for e in errors)

    _write_ts_test_file(synthetic_repo / "apps/frontend/src/money2.test.ts")
    pkg2 = _write_package(
        synthetic_repo,
        "fefrefs2",
        roadmap=[
            ACRecord(
                id="AC2",
                statement="s",
                test="apps/frontend/src/money2.test.ts::not a real title",
                status="open",
            )
        ],
    )
    errors2 = check_package(pkg2, {"fefrefs2": "infra"}, synthetic_repo)
    assert any("roadmap 'AC2'" in e and "not found" in e for e in errors2)


def test_resolved_frontend_roadmap_ref_passes(synthetic_repo: Path) -> None:
    _write_ts_test_file(synthetic_repo / "apps/frontend/src/money.test.ts")
    pkg = _write_package(
        synthetic_repo,
        "fefok",
        roadmap=[
            ACRecord(
                id="AC1",
                statement="s",
                test="apps/frontend/src/money.test.ts::AC-audit.20.2 real vitest test",
                status="open",
            )
        ],
    )
    errors = check_package(pkg, {"fefok": "infra"}, synthetic_repo)
    assert not any("roadmap 'AC1'" in e for e in errors)


def test_upward_edge_is_forbidden(synthetic_repo: Path) -> None:
    pkg = _write_package(
        synthetic_repo,
        "platlow",
        klass="middleware",
        depends_on=["corehigh"],
        extra_module=("uses.py", "from src.corehigh import thing  # noqa\n"),
    )
    errors = check_package(
        pkg, {"platlow": "middleware", "corehigh": "domain"}, synthetic_repo
    )
    assert any("upward import of 'corehigh'" in e for e in errors)


def test_undeclared_sideways_edge_is_forbidden(synthetic_repo: Path) -> None:
    pkg = _write_package(
        synthetic_repo,
        "coreundeclared",
        klass="domain",
        extra_module=("uses.py", "import src.kerneldep\n"),
    )
    errors = check_package(
        pkg, {"coreundeclared": "domain", "kerneldep": "infra"}, synthetic_repo
    )
    assert any("not in" in e and "depends_on" in e for e in errors)


def test_declared_downward_edge_is_allowed(synthetic_repo: Path) -> None:
    pkg = _write_package(
        synthetic_repo,
        "coreok",
        klass="domain",
        depends_on=["kerneldep"],
        extra_module=("uses.py", "import src.kerneldep\nimport os\n"),
    )
    assert (
        check_package(pkg, {"coreok": "domain", "kerneldep": "infra"}, synthetic_repo)
        == []
    )


def test_same_class_declared_edge_is_allowed(synthetic_repo: Path) -> None:
    pkg = _write_package(
        synthetic_repo,
        "kernA",
        depends_on=["kernB"],
        extra_module=("uses.py", "from src.kernB import thing  # noqa\n"),
    )
    assert (
        check_package(pkg, {"kernA": "infra", "kernB": "infra"}, synthetic_repo) == []
    )


def test_unused_dependency_declaration_is_forbidden_for_active_package(
    synthetic_repo: Path,
) -> None:
    _write_package(synthetic_repo, "kernB")
    pkg = _write_package(synthetic_repo, "kernA", depends_on=["kernB"])
    errors = check_package(pkg, {"kernA": "infra", "kernB": "infra"}, synthetic_repo)
    assert any("kernB" in e and "no import" in e for e in errors)


def test_unused_dependency_declaration_allowed_for_draft_package(
    synthetic_repo: Path,
) -> None:
    _write_package(synthetic_repo, "kernB")
    pkg = _write_package(synthetic_repo, "kernA", depends_on=["kernB"], status="draft")
    errors = check_package(pkg, {"kernA": "infra", "kernB": "infra"}, synthetic_repo)
    assert not any("no import" in e for e in errors)


def test_used_dependency_declaration_has_no_unused_violation(
    synthetic_repo: Path,
) -> None:
    _write_package(synthetic_repo, "kernB")
    pkg = _write_package(
        synthetic_repo,
        "kernA",
        depends_on=["kernB"],
        extra_module=("uses.py", "from src.kernB import thing  # noqa\n"),
    )
    errors = check_package(pkg, {"kernA": "infra", "kernB": "infra"}, synthetic_repo)
    assert not any("no import" in e for e in errors)


def test_common_prefix_edge_is_detected_as_undeclared(synthetic_repo: Path) -> None:
    def _common_pkg(name: str, sym: str) -> DiscoveredPackage:
        d = synthetic_repo / "common" / name
        d.mkdir(parents=True)
        (d / "__init__.py").write_text(f"__all__ = [{sym!r}]\n", encoding="utf-8")
        c = PackageContract(
            name=name,
            klass="infra",
            tier="CODE-ONLY",
            depends_on=[],
            interface=[sym],
            events=[],
            invariants=[],
            roadmap=[],
            implementations={"be": f"common/{name}", "fe": None},
        )
        return DiscoveredPackage(name=name, spec_dir=d, impl_dir=d, contract=c)

    low, hi = _common_pkg("commonlow", "L"), _common_pkg("commonhi", "H")
    assert hi.impl_dir is not None
    (hi.impl_dir / "uses.py").write_text(
        "from common.commonlow import L\n", encoding="utf-8"
    )
    prefixes = cpc._registered_prefixes([low, hi], synthetic_repo)
    errors = cpc._check_no_forbidden_edge(
        hi, {"commonlow": "infra", "commonhi": "infra"}, prefixes
    )
    assert any("commonlow" in e and "depends_on" in e for e in errors)


def test_dependency_cycle_is_forbidden(synthetic_repo: Path) -> None:
    a = _write_package(synthetic_repo, "cycA", depends_on=["cycB"])
    b = _write_package(synthetic_repo, "cycB", depends_on=["cycA"])
    assert any("dependency cycle" in e for e in cpc._check_no_dependency_cycle([a, b]))


def test_base_layer_must_not_import_own_extension(synthetic_repo: Path) -> None:
    pkg = _write_package(synthetic_repo, "layered")
    impl = pkg.impl_dir
    assert impl is not None
    (impl / "base").mkdir()
    (impl / "extension").mkdir()
    (impl / "extension" / "sql.py").write_text("X = 1\n", encoding="utf-8")
    for fname, code in (
        ("abs_dotted.py", "from src.layered.extension.sql import X\n"),
        ("abs_pkg.py", "from src.layered import extension\n"),
        ("abs_import.py", "import src.layered.extension.sql\n"),
        ("rel.py", "from ..extension import sql\n"),
    ):
        (impl / "base" / fname).write_text(code, encoding="utf-8")
    offenders = cpc._check_layer_purity(pkg)
    flagged = {o.split(":")[0].split("/")[-1] for o in offenders}
    assert {"abs_dotted.py", "abs_pkg.py", "abs_import.py", "rel.py"} <= flagged
    assert cpc._check_layer_purity(_write_package(synthetic_repo, "plain")) == []


def test_package_all_handles_missing_and_non_literal_dunder(
    synthetic_repo: Path,
) -> None:
    for name, body in (
        ("nodunder", "x = 1\n"),
        ("computed", "__all__ = sorted(['A'])\n"),
    ):
        pkg_dir = synthetic_repo / name
        pkg_dir.mkdir(parents=True)
        (pkg_dir / "__init__.py").write_text(body, encoding="utf-8")
        assert _package_all(pkg_dir) == []


def test_run_reports_no_packages_when_empty(synthetic_repo: Path) -> None:
    ok, messages = run(synthetic_repo)
    assert ok is False and any("no packages discovered" in m for m in messages)


def test_AC_meta_package_truth_1_authored_surface_is_exact_and_non_vacuous(
    synthetic_repo: Path,
) -> None:
    "AC-meta.package-truth.1"
    ok, messages = run(synthetic_repo)
    assert not ok and any("no packages discovered" in m for m in messages)
    package = _write_package(synthetic_repo, "truthful")
    package_readme = package.spec_dir / "readme.md"
    package_readme.unlink()
    clear_run_cache()
    ok, messages = run(synthetic_repo)
    assert not ok and any(
        "missing required authored surface: readme.md" in m for m in messages
    )
    wrong_case_readme = package.spec_dir / "README.md"
    wrong_case_readme.write_text("# truthful\n", encoding="utf-8")
    clear_run_cache()
    ok, messages = run(synthetic_repo)
    assert not ok and any(
        "missing required authored surface: readme.md" in m for m in messages
    )
    wrong_case_readme.rename(package_readme)
    nested_worklist = package.spec_dir / "data" / "TODO.md"
    nested_worklist.parent.mkdir()
    nested_worklist.write_text("- [ ] hidden work\n", encoding="utf-8")
    clear_run_cache()
    ok, messages = run(synthetic_repo)
    assert not ok and any("parallel worklist is forbidden" in m for m in messages)
    nested_worklist.unlink()
    clear_run_cache()
    ok, messages = run(synthetic_repo)
    assert ok, messages


def test_run_caching_and_clear_cache(synthetic_repo: Path) -> None:
    clear_run_cache()
    ok1, msgs1 = run(synthetic_repo)
    assert not ok1 and synthetic_repo.resolve() in cpc._RUN_CACHE
    assert run(synthetic_repo) == (ok1, msgs1)
    clear_run_cache()
    assert synthetic_repo.resolve() not in cpc._RUN_CACHE
    assert run(synthetic_repo, use_cache=False) == (ok1, msgs1)


def test_discover_run_and_cli_outcomes(
    synthetic_repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["--repo-root", str(synthetic_repo)]) == 1
    assert "no packages discovered" in capsys.readouterr().out

    _write_package(synthetic_repo, "clean")
    clear_run_cache()
    assert {p.name for p in discover_packages(synthetic_repo)} == {"clean"}
    ok, messages = run(synthetic_repo)
    assert ok and any("clean (class infra)" in m for m in messages)
    assert main(["--repo-root", str(synthetic_repo)]) == 0
    assert "PASSED" in capsys.readouterr().out

    _write_package(synthetic_repo, "dirty", all_names=["A", "B"], interface=["A"])
    clear_run_cache()
    ok, messages = run(synthetic_repo)
    assert not ok and any("interface != __all__" in m for m in messages)
    assert main(["--repo-root", str(synthetic_repo)]) == 1
    assert "FAILED" in capsys.readouterr().out


def test_run_reports_dependency_cycle(synthetic_repo: Path) -> None:
    _write_package(synthetic_repo, "cycX", depends_on=["cycY"])
    _write_package(synthetic_repo, "cycY", depends_on=["cycX"])
    ok, messages = run(synthetic_repo)
    assert not ok and any("dependency cycle" in m for m in messages)


def _ac(**overrides: object) -> ACRecord:
    return ACRecord.model_validate(
        {
            "id": "AC1.1.1",
            "statement": "s",
            "test": "t::f",
            "priority": "P0",
            "status": "open",
            **overrides,
        }
    )


def _pkg(**overrides: object) -> PackageContract:
    return PackageContract.model_validate(
        {
            "name": "p",
            "klass": "infra",
            "depends_on": [],
            "interface": [],
            "events": [],
            "invariants": [],
            "roadmap": [],
            "status": "active",
            "tier": "CODE-ONLY",
            **overrides,
        }
    )


def test_active_package_must_declare_a_tier() -> None:
    for status in ("active", "deprecated"):
        with pytest.raises(ValidationError):
            _pkg(status=status, tier=None)
    assert _pkg(status="draft", tier=None).tier is None


def test_package_proof_kind_must_satisfy_the_tier_matrix() -> None:
    "AC-meta.public-boundary.2"
    for tier in ("LLM-LED", "LLM-ONLY"):
        with pytest.raises(ValidationError):
            _pkg(tier=tier, roadmap=[_ac(proof_kind="exact")])
    for tier, expected in TIER_DEFAULT_PROOF_KIND.items():
        if tier != "HU":
            pkg = _pkg(tier=tier, roadmap=[_ac()])
            assert pkg.roadmap[0].proof_kind == expected
            assert pkg.roadmap[0].proof_kind in TIER_VALID_PROOF_KINDS[tier]
    packages = discover_packages(REPO)
    declared = sorted(
        (p.name, b.symbol) for p in packages for b in p.contract.command_boundaries
    )
    assert {
        ("extraction", "ReviewedStatementEnvelopeCommand"),
        ("ledger", "AnchoredJournalCommand"),
    } <= set(declared)
    by_name = {p.name: p for p in packages}
    for name, symbol in declared:
        assert by_name[name].impl_dir is not None
        assert len(cpc._command_definitions(by_name[name].impl_dir, symbol)) == 1
        assert check_single_package(name, REPO)[0]


def test_check_single_package_outcomes(synthetic_repo: Path) -> None:
    _write_package(synthetic_repo, "clean")
    ok, messages = check_single_package("clean", synthetic_repo)
    assert ok and any("clean" in msg and "OK" in msg for msg in messages)
    ok2, messages2 = check_single_package("nonexistent", synthetic_repo)
    assert not ok2 and any("not discovered" in msg for msg in messages2)


def _command_package(
    repo: Path, body: str, *, symbol: str = "Cmd"
) -> DiscoveredPackage:
    return _write_package(
        repo,
        "commands",
        klass="domain",
        all_names=[symbol],
        extra_module=("commands.py", body),
        command_boundaries=[
            CommandBoundary(symbol=symbol, version="1", proof="tests/x.py::test_x")
        ],
    )


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        (
            "@dataclass(frozen=True)\nclass Cmd:\n    payload: dict[str, object] | None = None\n",
            "dynamic type on field 'payload'",
        ),
        (
            "class Cmd:\n    handler: Callable[..., int]\n",
            "dynamic type on field 'handler'",
        ),
        (
            "def Cmd(currency, amount: int) -> int:\n    return amount\n",
            "untyped financial parameter 'currency'",
        ),
        (
            "def Cmd(rows: List[Dict[str, str]]) -> int:\n    return 1\n",
            "dynamic type on parameter 'rows'",
        ),
        (
            "async def Cmd(amount: int) -> Any:\n    return amount\n",
            "dynamic return type",
        ),
        ("def Cmd(amount: int):\n    return amount\n", "dynamic return type"),
        (
            "def Cmd(amount: int) -> Optional[dict[str, str]]:\n    return None\n",
            "dynamic return type",
        ),
        (
            "def Cmd(amount: int) -> tuple[dict[str, str], int]:\n    return {}, 1\n",
            "dynamic return type",
        ),
        (
            "def Cmd(amount: int) -> 'dict[str, str]':\n    return {}\n",
            "dynamic return type",
        ),
        (
            "def Cmd(amount: int) -> Optional[Callable[..., int]]:\n    return None\n",
            "dynamic return type",
        ),
        (
            "def Cmd(*args: dict[str, str]) -> int:\n    return 1\n",
            "dynamic type on parameter 'args'",
        ),
        (
            "def Cmd(**kwargs: dict[str, str]) -> int:\n    return 1\n",
            "dynamic type on parameter 'kwargs'",
        ),
    ],
)
def test_AC_meta_public_boundary_2_command_boundary_rejects_dynamic_types(
    synthetic_repo: Path, body: str, expected: str
) -> None:
    "AC-meta.public-boundary.2"
    pkg = _command_package(synthetic_repo, body)
    errors = check_package(pkg, {"commands": "domain"}, synthetic_repo)
    assert any(expected in e for e in errors), errors


@pytest.mark.parametrize(
    "body",
    [
        "@dataclass(frozen=True)\nclass Cmd:\n    amount: Decimal\n    tags: Mapping[str, str]\n    entry_date: date\n",
        "async def Cmd(amount: Decimal, currency: str, *args: int, **kwargs: str) -> Receipt:\n    return Receipt()\n",
    ],
)
def test_AC_meta_public_boundary_2_command_boundary_accepts_typed_definitions(
    synthetic_repo: Path, body: str
) -> None:
    "AC-meta.public-boundary.2"
    pkg = _command_package(synthetic_repo, body)
    assert check_package(pkg, {"commands": "domain"}, synthetic_repo) == []


@pytest.mark.parametrize(
    ("body", "found"),
    [
        ("class Other:\n    amount: int\n", 0),
        ("class Cmd:\n    amount: int\n\ndef Cmd() -> int:\n    return 1\n", 2),
    ],
)
def test_AC_meta_public_boundary_2_command_boundary_needs_exactly_one_definition(
    synthetic_repo: Path, body: str, found: int
) -> None:
    "AC-meta.public-boundary.2"
    pkg = _command_package(synthetic_repo, body)
    errors = check_package(pkg, {"commands": "domain"}, synthetic_repo)
    assert any(
        "exactly one top-level definition" in e and f"found {found}" in e
        for e in errors
    )


def test_declarative_contract_table_builders_and_ast_parity(tmp_path: Path) -> None:
    from common.meta.extension.generate_ac_registry import (
        _roadmap_acs_from_contract,
        package_contract_meta,
    )
    from common.meta.package_contract import (
        Kind,
        acs,
        concepts,
        invs,
        rels,
        suite,
        units,
    )

    built_units = units(
        "@vo|base/types.py|Alpha Beta\nRepoUnit|repo|base/repo.py|extension/repo.py|custom.repo",
        ("vo", "base/extra.py", ("Gamma",)),
    )
    assert [
        (u.name, u.kind, u.module, u.impl, u.semantic_key) for u in built_units
    ] == [
        ("Alpha", Kind.VALUE_OBJECT, "base/types.py", None, None),
        ("Beta", Kind.VALUE_OBJECT, "base/types.py", None, None),
        (
            "RepoUnit",
            Kind.REPOSITORY,
            "base/repo.py",
            "extension/repo.py",
            "custom.repo",
        ),
        ("Gamma", Kind.VALUE_OBJECT, "base/extra.py", None, None),
    ]

    built_invs = invs(
        "@$t/test_demo.py\ninv-1|First invariant.|test_one\n@-\ninv-2|Second invariant.|$be/demo/test_two.py::test_two"
    )
    assert [(i.id, i.test) for i in built_invs] == [
        ("inv-1", "tests/tooling/test_demo.py::test_one"),
        ("inv-2", "apps/backend/tests/demo/test_two.py::test_two"),
    ]
    assert (
        rels("demo", "audit|published-language|Uses audit money types.")[0].provider
        == "audit"
    )
    assert concepts(
        "demo_concept|common/demo/readme.md|Demo concept.|vision.md|tests/tooling/test_demo.py|demo|concept"
    )[0].cross_refs == ["vision.md"]
    with pytest.raises(ValueError, match="malformed AC table row"):
        acs("demo", "1.1|missing-test-column")

    runtime_acs = acs(
        "demo",
        suite("$t/test_suite.py", ("2.1", "Suite row.", "test_s"), priority="P2"),
    )
    assert runtime_acs[0].id == "AC-demo.2.1"

    contract_file = tmp_path / "contract.py"
    contract_file.write_text(
        textwrap.dedent(
            '''
            from common.meta.package_contract import PackageContract, acs, suite
            CONTRACT = PackageContract(
                name="demo", klass="infra", status="active", tier="CODE-LED",
                depends_on=[], interface=[], events=[], invariants=[],
                roadmap=acs(
                    "demo",
                    """
                    @$be/demo/test_core.py|P0|done|exact
                    1.1|Exact check.|test_exact
                    1.2|Property override.|test_prop|P1:property:open|axiom-a
                    """,
                    suite("$t/test_suite.py", ("2.1", "Suite row.", "test_s"), priority="P2"),
                ),
            )
            '''
        ),
        encoding="utf-8",
    )
    ast_meta = package_contract_meta(contract_file)
    assert ast_meta is not None and (ast_meta["name"], ast_meta["tier"]) == (
        "demo",
        "CODE-LED",
    )
    assert [r["id"] for r in ast_meta["roadmap"]] == [
        "AC-demo.1.1",
        "AC-demo.1.2",
        "AC-demo.2.1",
    ]
    ast_records = _roadmap_acs_from_contract(contract_file)
    assert ast_records[0]["test"] == "apps/backend/tests/demo/test_core.py::test_exact"
    assert (
        ast_records[1]["priority"],
        ast_records[1]["status"],
        ast_records[1]["proof_kind"],
        ast_records[1]["vision_anchor"],
    ) == ("P1", "open", "property", "axiom-a")
    assert ast_records[2]["test"] == "tests/tooling/test_suite.py::test_s"
