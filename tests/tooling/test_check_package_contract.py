from __future__ import annotations
import textwrap
from pathlib import Path
import pytest
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
from pydantic import ValidationError
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


def _write_package(
    repo_root: Path,
    name: str,
    *,
    klass: PackageClass,
    all_names: list[str],
    interface: list[str],
    depends_on: list[str] | None = None,
    invariants: list[Invariant] | None = None,
    roadmap: list[ACRecord] | None = None,
    extra_module: tuple[str, str] | None = None,
    tier: PackageTier = "CODE-ONLY",
    status: PackageStatus = "active",
    command_boundaries: list[CommandBoundary] | None = None,
) -> DiscoveredPackage:
    impl_rel = f"apps/backend/src/{name}"
    impl_dir = repo_root / impl_rel
    impl_dir.mkdir(parents=True)
    all_literal = ", ".join((repr(n) for n in all_names))
    (impl_dir / "__init__.py").write_text(
        f"__all__ = [{all_literal}]\n", encoding="utf-8"
    )
    if extra_module is not None:
        mod_name, mod_body = extra_module
        (impl_dir / mod_name).write_text(mod_body, encoding="utf-8")
    contract = PackageContract(
        name=name,
        klass=klass,
        tier=tier,
        status=status,
        depends_on=depends_on or [],
        interface=interface,
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
        textwrap.dedent(
            f"\n            from common.meta.package_contract import PackageContract\n            CONTRACT = PackageContract.model_validate({contract.model_dump()!r})\n            "
        ),
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


def _src(repo: Path) -> Path:
    return repo


def test_contained_impl_dir_accepts_repo_relative(tmp_path: Path) -> None:
    resolved = cpc._contained_impl_dir("apps/backend/src/counter", tmp_path)
    assert resolved == (tmp_path / "apps" / "backend" / "src" / "counter").resolve()
    _m1_tmp = tmp_path / "_m1"
    _m1_tmp.mkdir(exist_ok=True)
    assert cpc._contained_impl_dir(".", _m1_tmp) == _m1_tmp.resolve()
    _m2_tmp = tmp_path / "_m2"
    _m2_tmp.mkdir(exist_ok=True)
    assert cpc._contained_impl_dir("/etc", _m2_tmp) is None
    _m3_tmp = tmp_path / "_m3"
    _m3_tmp.mkdir(exist_ok=True)
    assert cpc._contained_impl_dir("../../outside", _m3_tmp) is None
    _m4_tmp = tmp_path / "_m4"
    _m4_tmp.mkdir(exist_ok=True)
    assert cpc._contained_impl_dir(None, _m4_tmp) is None


def test_escaping_be_path_reported_not_crashed(synthetic_repo: Path) -> None:
    pkg = _write_package(
        _src(synthetic_repo), "escaper", klass="infra", all_names=["E"], interface=["E"]
    )
    pkg = cpc.DiscoveredPackage(
        name=pkg.name,
        spec_dir=pkg.spec_dir,
        impl_dir=cpc._contained_impl_dir("../escape", synthetic_repo),
        contract=pkg.contract,
    )
    errors = cpc.check_package(pkg, {"escaper": "infra"}, synthetic_repo)
    assert any(("implementations['be'] is missing" in e for e in errors))


def test_interface_must_equal_all_passes_when_aligned(synthetic_repo: Path) -> None:
    pkg = _write_package(
        _src(synthetic_repo),
        "aligned",
        klass="infra",
        all_names=["A", "B"],
        interface=["B", "A"],
    )
    assert check_package(pkg, {"aligned": "infra"}, synthetic_repo) == []


def test_interface_mismatch_is_reported(synthetic_repo: Path) -> None:
    pkg = _write_package(
        _src(synthetic_repo),
        "drift",
        klass="infra",
        all_names=["A", "B"],
        interface=["A"],
    )
    errors = check_package(pkg, {"drift": "infra"}, synthetic_repo)
    assert any(("interface != __all__" in e for e in errors))


def test_duplicate_public_function_exports_are_rejected(synthetic_repo: Path) -> None:
    [
        _write_package(
            _src(synthetic_repo),
            name,
            klass="infra",
            all_names=["shared_function"],
            interface=["shared_function"],
        )
        for name in ("first", "second")
    ]
    ok, messages = run(synthetic_repo)
    assert not ok
    assert any(
        (
            "public function 'shared_function' is exported by multiple packages"
            in message
            for message in messages
        )
    )


def test_repeated_public_function_in_one_package_is_not_multi_owner(
    synthetic_repo: Path,
) -> None:
    _write_package(
        _src(synthetic_repo),
        "single",
        klass="infra",
        all_names=["one_function", "one_function"],
        interface=["one_function", "one_function"],
    )
    ok, messages = run(synthetic_repo)
    assert ok, messages


def test_unresolved_invariant_and_roadmap_refs_are_reported(
    synthetic_repo: Path,
) -> None:
    pkg = _write_package(
        _src(synthetic_repo),
        "refs",
        klass="infra",
        all_names=["X"],
        interface=["X"],
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
    assert any(("invariant 'INV1'" in e for e in errors))
    assert any(("roadmap 'AC1'" in e for e in errors))


def test_resolve_test_branches(synthetic_repo: Path) -> None:
    test_dir = synthetic_repo / "t"
    test_dir.mkdir()
    (test_dir / "test_ok.py").write_text(
        "def test_real():\n    pass\n\nasync def test_async_real():\n    pass\n",
        encoding="utf-8",
    )
    assert _resolve_test("t/test_ok.py", synthetic_repo) is not None
    assert _resolve_test("t/missing.py::test_real", synthetic_repo) is not None
    assert _resolve_test("t/test_ok.py::test_absent", synthetic_repo) is not None
    assert (
        _resolve_test("t/test_ok.py::TestSuite::test_real", synthetic_repo) is not None
    )
    assert _resolve_test("t/test_ok.py::test_real", synthetic_repo) is None
    assert _resolve_test("t/test_ok.py::test_async_real", synthetic_repo) is None


def _write_ts_test_file(path: Path) -> None:
    path.write_text(
        textwrap.dedent(
            '\n            import { describe, expect, it, test } from "vitest";\n\n            describe("money conformance", () => {\n              it("AC-audit.20.2 real vitest test", () => {\n                expect(1 + 1).toBe(2);\n              });\n\n              test("a real test() declaration", () => {\n                expect(true).toBe(true);\n              });\n\n              test.only(`a template-literal title with ${1 + 1} inlined`, () => {\n                expect(true).toBe(true);\n              });\n            });\n            '
        ),
        encoding="utf-8",
    )


def test_resolve_test_frontend_branches(synthetic_repo: Path) -> None:
    test_dir = synthetic_repo / "apps" / "frontend" / "src"
    test_dir.mkdir(parents=True)
    ts_file = test_dir / "money.test.ts"
    _write_ts_test_file(ts_file)
    rel = "apps/frontend/src/money.test.ts"
    assert (
        _resolve_test("apps/frontend/src/missing.test.ts::x", synthetic_repo)
        is not None
    )
    err = _resolve_test(f"{rel}::no such test", synthetic_repo)
    assert err is not None and "not found" in err
    assert (
        _resolve_test(f"{rel}::AC-audit.20.2 real vitest test", synthetic_repo) is None
    )
    assert _resolve_test(f"{rel}::a real test() declaration", synthetic_repo) is None
    assert (
        _resolve_test(
            f"{rel}::a template-literal title with ${{1 + 1}} inlined", synthetic_repo
        )
        is None
    )


def test_resolve_test_frontend_suffix_variants_all_resolve(
    synthetic_repo: Path,
) -> None:
    test_dir = synthetic_repo / "apps" / "frontend" / "src"
    test_dir.mkdir(parents=True)
    for suffix in (".test.tsx", ".spec.ts", ".spec.tsx"):
        ts_file = test_dir / f"money{suffix}"
        _write_ts_test_file(ts_file)
        rel = f"apps/frontend/src/money{suffix}"
        assert (
            _resolve_test(f"{rel}::AC-audit.20.2 real vitest test", synthetic_repo)
            is None
        ), suffix
        assert _resolve_test(f"{rel}::not a real title", synthetic_repo) is not None, (
            suffix
        )


def test_unresolved_frontend_roadmap_ref_is_reported(synthetic_repo: Path) -> None:
    pkg = _write_package(
        _src(synthetic_repo),
        "fefrefs",
        klass="infra",
        all_names=["X"],
        interface=["X"],
        roadmap=[
            ACRecord(
                id="AC1",
                statement="s",
                test="apps/frontend/src/no/such/file.test.ts::whatever",
                priority="P0",
                status="open",
            )
        ],
    )
    errors = check_package(pkg, {"fefrefs": "infra"}, synthetic_repo)
    assert any(
        ("roadmap 'AC1'" in e and "test file does not exist" in e for e in errors)
    ), errors
    test_dir = synthetic_repo / "apps" / "frontend" / "src"
    test_dir.mkdir(parents=True, exist_ok=True)
    _write_ts_test_file(test_dir / "money2.test.ts")
    pkg2 = _write_package(
        _src(synthetic_repo),
        "fefrefs2",
        klass="infra",
        all_names=["Y"],
        interface=["Y"],
        roadmap=[
            ACRecord(
                id="AC2",
                statement="s",
                test="apps/frontend/src/money2.test.ts::not a real title",
                priority="P0",
                status="open",
            )
        ],
    )
    errors2 = check_package(pkg2, {"fefrefs2": "infra"}, synthetic_repo)
    assert any(("roadmap 'AC2'" in e and "not found" in e for e in errors2)), errors2


def test_resolved_frontend_roadmap_ref_passes(synthetic_repo: Path) -> None:
    test_dir = synthetic_repo / "apps" / "frontend" / "src"
    test_dir.mkdir(parents=True)
    _write_ts_test_file(test_dir / "money.test.ts")
    pkg = _write_package(
        _src(synthetic_repo),
        "fefok",
        klass="infra",
        all_names=["X"],
        interface=["X"],
        roadmap=[
            ACRecord(
                id="AC1",
                statement="s",
                test="apps/frontend/src/money.test.ts::AC-audit.20.2 real vitest test",
                priority="P0",
                status="open",
            )
        ],
    )
    errors = check_package(pkg, {"fefok": "infra"}, synthetic_repo)
    assert not any(("roadmap 'AC1'" in e for e in errors)), errors


def test_upward_edge_is_forbidden(synthetic_repo: Path) -> None:
    src = _src(synthetic_repo)
    pkg = _write_package(
        src,
        "platlow",
        klass="middleware",
        all_names=["P"],
        interface=["P"],
        depends_on=["corehigh"],
        extra_module=("uses.py", "from src.corehigh import thing  # noqa\n"),
    )
    errors = check_package(
        pkg, {"platlow": "middleware", "corehigh": "domain"}, synthetic_repo
    )
    assert any(("upward import of 'corehigh'" in e for e in errors))


def test_undeclared_sideways_edge_is_forbidden(synthetic_repo: Path) -> None:
    src = _src(synthetic_repo)
    pkg = _write_package(
        src,
        "coreundeclared",
        klass="domain",
        all_names=["C"],
        interface=["C"],
        depends_on=[],
        extra_module=("uses.py", "import src.kerneldep\n"),
    )
    errors = check_package(
        pkg, {"coreundeclared": "domain", "kerneldep": "infra"}, synthetic_repo
    )
    assert any(("not in" in e and "depends_on" in e for e in errors))


def test_declared_downward_edge_is_allowed(synthetic_repo: Path) -> None:
    src = _src(synthetic_repo)
    pkg = _write_package(
        src,
        "coreok",
        klass="domain",
        all_names=["C"],
        interface=["C"],
        depends_on=["kerneldep"],
        extra_module=(
            "uses.py",
            "import src.kerneldep\nimport os  # non-src import ignored\n",
        ),
    )
    errors = check_package(
        pkg, {"coreok": "domain", "kerneldep": "infra"}, synthetic_repo
    )
    assert errors == []


def test_same_class_declared_edge_is_allowed(synthetic_repo: Path) -> None:
    src = _src(synthetic_repo)
    pkg = _write_package(
        src,
        "kernA",
        klass="infra",
        all_names=["A"],
        interface=["A"],
        depends_on=["kernB"],
        extra_module=("uses.py", "from src.kernB import thing  # noqa\n"),
    )
    errors = check_package(pkg, {"kernA": "infra", "kernB": "infra"}, synthetic_repo)
    assert errors == [], errors


def test_unused_dependency_declaration_is_forbidden_for_active_package(
    synthetic_repo: Path,
) -> None:
    src = _src(synthetic_repo)
    _write_package(src, "kernB", klass="infra", all_names=["B"], interface=["B"])
    pkg = _write_package(
        src,
        "kernA",
        klass="infra",
        all_names=["A"],
        interface=["A"],
        depends_on=["kernB"],
    )
    errors = check_package(pkg, {"kernA": "infra", "kernB": "infra"}, synthetic_repo)
    assert any(("kernB" in e and "no import" in e for e in errors)), errors


def test_unused_dependency_declaration_allowed_for_draft_package(
    synthetic_repo: Path,
) -> None:
    src = _src(synthetic_repo)
    _write_package(src, "kernB", klass="infra", all_names=["B"], interface=["B"])
    pkg = _write_package(
        src,
        "kernA",
        klass="infra",
        all_names=["A"],
        interface=["A"],
        depends_on=["kernB"],
        status="draft",
    )
    errors = check_package(pkg, {"kernA": "infra", "kernB": "infra"}, synthetic_repo)
    assert not any(("no import" in e for e in errors)), errors


def test_used_dependency_declaration_has_no_unused_violation(
    synthetic_repo: Path,
) -> None:
    src = _src(synthetic_repo)
    _write_package(src, "kernB", klass="infra", all_names=["B"], interface=["B"])
    pkg = _write_package(
        src,
        "kernA",
        klass="infra",
        all_names=["A"],
        interface=["A"],
        depends_on=["kernB"],
        extra_module=("uses.py", "from src.kernB import thing  # noqa\n"),
    )
    errors = check_package(pkg, {"kernA": "infra", "kernB": "infra"}, synthetic_repo)
    assert not any(("no import" in e for e in errors)), errors


def test_common_prefix_edge_is_detected_as_undeclared(synthetic_repo: Path) -> None:
    src = _src(synthetic_repo)
    low_dir = src / "common" / "commonlow"
    low_dir.mkdir(parents=True)
    (low_dir / "__init__.py").write_text("__all__ = ['L']\n", encoding="utf-8")
    infra_class: PackageClass = "infra"
    code_only_tier: PackageTier = "CODE-ONLY"
    low_contract = PackageContract(
        name="commonlow",
        klass=infra_class,
        tier=code_only_tier,
        depends_on=[],
        interface=["L"],
        events=[],
        invariants=[],
        roadmap=[],
        implementations={"be": "common/commonlow", "fe": None},
    )
    low = DiscoveredPackage(
        name="commonlow", spec_dir=low_dir, impl_dir=low_dir, contract=low_contract
    )
    hi_dir = src / "common" / "commonhi"
    hi_dir.mkdir(parents=True)
    (hi_dir / "__init__.py").write_text("__all__ = ['H']\n", encoding="utf-8")
    (hi_dir / "uses.py").write_text(
        "from common.commonlow import L  # noqa\n", encoding="utf-8"
    )
    hi_contract = PackageContract(
        name="commonhi",
        klass=infra_class,
        tier=code_only_tier,
        depends_on=[],
        interface=["H"],
        events=[],
        invariants=[],
        roadmap=[],
        implementations={"be": "common/commonhi", "fe": None},
    )
    hi = DiscoveredPackage(
        name="commonhi", spec_dir=hi_dir, impl_dir=hi_dir, contract=hi_contract
    )
    prefixes = cpc._registered_prefixes([low, hi], synthetic_repo)
    errors = cpc._check_no_forbidden_edge(
        hi, {"commonlow": "infra", "commonhi": "infra"}, prefixes
    )
    assert any(("commonlow" in e and "depends_on" in e for e in errors)), errors


def test_dependency_cycle_is_forbidden(synthetic_repo: Path) -> None:
    src = _src(synthetic_repo)
    a = _write_package(
        src,
        "cycA",
        klass="infra",
        all_names=["A"],
        interface=["A"],
        depends_on=["cycB"],
    )
    b = _write_package(
        src,
        "cycB",
        klass="infra",
        all_names=["B"],
        interface=["B"],
        depends_on=["cycA"],
    )
    offenders = cpc._check_no_dependency_cycle([a, b])
    assert any(("dependency cycle" in e for e in offenders)), offenders


def test_base_layer_must_not_import_own_extension(synthetic_repo: Path) -> None:
    pkg = _write_package(
        _src(synthetic_repo), "layered", klass="infra", all_names=["L"], interface=["L"]
    )
    impl = pkg.impl_dir
    (impl / "base").mkdir()
    (impl / "extension").mkdir()
    (impl / "extension" / "sql.py").write_text("X = 1\n", encoding="utf-8")
    (impl / "base" / "abs_dotted.py").write_text(
        "from src.layered.extension.sql import X  # noqa\n", encoding="utf-8"
    )
    (impl / "base" / "abs_pkg.py").write_text(
        "from src.layered import extension  # noqa\n", encoding="utf-8"
    )
    (impl / "base" / "abs_import.py").write_text(
        "import src.layered.extension.sql  # noqa\n", encoding="utf-8"
    )
    (impl / "base" / "rel.py").write_text(
        "from ..extension import sql  # noqa\n", encoding="utf-8"
    )
    offenders = cpc._check_layer_purity(pkg)
    flagged = {o.split(":")[0].split("/")[-1] for o in offenders}
    assert {"abs_dotted.py", "abs_pkg.py", "abs_import.py", "rel.py"} <= flagged, (
        offenders
    )
    plain = _write_package(
        _src(synthetic_repo), "plain", klass="infra", all_names=["P"], interface=["P"]
    )
    assert cpc._check_layer_purity(plain) == []


def test_package_all_handles_missing_dunder(synthetic_repo: Path) -> None:
    pkg_dir = _src(synthetic_repo) / "nodunder"
    pkg_dir.mkdir(parents=True)
    (pkg_dir / "__init__.py").write_text("x = 1\n", encoding="utf-8")
    assert _package_all(pkg_dir) == []


def test_package_all_tolerates_non_literal_all(synthetic_repo: Path) -> None:
    pkg_dir = _src(synthetic_repo) / "computed"
    pkg_dir.mkdir(parents=True)
    (pkg_dir / "__init__.py").write_text(
        "__all__ = sorted(['B', 'A'])\n", encoding="utf-8"
    )
    assert _package_all(pkg_dir) == []


def test_run_reports_no_packages_when_empty(synthetic_repo: Path) -> None:
    ok, messages = run(synthetic_repo)
    assert ok is False
    assert any(("no packages discovered" in m for m in messages))


def test_AC_meta_package_truth_1_authored_surface_is_exact_and_non_vacuous(
    synthetic_repo: Path,
) -> None:
    "AC-meta.package-truth.1"
    ok, messages = run(synthetic_repo)
    assert not ok
    assert any(("no packages discovered" in message for message in messages))
    package = _write_package(
        _src(synthetic_repo),
        "truthful",
        klass="infra",
        all_names=["K"],
        interface=["K"],
    )
    package_readme = package.spec_dir / "readme.md"
    package_readme.unlink()
    clear_run_cache()
    ok, messages = run(synthetic_repo)
    assert not ok
    assert any(
        (
            "missing required authored surface: readme.md" in message
            for message in messages
        )
    )
    package_readme.write_text("# truthful\n", encoding="utf-8")
    wrong_case_readme = package.spec_dir / "README.md"
    package_readme.rename(wrong_case_readme)
    clear_run_cache()
    ok, messages = run(synthetic_repo)
    assert not ok
    assert any(
        (
            "missing required authored surface: readme.md" in message
            for message in messages
        )
    )
    wrong_case_readme.rename(package_readme)
    nested_worklist = package.spec_dir / "data" / "TODO.md"
    nested_worklist.parent.mkdir()
    nested_worklist.write_text("- [ ] hidden work\n", encoding="utf-8")
    clear_run_cache()
    ok, messages = run(synthetic_repo)
    assert not ok
    assert any(("parallel worklist is forbidden" in message for message in messages))
    nested_worklist.unlink()
    clear_run_cache()
    ok, messages = run(synthetic_repo)
    assert ok, messages


def test_run_caching_and_clear_cache(synthetic_repo: Path) -> None:
    clear_run_cache()
    ok1, msgs1 = run(synthetic_repo)
    assert not ok1
    assert synthetic_repo.resolve() in cpc._RUN_CACHE
    cached_ok, cached_msgs = cpc._RUN_CACHE[synthetic_repo.resolve()]
    assert cached_ok == ok1
    assert cached_msgs == msgs1
    ok2, msgs2 = run(synthetic_repo)
    assert (ok1, msgs1) == (ok2, msgs2)
    clear_run_cache()
    assert synthetic_repo.resolve() not in cpc._RUN_CACHE
    ok3, msgs3 = run(synthetic_repo, use_cache=False)
    assert (ok1, msgs1) == (ok3, msgs3)


def test_discover_and_run_pass_for_clean_package(synthetic_repo: Path) -> None:
    _write_package(
        _src(synthetic_repo), "clean", klass="infra", all_names=["K"], interface=["K"]
    )
    discovered = discover_packages(synthetic_repo)
    assert {p.name for p in discovered} == {"clean"}
    ok, messages = run(synthetic_repo)
    assert ok is True
    assert any(("clean (class infra)" in m for m in messages))


def test_run_fails_for_dirty_package(synthetic_repo: Path) -> None:
    _write_package(
        _src(synthetic_repo),
        "dirty",
        klass="infra",
        all_names=["A", "B"],
        interface=["A"],
    )
    ok, messages = run(synthetic_repo)
    assert ok is False
    assert any(("interface != __all__" in m for m in messages))


def test_run_reports_dependency_cycle(synthetic_repo: Path) -> None:
    _write_package(
        _src(synthetic_repo),
        "cycX",
        klass="infra",
        all_names=["X"],
        interface=["X"],
        depends_on=["cycY"],
    )
    _write_package(
        _src(synthetic_repo),
        "cycY",
        klass="infra",
        all_names=["Y"],
        interface=["Y"],
        depends_on=["cycX"],
    )
    ok, messages = run(synthetic_repo)
    assert ok is False
    assert any(("dependency cycle" in m for m in messages))


def test_main_passes_on_clean_repo(
    synthetic_repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _write_package(
        _src(synthetic_repo), "clean", klass="infra", all_names=["K"], interface=["K"]
    )
    rc = main(["--repo-root", str(synthetic_repo)])
    assert rc == 0
    assert "PASSED" in capsys.readouterr().out


def test_main_fails_on_dirty_repo(
    synthetic_repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _write_package(
        _src(synthetic_repo),
        "dirty",
        klass="infra",
        all_names=["A", "B"],
        interface=["A"],
    )
    rc = main(["--repo-root", str(synthetic_repo)])
    assert rc == 1
    assert "FAILED" in capsys.readouterr().out


def test_main_fails_on_empty_repo(
    synthetic_repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc = main(["--repo-root", str(synthetic_repo)])
    assert rc == 1
    assert "no packages discovered" in capsys.readouterr().out


def _ac(**overrides: object) -> ACRecord:
    kwargs: dict[str, object] = {
        "id": "AC1.1.1",
        "statement": "s",
        "test": "t::f",
        "priority": "P0",
        "status": "open",
    }
    kwargs.update(overrides)
    return ACRecord.model_validate(kwargs)


def _pkg(**overrides: object) -> PackageContract:
    kwargs: dict[str, object] = {
        "name": "p",
        "klass": "infra",
        "depends_on": [],
        "interface": [],
        "events": [],
        "invariants": [],
        "roadmap": [],
        "status": "active",
        "tier": "CODE-ONLY",
    }
    kwargs.update(overrides)
    return PackageContract.model_validate(kwargs)


def test_active_package_must_declare_a_tier() -> None:
    for status in ("active", "deprecated"):
        with pytest.raises(ValidationError):
            _pkg(status=status, tier=None)
    draft = _pkg(status="draft", tier=None)
    assert draft.tier is None


def test_package_proof_kind_must_satisfy_the_tier_matrix() -> None:
    for tier in ("LLM-LED", "LLM-ONLY"):
        with pytest.raises(ValidationError):
            _pkg(tier=tier, roadmap=[_ac(proof_kind="exact")])
    for _m5_tier, _m5_expected in TIER_DEFAULT_PROOF_KIND.items():
        if _m5_tier == "HU":
            continue
        _m5_pkg = _pkg(tier=_m5_tier, roadmap=[_ac()])
        assert _m5_pkg.roadmap[0].proof_kind == _m5_expected
        assert _m5_pkg.roadmap[0].proof_kind in TIER_VALID_PROOF_KINDS[_m5_tier]
    "AC-meta.public-boundary.2"
    "AC-meta.public-boundary.2"
    _m6_declared = sorted(
        (
            (_m6_package.name, _m6_boundary.symbol)
            for _m6_package in discover_packages(REPO)
            for _m6_boundary in _m6_package.contract.command_boundaries
        )
    )
    assert {
        ("extraction", "ReviewedStatementEnvelopeCommand"),
        ("ledger", "AnchoredJournalCommand"),
    } <= set(_m6_declared)
    for _m6_name, _m6_symbol in _m6_declared:
        _m6_package = next(
            (_m6_p for _m6_p in discover_packages(REPO) if _m6_p.name == _m6_name)
        )
        assert _m6_package.impl_dir is not None
        assert len(cpc._command_definitions(_m6_package.impl_dir, _m6_symbol)) == 1
        assert check_single_package(_m6_name, REPO)[0]


def test_check_single_package_passes_for_clean_package(synthetic_repo: Path) -> None:
    _write_package(
        _src(synthetic_repo), "clean", klass="infra", all_names=["K"], interface=["K"]
    )
    ok, messages = check_single_package("clean", synthetic_repo)
    assert ok
    assert any(("clean" in msg and "OK" in msg for msg in messages))


def test_check_single_package_reports_missing_package(synthetic_repo: Path) -> None:
    ok, messages = check_single_package("nonexistent", synthetic_repo)
    assert not ok
    assert any(("not discovered" in msg for msg in messages))


REPO = Path(__file__).resolve().parents[2]


def _command_package(
    repo: Path, body: str, *, symbol: str = "Cmd"
) -> DiscoveredPackage:
    return _write_package(
        repo,
        "commands",
        klass="domain",
        all_names=[symbol],
        interface=[symbol],
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
    assert any((expected in e for e in errors)), errors


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
        (
            "exactly one top-level definition" in e and f"found {found}" in e
            for e in errors
        )
    ), errors


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
        """
        @vo|base/types.py|Alpha Beta
        RepoUnit|repo|base/repo.py|extension/repo.py|custom.repo
        """,
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
        """
        @$t/test_demo.py
        inv-1|First invariant.|test_one
        @-
        inv-2|Second invariant.|$be/demo/test_two.py::test_two
        """
    )
    assert [(i.id, i.test) for i in built_invs] == [
        ("inv-1", "tests/tooling/test_demo.py::test_one"),
        ("inv-2", "apps/backend/tests/demo/test_two.py::test_two"),
    ]

    built_rels = rels("demo", "audit|published-language|Uses audit money types.")
    assert len(built_rels) == 1
    assert (built_rels[0].provider, built_rels[0].consumer) == ("audit", "demo")

    built_concepts = concepts(
        "demo_concept|common/demo/readme.md|Demo concept.|vision.md|tests/tooling/test_demo.py|demo|concept"
    )
    assert built_concepts[0].key == "demo_concept"
    assert built_concepts[0].cross_refs == ["vision.md"]

    with pytest.raises(ValueError, match="malformed AC table row"):
        acs("demo", "1.1|missing-test-column")

    runtime_acs = acs(
        "demo",
        suite("$t/test_suite.py", ("2.1", "Suite row.", "test_s"), priority="P2"),
    )
    assert runtime_acs[0].id == "AC-demo.2.1"
    assert runtime_acs[0].test == "tests/tooling/test_suite.py::test_s"

    contract_src = textwrap.dedent(
        '''
        from common.meta.package_contract import PackageContract, acs, suite

        CONTRACT = PackageContract(
            name="demo",
            klass="infra",
            status="active",
            tier="CODE-LED",
            depends_on=[],
            interface=[],
            events=[],
            invariants=[],
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
    )
    contract_file = tmp_path / "contract.py"
    contract_file.write_text(contract_src, encoding="utf-8")

    ast_meta = package_contract_meta(contract_file)
    assert ast_meta is not None
    assert (ast_meta["name"], ast_meta["tier"]) == ("demo", "CODE-LED")
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
