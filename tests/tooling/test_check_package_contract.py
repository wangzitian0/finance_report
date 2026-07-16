"""Failure-path coverage for ``common.meta.extension.check_package_contract``.

``test_counter_package.py`` proves the gate is GREEN for the live ``counter``
package (the happy path). This module drives the gate's *negative* branches —
interface drift, unresolved test refs, and forbidden dependency edges — plus the
``main`` CLI, against synthetic packages built in a tmp repo. Keeping these here
means the governance gate that the whole package model relies on is itself
proven to fail loudly when a contract is violated.

These are SSOT/code-contract hardening tests (they protect the package-model
governance gate). They are classified, not AC-owned, in
``docs/project/traceability-exceptions.md``.
"""

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
    discover_packages,
    main,
    run,
)
from pydantic import ValidationError

from common.meta.package_contract import (
    TIER_DEFAULT_PROOF_KIND,
    TIER_VALID_PROOF_KINDS,
    ACRecord,
    Invariant,
    PackageContract,
)


def _write_package(
    repo_root: Path,
    name: str,
    *,
    klass: str,
    all_names: list[str],
    interface: list[str],
    depends_on: list[str] | None = None,
    invariants: list[Invariant] | None = None,
    roadmap: list[ACRecord] | None = None,
    extra_module: tuple[str, str] | None = None,
    tier: str = "CODE-ONLY",
    status: str = "active",
) -> DiscoveredPackage:
    """Materialize a package in the package model: a ``common/<name>/contract.py``
    spec pointing at a BE implementation under ``apps/backend/src/<name>``.

    The implementation dir holds the ``__init__.py`` (whose ``__all__`` the gate
    checks against ``interface``) and any ``extra_module`` used to drive the
    dependency-edge scan.
    """
    impl_rel = f"apps/backend/src/{name}"
    impl_dir = repo_root / impl_rel
    impl_dir.mkdir(parents=True)
    all_literal = ", ".join(repr(n) for n in all_names)
    (impl_dir / "__init__.py").write_text(
        f"__all__ = [{all_literal}]\n", encoding="utf-8"
    )
    if extra_module is not None:
        mod_name, mod_body = extra_module
        (impl_dir / mod_name).write_text(mod_body, encoding="utf-8")

    contract = PackageContract(
        name=name,
        klass=klass,  # type: ignore[arg-type]
        tier=tier,  # type: ignore[arg-type]
        status=status,  # type: ignore[arg-type]
        depends_on=depends_on or [],
        interface=interface,
        events=[],
        invariants=invariants or [],
        roadmap=roadmap or [],
        implementations={"be": impl_rel, "fe": None},
    )
    spec_dir = repo_root / "common" / name
    spec_dir.mkdir(parents=True)
    (spec_dir / "readme.md").write_text(f"# {name}\n", encoding="utf-8")
    (spec_dir / "contract.py").write_text(
        textwrap.dedent(
            f"""
            from common.meta.package_contract import PackageContract
            CONTRACT = PackageContract.model_validate({contract.model_dump()!r})
            """
        ),
        encoding="utf-8",
    )
    return DiscoveredPackage(
        name=name, spec_dir=spec_dir, impl_dir=impl_dir, contract=contract
    )


