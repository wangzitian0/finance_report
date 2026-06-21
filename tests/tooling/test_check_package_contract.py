"""Failure-path coverage for ``common.governance.check_package_contract``.

``test_counter_package.py`` proves the gate is GREEN for the live ``counter``
package (the happy path). This module drives the gate's *negative* branches —
interface drift, unresolved test refs, and forbidden dependency edges — plus the
``main`` CLI, against synthetic packages built in a tmp repo. Keeping these here
means the governance gate that the whole package model relies on is itself
proven to fail loudly when a contract is violated.

These are SSOT/code-contract hardening tests (they protect the package-model
governance gate). They are classified, not AC-owned, in
``docs/analysis/traceability-exceptions.md``.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

import common.governance.check_package_contract as cpc
from common.governance.check_package_contract import (
    DiscoveredPackage,
    _package_all,
    _resolve_test,
    check_package,
    discover_packages,
    main,
    run,
)
from common.governance.package_contract import ACRecord, Invariant, PackageContract


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
        depends_on=depends_on or [],
        interface=interface,
        events=[],
        invariants=invariants or [],
        roadmap=roadmap or [],
        implementations={"be": impl_rel, "fe": None},
    )
    spec_dir = repo_root / "common" / name
    spec_dir.mkdir(parents=True)
    (spec_dir / "contract.py").write_text(
        textwrap.dedent(
            f"""
            from common.governance.package_contract import PackageContract
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


# --- (a) interface vs __all__ -------------------------------------------------


def test_interface_must_equal_all_passes_when_aligned(synthetic_repo: Path) -> None:
    pkg = _write_package(
        _src(synthetic_repo),
        "aligned",
        klass="kernel",
        all_names=["A", "B"],
        interface=["B", "A"],
    )
    assert check_package(pkg, {"aligned": "kernel"}, synthetic_repo) == []


def test_interface_mismatch_is_reported(synthetic_repo: Path) -> None:
    pkg = _write_package(
        _src(synthetic_repo),
        "drift",
        klass="kernel",
        all_names=["A", "B"],
        interface=["A"],
    )
    errors = check_package(pkg, {"drift": "kernel"}, synthetic_repo)
    assert any("interface != __all__" in e for e in errors)


# --- (b) invariant / roadmap test refs ---------------------------------------


def test_unresolved_invariant_and_roadmap_refs_are_reported(
    synthetic_repo: Path,
) -> None:
    pkg = _write_package(
        _src(synthetic_repo),
        "refs",
        klass="kernel",
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
    errors = check_package(pkg, {"refs": "kernel"}, synthetic_repo)
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


# --- (c) forbidden dependency edges ------------------------------------------


def test_upward_edge_is_forbidden(synthetic_repo: Path) -> None:
    src = _src(synthetic_repo)
    # a 'platform' package importing a 'core' package -> upward edge.
    pkg = _write_package(
        src,
        "platlow",
        klass="platform",
        all_names=["P"],
        interface=["P"],
        depends_on=["corehigh"],
        extra_module=("uses.py", "from src.corehigh import thing  # noqa\n"),
    )
    errors = check_package(
        pkg, {"platlow": "platform", "corehigh": "core"}, synthetic_repo
    )
    assert any("upward/sideways import of 'corehigh'" in e for e in errors)


def test_undeclared_sideways_edge_is_forbidden(synthetic_repo: Path) -> None:
    src = _src(synthetic_repo)
    # core importing a lower 'kernel' package that is NOT in depends_on.
    pkg = _write_package(
        src,
        "coreundeclared",
        klass="core",
        all_names=["C"],
        interface=["C"],
        depends_on=[],  # kerneldep deliberately omitted
        extra_module=("uses.py", "import src.kerneldep\n"),
    )
    errors = check_package(
        pkg, {"coreundeclared": "core", "kerneldep": "kernel"}, synthetic_repo
    )
    assert any("not in" in e and "depends_on" in e for e in errors)


def test_declared_downward_edge_is_allowed(synthetic_repo: Path) -> None:
    src = _src(synthetic_repo)
    pkg = _write_package(
        src,
        "coreok",
        klass="core",
        all_names=["C"],
        interface=["C"],
        depends_on=["kerneldep"],
        extra_module=(
            "uses.py",
            "import src.kerneldep\nimport os  # non-src import ignored\n",
        ),
    )
    errors = check_package(
        pkg, {"coreok": "core", "kerneldep": "kernel"}, synthetic_repo
    )
    assert errors == []


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


def test_discover_and_run_pass_for_clean_package(synthetic_repo: Path) -> None:
    _write_package(
        _src(synthetic_repo), "clean", klass="kernel", all_names=["K"], interface=["K"]
    )
    discovered = discover_packages(synthetic_repo)
    assert {p.name for p in discovered} == {"clean"}
    ok, messages = run(synthetic_repo)
    assert ok is True
    assert any("clean (class kernel)" in m for m in messages)


def test_run_fails_for_dirty_package(synthetic_repo: Path) -> None:
    _write_package(
        _src(synthetic_repo),
        "dirty",
        klass="kernel",
        all_names=["A", "B"],
        interface=["A"],
    )
    ok, messages = run(synthetic_repo)
    assert ok is False
    assert any("interface != __all__" in m for m in messages)


# --- main CLI -----------------------------------------------------------------


def test_main_passes_on_clean_repo(
    synthetic_repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _write_package(
        _src(synthetic_repo), "clean", klass="kernel", all_names=["K"], interface=["K"]
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
        klass="kernel",
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
