"""AC-meta.dircov.1: every common/ directory is governed or a documented exception.

``check_package_contract`` discovers packages additively (globs
``common/*/contract.py`` for a module-level ``CONTRACT = PackageContract(...)``),
so it never notices a directory with no discoverable contract -- exactly how
``common/ci``, ``common/shell``, and ``common/ssot`` accumulated as undeclared
junk drawers before the cleanup finished (#1564-#1568, #1430).
``check_package_directory_coverage`` closes that gap: it enumerates every
directory directly under ``common/`` and fails on one that ships neither a
discoverable ``CONTRACT`` nor a documented entry in ``UNGOVERNED_EXCEPTIONS``.
"""

from __future__ import annotations

from pathlib import Path

from common.meta.extension import check_package_directory_coverage as gate

REPO_ROOT = Path(__file__).resolve().parents[2]


def _make_pkg_with_contract(root: Path, name: str) -> None:
    pkg = root / "common" / name
    pkg.mkdir(parents=True)
    (pkg / "contract.py").write_text(
        "\n".join(
            [
                "from common.meta.base.package_contract import PackageContract",
                "",
                "CONTRACT = PackageContract(",
                f'    name="{name}",',
                '    klass="middleware",',
                '    status="draft",',
                "    depends_on=[],",
                "    interface=[],",
                "    events=[],",
                "    invariants=[],",
                "    roadmap=[],",
                ")",
                "",
            ]
        ),
        encoding="utf-8",
    )


def _make_bare_dir(root: Path, name: str, *, with_file: bool = True) -> None:
    pkg = root / "common" / name
    pkg.mkdir(parents=True)
    if with_file:
        (pkg / "some_tool.py").write_text("# a stray script\n", encoding="utf-8")


def test_real_repo_passes() -> None:
    """The actual repository has no ungoverned, undocumented common/ directory."""
    errors = gate.check_directory_coverage(REPO_ROOT)
    assert errors == [], "\n".join(errors)


def test_residual_exception_list_is_empty() -> None:
    """#1430: the repo no longer needs a common/ junk-drawer exception list."""
    assert gate.UNGOVERNED_EXCEPTIONS == {}


def test_directory_with_contract_passes(tmp_path: Path) -> None:
    """A directory shipping a contract.py is governed -- no error."""
    _make_pkg_with_contract(tmp_path, "widgets")
    assert gate.check_directory_coverage(tmp_path) == []


def test_contract_file_without_exported_contract_is_rejected(tmp_path: Path) -> None:
    """A contract.py that discovery cannot see must not satisfy coverage."""
    pkg = tmp_path / "common" / "widgets"
    pkg.mkdir(parents=True)
    (pkg / "contract.py").write_text("contract = object()\n", encoding="utf-8")

    errors = gate.check_directory_coverage(tmp_path)

    assert errors == [
        "common/widgets/contract.py does not export a module-level CONTRACT = "
        "PackageContract(...), so package discovery and governance cannot see it."
    ]


def test_contract_file_with_invalid_syntax_is_rejected(tmp_path: Path) -> None:
    """An unloadable contract cannot make a package appear governed."""
    pkg = tmp_path / "common" / "widgets"
    pkg.mkdir(parents=True)
    (pkg / "contract.py").write_text("CONTRACT = (\n", encoding="utf-8")

    errors = gate.check_directory_coverage(tmp_path)

    assert errors == [
        "common/widgets/contract.py does not export a module-level CONTRACT = "
        "PackageContract(...), so package discovery and governance cannot see it."
    ]


def test_contract_file_with_wrong_contract_type_is_rejected(tmp_path: Path) -> None:
    """An uppercase non-PackageContract export is still undiscoverable."""
    pkg = tmp_path / "common" / "widgets"
    pkg.mkdir(parents=True)
    (pkg / "contract.py").write_text("CONTRACT = object()\n", encoding="utf-8")

    errors = gate.check_directory_coverage(tmp_path)

    assert errors == [
        "common/widgets/contract.py does not export a module-level CONTRACT = "
        "PackageContract(...), so package discovery and governance cannot see it."
    ]


def test_annotated_contract_export_is_discoverable(tmp_path: Path) -> None:
    """An annotated module-level package contract is discoverable."""
    pkg = tmp_path / "common" / "widgets"
    pkg.mkdir(parents=True)
    (pkg / "contract.py").write_text(
        "\n".join(
            [
                "from common.meta.base.package_contract import PackageContract",
                "",
                "CONTRACT: PackageContract = PackageContract(",
                '    name="widgets",',
                '    klass="middleware",',
                '    status="draft",',
                "    depends_on=[],",
                "    interface=[],",
                "    events=[],",
                "    invariants=[],",
                "    roadmap=[],",
                ")",
                "",
            ]
        ),
        encoding="utf-8",
    )

    assert gate.check_directory_coverage(tmp_path) == []


def test_documented_exception_passes_without_contract(
    tmp_path: Path, monkeypatch
) -> None:
    """A directory named in UNGOVERNED_EXCEPTIONS passes even with no contract.py."""
    _make_bare_dir(tmp_path, "wip_domain")
    monkeypatch.setitem(
        gate.UNGOVERNED_EXCEPTIONS, "wip_domain", "test-only documented exception"
    )
    assert gate.check_directory_coverage(tmp_path) == []


def test_bare_directory_with_no_exception_is_rejected(tmp_path: Path) -> None:
    """A new junk-drawer directory with no contract.py and no exception fails."""
    _make_bare_dir(tmp_path, "random_junk")
    errors = gate.check_directory_coverage(tmp_path)
    assert len(errors) == 1
    assert "common/random_junk/" in errors[0]
    assert "contract.py" in errors[0]


def test_pycache_is_ignored(tmp_path: Path) -> None:
    """__pycache__ residue under common/ is never flagged."""
    (tmp_path / "common" / "__pycache__").mkdir(parents=True)
    assert gate.check_directory_coverage(tmp_path) == []


def test_dir_holding_only_stale_pycache_is_ignored(tmp_path: Path) -> None:
    """A deleted package can leave stale, untracked __pycache__ behind on an
    existing checkout (Python never cleans it up when the source is removed
    from git) -- exactly what happened to common/ssot/ after #1650/#1651.
    That local debris must not fail the gate for every other developer."""
    stale = tmp_path / "common" / "retired_pkg" / "sub" / "__pycache__"
    stale.mkdir(parents=True)
    (stale / "mod.cpython-312.pyc").write_bytes(b"\x00")
    assert gate.check_directory_coverage(tmp_path) == []


def test_dir_with_real_file_alongside_pycache_is_still_governed(tmp_path: Path) -> None:
    """A real package still needs a contract.py even if it also has caches."""
    _make_bare_dir(tmp_path, "half_stale")
    (tmp_path / "common" / "half_stale" / "__pycache__").mkdir()
    errors = gate.check_directory_coverage(tmp_path)
    assert len(errors) == 1
    assert errors[0].startswith("common/half_stale/")


def test_main_passes_quietly_on_real_repo(capsys) -> None:
    assert gate.main(["--repo-root", str(REPO_ROOT)]) == 0
    assert "PASSED" in capsys.readouterr().out


def test_main_fails_and_reports_on_a_junk_drawer(tmp_path: Path, capsys) -> None:
    _make_bare_dir(tmp_path, "another_junk_drawer")
    assert gate.main(["--repo-root", str(tmp_path)]) == 1
    assert "another_junk_drawer" in capsys.readouterr().err