@pytest.fixture
def synthetic_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A throwaway repo root with ``common/`` + ``apps/backend/src`` and
    ``REPO_ROOT`` patched.

    Patching the module-level ``REPO_ROOT`` is required because
    ``_check_no_forbidden_edge`` computes ``py.relative_to(REPO_ROOT)`` for its
    offender messages; without it, scanning files under ``tmp_path`` raises.
    """
    monkeypatch.setattr(cpc, "REPO_ROOT", tmp_path)
    (tmp_path / "apps" / "backend" / "src").mkdir(parents=True)
    (tmp_path / "common").mkdir(parents=True)
    return tmp_path


def _src(repo: Path) -> Path:
    """The repo root: ``_write_package`` now derives both spec and impl dirs."""
    return repo


# --- implementations["be"] path containment ----------------------------------


def test_contained_impl_dir_accepts_repo_relative(tmp_path: Path) -> None:
    resolved = cpc._contained_impl_dir("apps/backend/src/counter", tmp_path)
    assert resolved == (tmp_path / "apps" / "backend" / "src" / "counter").resolve()


def test_contained_impl_dir_allows_repo_root_itself(tmp_path: Path) -> None:
    # The meta package points its BE implementation at common/meta, a
    # normal repo-relative path; the root itself is also accepted.
    assert cpc._contained_impl_dir(".", tmp_path) == tmp_path.resolve()


def test_contained_impl_dir_rejects_absolute_path(tmp_path: Path) -> None:
    assert cpc._contained_impl_dir("/etc", tmp_path) is None


def test_contained_impl_dir_rejects_escape(tmp_path: Path) -> None:
    assert cpc._contained_impl_dir("../../outside", tmp_path) is None


def test_contained_impl_dir_none_for_missing(tmp_path: Path) -> None:
    assert cpc._contained_impl_dir(None, tmp_path) is None


def test_escaping_be_path_reported_not_crashed(synthetic_repo: Path) -> None:
    """A contract whose implementations['be'] escapes the repo is reported as a
    violation (interface with no __all__ to check), never a crash."""
    pkg = _write_package(
        _src(synthetic_repo),
        "escaper",
        klass="infra",
        all_names=["E"],
        interface=["E"],
    )
    # Re-point the discovered package's BE impl outside the repo.
    pkg = cpc.DiscoveredPackage(
        name=pkg.name,
        spec_dir=pkg.spec_dir,
        impl_dir=cpc._contained_impl_dir("../escape", synthetic_repo),
        contract=pkg.contract,
    )
    errors = cpc.check_package(pkg, {"escaper": "infra"}, synthetic_repo)
    assert any("implementations['be'] is missing" in e for e in errors)


# --- (a) interface vs __all__ -------------------------------------------------


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
    assert any("interface != __all__" in e for e in errors)


def test_duplicate_public_function_exports_are_rejected(
    synthetic_repo: Path,
) -> None:
    """The contract gate rejects two packages claiming one function name."""
    for name in ("first", "second"):
        _write_package(
            _src(synthetic_repo),
            name,
            klass="infra",
            all_names=["shared_function"],
            interface=["shared_function"],
        )

    ok, messages = run(synthetic_repo)

    assert not ok
    assert any(
        "public function 'shared_function' is exported by multiple packages" in message
        for message in messages
    )


def test_repeated_public_function_in_one_package_is_not_multi_owner(
    synthetic_repo: Path,
) -> None:
    """Repeated declarations do not invent a second package owner."""
    _write_package(
        _src(synthetic_repo),
        "single",
        klass="infra",
        all_names=["one_function", "one_function"],
        interface=["one_function", "one_function"],
    )

    ok, messages = run(synthetic_repo)

    assert ok, messages


# --- (b) invariant / roadmap test refs ---------------------------------------


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
    assert any("invariant 'INV1'" in e for e in errors)
    assert any("roadmap 'AC1'" in e for e in errors)


def test_resolve_test_branches(synthetic_repo: Path) -> None:
    test_dir = synthetic_repo / "t"
    test_dir.mkdir()
    (test_dir / "test_ok.py").write_text(
        "def test_real():\n    pass\n\nasync def test_async_real():\n    pass\n",
        encoding="utf-8",
    )
    # malformed ref (no '::')
    assert _resolve_test("t/test_ok.py", synthetic_repo) is not None
    # missing file
    assert _resolve_test("t/missing.py::test_real", synthetic_repo) is not None
    # file exists, func missing
    assert _resolve_test("t/test_ok.py::test_absent", synthetic_repo) is not None
    # resolves: sync and async functions both count
    assert _resolve_test("t/test_ok.py::test_real", synthetic_repo) is None
    assert _resolve_test("t/test_ok.py::test_async_real", synthetic_repo) is None


# --- (b2) frontend (vitest/Playwright) test refs (#1820) ---------------------
#
# A roadmap/invariant `test=` ref may also point at a `*.test.ts`/`*.test.tsx`/
# `*.spec.ts`/`*.spec.tsx` file. TS has no Python AST, so this resolves by file
# existence + the test name matching a real `it(...)`/`test(...)` declaration —
# the same "does a real declaration with this title exist" proof strength as
# the Python branch, no stronger claim (no TS parse/compile check). The fixture
# content below is deliberately NOT valid Python (curly-brace imports, arrow
# functions, template literals) so a regression that still routes `.test.ts`
# through `ast.parse` fails LOUDLY (a crash), not silently.


def _write_ts_test_file(path: Path) -> None:
    path.write_text(
        textwrap.dedent(
            """
            import { describe, expect, it, test } from "vitest";

            describe("money conformance", () => {
              it("AC-audit.20.2 real vitest test", () => {
                expect(1 + 1).toBe(2);
              });

              test("a real test() declaration", () => {
                expect(true).toBe(true);
              });

              test.only(`a template-literal title with ${1 + 1} inlined`, () => {
                expect(true).toBe(true);
              });
            });
            """
        ),
        encoding="utf-8",
    )


def test_resolve_test_frontend_branches(synthetic_repo: Path) -> None:
    test_dir = synthetic_repo / "apps" / "frontend" / "src"
    test_dir.mkdir(parents=True)
    ts_file = test_dir / "money.test.ts"
    _write_ts_test_file(ts_file)
    rel = "apps/frontend/src/money.test.ts"

    # missing file
    assert (
        _resolve_test("apps/frontend/src/missing.test.ts::x", synthetic_repo)
        is not None
    )
    # file exists, name absent -> reported, not a crash
    err = _resolve_test(f"{rel}::no such test", synthetic_repo)
    assert err is not None and "not found" in err
    # resolves: `it(...)`, `test(...)`, and `test.only(...)` all count
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
    """``.test.tsx`` / ``.spec.ts`` / ``.spec.tsx`` all take the frontend branch."""
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
    """A TS ref to a nonexistent file, and one to a real file with an absent test
    name, are both reported by ``check_package`` — not a crash, not a silent
    pass."""
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
        "roadmap 'AC1'" in e and "test file does not exist" in e for e in errors
    ), errors

    # Real file, absent test name.
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
    assert any("roadmap 'AC2'" in e and "not found" in e for e in errors2), errors2


def test_resolved_frontend_roadmap_ref_passes(synthetic_repo: Path) -> None:
    """A TS ref to a real ``it(...)`` title resolves — no roadmap error."""
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
    assert not any("roadmap 'AC1'" in e for e in errors), errors


# --- (c) forbidden dependency edges ------------------------------------------


def test_upward_edge_is_forbidden(synthetic_repo: Path) -> None:
    src = _src(synthetic_repo)
    # a 'platform' package importing a 'core' package -> upward edge.
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
    assert any("upward import of 'corehigh'" in e for e in errors)


def test_undeclared_sideways_edge_is_forbidden(synthetic_repo: Path) -> None:
    src = _src(synthetic_repo)
    # core importing a lower 'kernel' package that is NOT in depends_on.
    pkg = _write_package(
        src,
        "coreundeclared",
        klass="domain",
        all_names=["C"],
        interface=["C"],
        depends_on=[],  # kerneldep deliberately omitted
        extra_module=("uses.py", "import src.kerneldep\n"),
    )
    errors = check_package(
        pkg, {"coreundeclared": "domain", "kerneldep": "infra"}, synthetic_repo
    )
    assert any("not in" in e and "depends_on" in e for e in errors)


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
    # a kernel package importing another kernel package it declares -> allowed
    # (sideways + acyclic). "never up, never sideways-cyclic".
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


# --- (c2) unused dependency declarations (contract-honesty gate, #1674) ------
#
# _check_no_forbidden_edge only ever caught an import missing its declaration.
# The reverse — a depends_on entry with zero real imports — was invisible, so
# contracts drifted to describe the *target* design instead of current reality
# (16 such edges found across the repo in the 2026-07-09 audit). An ACTIVE
# package with a real implementation must keep the declared graph honest; a
# DRAFT package (or one with no implementation yet) is allowed to describe
# where it's going before the code catches up.


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
        depends_on=["kernB"],  # declared but never imported below
    )
    errors = check_package(pkg, {"kernA": "infra", "kernB": "infra"}, synthetic_repo)
    assert any("kernB" in e and "no import" in e for e in errors), errors


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
    assert not any("no import" in e for e in errors), errors


def test_used_dependency_declaration_has_no_unused_violation(
    synthetic_repo: Path,
) -> None:
    """A declared edge with a real import must not be flagged 'unused' — this
    is the companion happy path to the two tests above."""
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
    assert not any("no import" in e for e in errors), errors


# --- (c3) common.<pkg> imports must be scanned too (#1674) -------------------
#
# common-implemented packages (meta/config/testing) are importable as
# common.<name>, not src.<name>. The pre-fix scan only ever recognised the
# src. prefix, so a real edge between two common-implemented packages was
# invisible to both the undeclared-edge check and the new unused check.


def test_common_prefix_edge_is_detected_as_undeclared(synthetic_repo: Path) -> None:
    src = _src(synthetic_repo)
    low_dir = src / "common" / "commonlow"
    low_dir.mkdir(parents=True)
    (low_dir / "__init__.py").write_text("__all__ = ['L']\n", encoding="utf-8")
    low_contract = PackageContract(
        name="commonlow",
        klass="infra",  # type: ignore[arg-type]
        tier="CODE-ONLY",  # type: ignore[arg-type]
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
        klass="infra",  # type: ignore[arg-type]
        tier="CODE-ONLY",  # type: ignore[arg-type]
        depends_on=[],  # undeclared on purpose
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
    assert any("commonlow" in e and "depends_on" in e for e in errors), errors


def test_dependency_cycle_is_forbidden(synthetic_repo: Path) -> None:
    src = _src(synthetic_repo)
    # two same-class packages depending on each other -> a cycle, rejected globally.
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
    assert any("dependency cycle" in e for e in offenders), offenders


def test_base_layer_must_not_import_own_extension(synthetic_repo: Path) -> None:
    # a package split into base/ + extension/ where base reaches into its own
    # extension/ -> rejected (base must stay pure; edges live in extension).
    pkg = _write_package(
        _src(synthetic_repo), "layered", klass="infra", all_names=["L"], interface=["L"]
    )
    impl = pkg.impl_dir
    (impl / "base").mkdir()
    (impl / "extension").mkdir()
    (impl / "extension" / "sql.py").write_text("X = 1\n", encoding="utf-8")
    # cover all the import forms that reach the package's own extension/:
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
    # each offender is "<path>: <message>"; take the path part, then its basename
    # (the message itself contains "extension/", so split on ":" before "/").
    flagged = {o.split(":")[0].split("/")[-1] for o in offenders}
    assert {"abs_dotted.py", "abs_pkg.py", "abs_import.py", "rel.py"} <= flagged, (
        offenders
    )
    # a package without the two-layer split is skipped (additive).
    plain = _write_package(
        _src(synthetic_repo), "plain", klass="infra", all_names=["P"], interface=["P"]
    )
    assert cpc._check_layer_purity(plain) == []


# --- discover_packages / run / _package_all ----------------------------------


def test_package_all_handles_missing_dunder(synthetic_repo: Path) -> None:
    pkg_dir = _src(synthetic_repo) / "nodunder"
    pkg_dir.mkdir(parents=True)
    (pkg_dir / "__init__.py").write_text("x = 1\n", encoding="utf-8")
    assert _package_all(pkg_dir) == []


def test_package_all_tolerates_non_literal_all(synthetic_repo: Path) -> None:
    """A computed ``__all__`` is not statically readable -> [] (never a crash)."""
    pkg_dir = _src(synthetic_repo) / "computed"
    pkg_dir.mkdir(parents=True)
    (pkg_dir / "__init__.py").write_text(
        "__all__ = sorted(['B', 'A'])\n", encoding="utf-8"
    )
    assert _package_all(pkg_dir) == []


def test_run_reports_no_packages_when_empty(synthetic_repo: Path) -> None:
    ok, messages = run(synthetic_repo)
    assert ok is False
    assert any("no packages discovered" in m for m in messages)


def test_AC_meta_package_truth_1_authored_surface_is_exact_and_non_vacuous(
    synthetic_repo: Path,
) -> None:
    """AC-meta.package-truth.1 rejects missing owners and parallel worklists."""
    ok, messages = run(synthetic_repo)
    assert not ok
    assert any("no packages discovered" in message for message in messages)

    package = _write_package(
        _src(synthetic_repo),
        "truthful",
        klass="infra",
        all_names=["K"],
        interface=["K"],
    )
    package_readme = package.spec_dir / "readme.md"
    package_readme.unlink()
    ok, messages = run(synthetic_repo)
    assert not ok
    assert any(
        "missing required authored surface: readme.md" in message
        for message in messages
    )

    package_readme.write_text("# truthful\n", encoding="utf-8")
    wrong_case_readme = package.spec_dir / "README.md"
    package_readme.rename(wrong_case_readme)
    ok, messages = run(synthetic_repo)
    assert not ok
    assert any(
        "missing required authored surface: readme.md" in message
        for message in messages
    )

    wrong_case_readme.rename(package_readme)
    nested_worklist = package.spec_dir / "data" / "TODO.md"
    nested_worklist.parent.mkdir()
    nested_worklist.write_text("- [ ] hidden work\n", encoding="utf-8")
    ok, messages = run(synthetic_repo)
    assert not ok
    assert any("parallel worklist is forbidden" in message for message in messages)

    nested_worklist.unlink()
    ok, messages = run(synthetic_repo)
    assert ok, messages


def test_discover_and_run_pass_for_clean_package(synthetic_repo: Path) -> None:
    _write_package(
        _src(synthetic_repo), "clean", klass="infra", all_names=["K"], interface=["K"]
    )
    discovered = discover_packages(synthetic_repo)
    assert {p.name for p in discovered} == {"clean"}
    ok, messages = run(synthetic_repo)
    assert ok is True
    assert any("clean (class infra)" in m for m in messages)


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
    assert any("interface != __all__" in m for m in messages)


def test_run_reports_dependency_cycle(synthetic_repo: Path) -> None:
    # Integration: two same-class packages depending on each other -> run() (not
    # just the helper) must surface the cycle, proving run() wires the check in.
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
    assert any("dependency cycle" in m for m in messages)


# --- main CLI -----------------------------------------------------------------


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
    """Build a roadmap ACRecord with valid defaults, overriding per test."""
    kwargs: dict[str, object] = {
        "id": "AC1.1.1",
        "statement": "s",
        "test": "t::f",
        "priority": "P0",
        "status": "open",
    }
    kwargs.update(overrides)
    return ACRecord(**kwargs)  # type: ignore[arg-type]


def _pkg(**overrides: object) -> PackageContract:
    """Build a minimal PackageContract with valid defaults, overriding per test."""
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
    return PackageContract(**kwargs)  # type: ignore[arg-type]


def test_active_package_must_declare_a_tier() -> None:
    """An active/deprecated package with an undecided tier cannot be constructed.

    Authority tier is a module-design property: a shipped package must have
    resolved it to one of CODE-ONLY/CODE-LED/LLM-LED/LLM-ONLY. The "undecided" state (the legacy ``HU``)
    is legal only while the package is still a ``draft``.
    """
    for status in ("active", "deprecated"):
        with pytest.raises(ValidationError):
            _pkg(status=status, tier=None)
    # A draft package may stay undecided (tier=None) — that is the HU state.
    draft = _pkg(status="draft", tier=None)
    assert draft.tier is None


def test_package_proof_kind_must_satisfy_the_tier_matrix() -> None:
    """A roadmap AC whose proof_kind is invalid for the PACKAGE tier is rejected.

    Enforces the tier->proof matrix at construction, against the package's tier
    (not a per-AC one): under an LLM-LED/LLM-ONLY package an AC can never claim ``exact``.
    """
    for tier in ("LLM-LED", "LLM-ONLY"):
        with pytest.raises(ValidationError):
            _pkg(tier=tier, roadmap=[_ac(proof_kind="exact")])


def test_package_ac_proof_kind_defaults_to_the_tier_canonical_kind() -> None:
    """Omitting an AC's proof_kind resolves to the package tier's canonical kind."""
    for tier, expected in TIER_DEFAULT_PROOF_KIND.items():
        if tier == "HU":  # not a permanent package tier
            continue
        pkg = _pkg(tier=tier, roadmap=[_ac()])
        assert pkg.roadmap[0].proof_kind == expected
        assert pkg.roadmap[0].proof_kind in TIER_VALID_PROOF_KINDS[tier]
