"""meta package — the DDD building-block layering, proven.

These tests anchor the meta package's structural invariants (it converges into
``base`` / ``extension`` / ``data`` and its base stays pure) and its roadmap ACs
(the governance gate enforces the building-block table: kind -> layer placement,
the repository port/adapter split, and the data-as-sink rule), plus the purity of
the ``data`` projection.

They drive the gate (``common.meta.extension.check_package_contract``) against
synthetic packages built in a tmp dir, exactly like
``test_check_package_contract.py``, so the rules are proven to FAIL loudly when a
contract violates them — and to stay additive (skipped) for packages that have not
adopted the physical split.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

import common.meta.extension.check_package_contract as cpc
from common.meta import (
    ACRecord,
    Kind,
    PackageContract,
    Unit,
    contract_index,
)
from common.meta.extension.check_package_contract import DiscoveredPackage

REPO = Path(__file__).resolve().parents[2]
META = REPO / "common/meta"


def _imported_modules(path: Path) -> set[str]:
    mods: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.ImportFrom) and node.module:
            mods.add(node.module)
        elif isinstance(node, ast.Import):
            mods.update(a.name for a in node.names)
    return mods


def _contract(name: str, **overrides: object) -> PackageContract:
    kwargs: dict[str, object] = {
        "name": name,
        "klass": "kernel",
        "tier": "CODE-ONLY",
        "depends_on": [],
        "interface": [],
        "events": [],
        "invariants": [],
        "roadmap": [],
        "units": [],
    }
    kwargs.update(overrides)
    return PackageContract(**kwargs)  # type: ignore[arg-type]


def _make_pkg(
    tmp: Path,
    name: str,
    *,
    units: list[Unit],
    layered: bool = True,
    extra_files: dict[str, str] | None = None,
) -> DiscoveredPackage:
    """Materialize a synthetic package at ``apps/backend/src/<name>`` (importable
    as ``src.<name>``) with optional ``base/``+``extension/`` layers and units."""
    impl = tmp / "apps/backend/src" / name
    impl.mkdir(parents=True)
    (impl / "__init__.py").write_text("__all__ = []\n", encoding="utf-8")
    if layered:
        for layer in ("base", "extension"):
            (impl / layer).mkdir()
            (impl / layer / "__init__.py").write_text("", encoding="utf-8")
    for rel, content in (extra_files or {}).items():
        path = impl / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    contract = _contract(
        name,
        units=units,
        implementations={"be": f"apps/backend/src/{name}", "fe": None},
    )
    return DiscoveredPackage(
        name=name, spec_dir=tmp / "common" / name, impl_dir=impl, contract=contract
    )


# --- structural invariants about meta itself ---------------------------------


def test_meta_converges_by_layer():
    """Invariant meta-converges-by-layer: base/ (model) + extension/ (gate) + data/ (projection)."""
    assert (META / "base/package_contract.py").exists()
    assert (META / "extension/check_package_contract.py").exists()
    assert (META / "data/projection.py").exists()
    exports = (META / "__init__.py").read_text(encoding="utf-8")
    for name in ("PackageContract", "Kind", "Unit", "contract_index"):
        assert name in exports, f"meta must export {name}"


def test_meta_base_is_pure():
    """Invariant meta-base-is-pure: base/ never imports its own extension/ or data/."""
    offenders: dict[str, set[str]] = {}
    for path in sorted((META / "base").rglob("*.py")):
        bad = {
            m
            for m in _imported_modules(path)
            if m.startswith("common.meta.extension")
            or m.startswith("common.meta.data")
            or "sqlalchemy" in m
        }
        if bad:
            offenders[str(path.relative_to(META))] = bad
    assert not offenders, f"meta base/ reaches into extension/data/ORM: {offenders}"


# --- gate behavior: the building-block table (roadmap ACs) --------------------


def test_AC_meta_kind_1_unit_misplacement_is_rejected(tmp_path: Path):
    """AC-meta.kind.1: a unit whose module sits in the wrong layer is rejected (A)."""
    bad = _make_pkg(
        tmp_path,
        "misplaced",
        units=[Unit(name="V", kind=Kind.VALUE_OBJECT, module="extension/v.py")],
        extra_files={"extension/v.py": "V = 1\n"},
    )
    offenders = cpc._check_kind_placement(bad)
    assert any("belongs in 'base/'" in o for o in offenders), offenders
    # a right-layer unit whose declared module file is missing is also reported.
    missing = _make_pkg(
        tmp_path,
        "missingmod",
        units=[Unit(name="V", kind=Kind.VALUE_OBJECT, module="base/ghost.py")],
    )
    assert any("does not exist" in o for o in cpc._check_kind_placement(missing))
    # correct placement passes; a unit with no module (taxonomy only) is skipped.
    ok = _make_pkg(
        tmp_path,
        "placed",
        units=[
            Unit(name="V", kind=Kind.VALUE_OBJECT, module="base/v.py"),
            Unit(name="Taxonomy", kind=Kind.VALUE_OBJECT),  # no module -> skipped
        ],
        extra_files={"base/v.py": "V = 1\n"},
    )
    assert cpc._check_kind_placement(ok) == []


def test_AC_meta_kind_2_repository_requires_port_and_adapter(tmp_path: Path):
    """AC-meta.kind.2: a repository unit must split base port + extension adapter (B)."""
    bad = _make_pkg(
        tmp_path,
        "badrepo",
        units=[
            Unit(
                name="R",
                kind=Kind.REPOSITORY,
                module="base/port.py",
                impl="base/adapter.py",  # adapter must be in extension/
            )
        ],
        extra_files={"base/port.py": "P = 1\n", "base/adapter.py": "A = 1\n"},
    )
    offenders = cpc._check_kind_placement(bad)
    assert any("must live in 'extension/'" in o for o in offenders), offenders
    # a proper port/adapter split passes.
    ok = _make_pkg(
        tmp_path,
        "okrepo",
        units=[
            Unit(
                name="R",
                kind=Kind.REPOSITORY,
                module="base/port.py",
                impl="extension/sql.py",
            )
        ],
        extra_files={"base/port.py": "P = 1\n", "extension/sql.py": "A = 1\n"},
    )
    assert cpc._check_kind_placement(ok) == []


def test_AC_meta_kind_3_data_layer_is_a_sink(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """AC-meta.kind.3: nothing in base/ or extension/ may import the package's own data/."""
    monkeypatch.setattr(cpc, "REPO_ROOT", tmp_path)
    bad = _make_pkg(
        tmp_path,
        "sinky",
        units=[],
        extra_files={
            "data/projection.py": "X = 1\n",
            "base/reader.py": "from src.sinky.data.projection import X  # noqa\n",
        },
    )
    offenders = cpc._check_data_is_sink(bad)
    assert any("data is a read-model sink" in o for o in offenders), offenders
    # a package whose write side does not import data/ passes.
    clean = _make_pkg(
        tmp_path, "cleansink", units=[], extra_files={"data/projection.py": "X = 1\n"}
    )
    assert cpc._check_data_is_sink(clean) == []


def test_AC_meta_projection_1_contract_index_is_pure(tmp_path: Path):
    """AC-meta.projection.1: contract_index is a pure projection over its inputs."""
    a = _contract(
        "a", units=[Unit(name="V", kind=Kind.VALUE_OBJECT, module="base/v.py")]
    )
    b = _contract(
        "b",
        klass="platform",
        depends_on=["a"],
        roadmap=[
            ACRecord(
                id="AC-b.1.1", statement="s", test="t::f", priority="P0", status="done"
            )
        ],
        units=[
            Unit(
                name="R",
                kind=Kind.REPOSITORY,
                module="base/p.py",
                impl="extension/s.py",
            )
        ],
    )
    idx = contract_index([a, b])
    assert idx["registry"]["a"]["klass"] == "kernel"
    assert idx["consumers"]["a"] == ["b"]
    assert idx["ac_index"]["AC-b.1.1"] == "b"
    assert idx["units_by_layer"]["a"] == {"base": 1, "extension": 0, "data": 0}
    # a repository spans both sides of the dependency inversion.
    assert idx["units_by_layer"]["b"] == {"base": 1, "extension": 1, "data": 0}
    # pure: identical inputs -> identical output, no I/O.
    assert contract_index([a, b]) == idx


def test_contract_index_rejects_duplicate_ac_id():
    """contract_index surfaces an AC id claimed by two packages, never overwrites."""
    dup = ACRecord(
        id="AC-dup.1.1", statement="s", test="t::f", priority="P0", status="done"
    )
    a = _contract("a", roadmap=[dup])
    b = _contract("b", roadmap=[dup])
    with pytest.raises(ValueError, match="claimed by two packages"):
        contract_index([a, b])


def test_AC_meta_kind_4_value_type_packages_pass(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """AC-meta.kind.4: a value-type package may declare value-object units with no
    physical split; the gate accepts it (additive) and passes."""
    monkeypatch.setattr(cpc, "REPO_ROOT", tmp_path)
    pkg = _make_pkg(
        tmp_path,
        "valpkg",
        layered=False,
        units=[Unit(name="V", kind=Kind.VALUE_OBJECT)],  # no module path
    )
    # no base/extension dirs -> placement is skipped, not failed.
    assert cpc._check_kind_placement(pkg) == []
    assert cpc.check_package(pkg, {"valpkg": "kernel"}, tmp_path) == []
