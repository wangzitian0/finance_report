from __future__ import annotations

import subprocess
import json
from pathlib import Path
from textwrap import dedent

import pytest

from common.meta import PackageContract, dependency_index
from common.meta.extension import check_package_contract as package_gate
from common.meta.extension import dependency_report
from common.meta.extension.dependency_report import (
    build_dependency_snapshot,
    build_impact_report,
)
from common.meta.extension.check_package_contract import discover_packages
from tools.report_ddd_dependencies import main

ROOT = Path(__file__).resolve().parents[2]


def _contract(
    name: str,
    *,
    klass: str,
    depends_on: list[str],
) -> PackageContract:
    return PackageContract(
        name=name,
        klass=klass,  # type: ignore[arg-type]
        tier="CODE-ONLY",
        depends_on=depends_on,
        interface=[],
        events=[],
        invariants=[],
        roadmap=[],
        implementations={"be": None, "fe": None},
    )


def test_AC_meta_dependency_governance_1_projection_has_typed_edges_and_transitive_consumers() -> (
    None
):
    """AC-meta.dependency-governance.1: one pure graph exposes full consumers."""

    provider = _contract("provider", klass="meta", depends_on=[])
    middle = _contract("middle", klass="infra", depends_on=["provider"])
    consumer = _contract("consumer", klass="domain", depends_on=["middle"])

    index = dependency_index([consumer, provider, middle])

    assert index == {
        "edges": [
            {
                "consumer": "consumer",
                "provider": "middle",
                "kind": "compile",
                "detail": "PackageContract.depends_on",
            },
            {
                "consumer": "middle",
                "provider": "provider",
                "kind": "compile",
                "detail": "PackageContract.depends_on",
            },
        ],
        "direct_consumers": {
            "consumer": [],
            "middle": ["consumer"],
            "provider": ["middle"],
        },
        "transitive_consumers": {
            "consumer": [],
            "middle": ["consumer"],
            "provider": ["consumer", "middle"],
        },
    }
    assert dependency_index([middle, consumer, provider]) == index

    with pytest.raises(ValueError, match="unknown package"):
        dependency_index([_contract("broken", klass="domain", depends_on=["missing"])])
    with pytest.raises(ValueError, match="duplicate package"):
        dependency_index([provider, provider])
    with pytest.raises(ValueError, match="duplicate dependency"):
        dependency_index(
            [
                provider,
                _contract(
                    "duplicate",
                    klass="domain",
                    depends_on=["provider", "provider"],
                ),
            ]
        )
    with pytest.raises(ValueError, match="cannot depend on itself"):
        dependency_index([_contract("selfish", klass="domain", depends_on=["selfish"])])
    with pytest.raises(ValueError, match="dependency cycle"):
        dependency_index(
            [
                _contract("first", klass="infra", depends_on=["second"]),
                _contract("second", klass="infra", depends_on=["first"]),
            ]
        )


def test_AC_meta_dependency_governance_1_package_gate_reuses_graph_policy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC-meta.dependency-governance.1: gate/report/projection share one engine."""

    contracts = [
        _contract("provider", klass="meta", depends_on=[]),
        _contract("consumer", klass="infra", depends_on=["provider"]),
    ]
    discovered = [
        package_gate.DiscoveredPackage(
            name=contract.name,
            spec_dir=ROOT / "common" / contract.name,
            impl_dir=None,
            contract=contract,
        )
        for contract in contracts
    ]
    seen: list[PackageContract] = []

    def build_once(values: list[PackageContract]) -> None:
        seen.extend(values)

    monkeypatch.setattr(package_gate, "build_dependency_graph", build_once)

    assert package_gate._check_no_dependency_cycle(discovered) == []
    assert seen == contracts


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dedent(content).lstrip(), encoding="utf-8")


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", repo.as_posix(), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _write_package(
    repo: Path,
    name: str,
    *,
    klass: str,
    depends_on: list[str],
    parameters: str = "value: str",
) -> None:
    impl = f"apps/backend/src/{name}"
    _write(
        repo / f"common/{name}/contract.py",
        f"""
        from common.meta.package_contract import PackageContract

        CONTRACT = PackageContract(
            name={name!r},
            klass={klass!r},
            tier="CODE-ONLY",
            depends_on={depends_on!r},
            interface=["public"],
            events=[],
            invariants=[],
            roadmap=[],
            implementations={{"be": {impl!r}, "fe": None}},
        )
        """,
    )
    _write(
        repo / f"{impl}/__init__.py",
        'from .api import public\n\n__all__ = ["public"]\n',
    )
    _write(
        repo / f"{impl}/api.py",
        f"""
        def public({parameters}) -> str:
            return value
        """,
    )


def _seed_repo(tmp_path: Path) -> tuple[Path, str]:
    repo = tmp_path / "repo"
    _write_package(repo, "provider", klass="meta", depends_on=[])
    _write_package(repo, "middle", klass="infra", depends_on=["provider"])
    _write_package(repo, "consumer", klass="domain", depends_on=["middle"])
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "dependency-test@example.invalid")
    _git(repo, "config", "user.name", "Dependency Test")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "base")
    return repo, _git(repo, "rev-parse", "HEAD")


def _write_public_types(
    repo: Path,
    *,
    constructor: str,
    enum_value: str,
) -> None:
    _write_public_surface(
        repo,
        interface=["PublicClass", "PublicEnum"],
        source=f"""
        from enum import StrEnum

        class PublicClass:
            def __init__(self, {constructor}) -> None:
                self.value = value

        class PublicEnum(StrEnum):
            FIRST = {enum_value!r}
        """,
    )


def _write_public_surface(
    repo: Path,
    *,
    interface: list[str],
    source: str,
) -> None:
    impl = "apps/backend/src/provider"
    _write(
        repo / "common/provider/contract.py",
        f"""
        from common.meta.package_contract import PackageContract

        CONTRACT = PackageContract(
            name="provider",
            klass="meta",
            tier="CODE-ONLY",
            depends_on=[],
            interface={interface!r},
            events=[],
            invariants=[],
            roadmap=[],
            implementations={{"be": {impl!r}, "fe": None}},
        )
        """,
    )
    _write(
        repo / f"{impl}/__init__.py",
        (f"from .api import {', '.join(interface)}\n\n__all__ = {interface!r}\n"),
    )
    _write(repo / f"{impl}/api.py", source)


def test_AC_meta_dependency_governance_2_impact_includes_indirect_consumers(
    tmp_path: Path,
) -> None:
    """AC-meta.dependency-governance.2: impact includes indirect consumers."""

    repo, base_ref = _seed_repo(tmp_path)
    _write_package(
        repo,
        "provider",
        klass="meta",
        depends_on=[],
        parameters="value: str, strict: bool = False",
    )
    _write_package(
        repo,
        "consumer",
        klass="domain",
        depends_on=["middle", "provider"],
    )

    report = build_impact_report(repo, base_ref=base_ref)

    assert report["errors"] == []
    assert report["added_edges"] == [
        {
            "consumer": "consumer",
            "provider": "provider",
            "kind": "compile",
            "detail": "PackageContract.depends_on",
        }
    ]
    assert report["removed_edges"] == []
    assert report["changed_public_symbols"] == [
        {
            "package": "provider",
            "symbol": "public",
            "before": (
                ".api.public -> apps/backend/src/provider/api.py::public "
                "=> def(value: str) -> str"
            ),
            "after": (
                ".api.public -> apps/backend/src/provider/api.py::public "
                "=> def(value: str, strict: bool=False) -> str"
            ),
        }
    ]
    assert report["affected_consumers"]["provider"] == {
        "direct": ["consumer", "middle"],
        "transitive": ["consumer", "middle"],
        "indirect": [],
    }
    assert report["base"]["transitive_consumers"]["provider"] == [
        "consumer",
        "middle",
    ]

    with pytest.raises(RuntimeError, match="missing-base"):
        build_impact_report(repo, base_ref="missing-base")
    with pytest.raises(RuntimeError, match="no package contracts"):
        build_dependency_snapshot(tmp_path / "empty")

    broken = tmp_path / "broken"
    _write(
        broken / "common/broken/contract.py",
        """
        from common.meta.package_contract import PackageContract

        CONTRACT = PackageContract(
            name="broken",
            klass="domain",
            tier="CODE-ONLY",
            depends_on=[],
            interface=["public"],
            events=[],
            invariants=[],
            roadmap=[],
            implementations={"be": "apps/backend/src/broken", "fe": None},
        )
        """,
    )
    with pytest.raises(RuntimeError, match="no readable BE implementation"):
        build_dependency_snapshot(broken)


def test_AC_meta_dependency_governance_2_edge_change_includes_upstream_providers(
    tmp_path: Path,
) -> None:
    """AC-meta.dependency-governance.2: topology fan-out reaches upstream."""

    repo, _ = _seed_repo(tmp_path)
    _write_package(repo, "consumer", klass="domain", depends_on=[])
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "detach downstream consumer")
    base_ref = _git(repo, "rev-parse", "HEAD")
    _write_package(repo, "consumer", klass="domain", depends_on=["middle"])

    report = build_impact_report(repo, base_ref=base_ref)

    assert report["affected_consumers"]["middle"] == {
        "direct": ["consumer"],
        "transitive": ["consumer"],
        "indirect": [],
    }
    assert report["affected_consumers"]["provider"] == {
        "direct": ["middle"],
        "transitive": ["consumer", "middle"],
        "indirect": ["consumer"],
    }


def test_AC_meta_dependency_governance_2_base_snapshot_uses_clean_interpreter(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC-meta.dependency-governance.2: HEAD imports cannot contaminate base."""

    repo, base_ref = _seed_repo(tmp_path)

    def contaminated_head_snapshot(_repo_root: Path) -> dict[str, object]:
        raise AssertionError("HEAD interpreter leaked into the base snapshot")

    monkeypatch.setattr(
        dependency_report,
        "build_dependency_snapshot",
        contaminated_head_snapshot,
    )

    snapshot = dependency_report._snapshot_git_ref(repo, base_ref)

    assert snapshot["direct_consumers"]["provider"] == ["middle"]


def test_AC_meta_dependency_governance_2_base_contract_schema_is_not_reinterpreted(
    tmp_path: Path,
) -> None:
    """AC-meta.dependency-governance.2: base facts survive contract-model drift."""

    repo = tmp_path / "legacy-repo"
    _write(
        repo / "common/provider/contract.py",
        """
        from common.meta.package_contract import PackageContract

        CONTRACT = PackageContract(
            name="provider",
            depends_on=[],
            interface=[],
            implementations={"be": None, "fe": None},
        )
        """,
    )
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "dependency-test@example.invalid")
    _git(repo, "config", "user.name", "Dependency Test")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "legacy package contract")
    base_ref = _git(repo, "rev-parse", "HEAD")

    snapshot = dependency_report._snapshot_git_ref(repo, base_ref)

    assert snapshot["edges"] == []
    assert snapshot["direct_consumers"] == {"provider": []}


def test_AC_meta_dependency_governance_2_public_class_constructor_is_reported(
    tmp_path: Path,
) -> None:
    """AC-meta.dependency-governance.2: constructors are public signatures."""

    repo, _ = _seed_repo(tmp_path)
    _write_public_types(repo, constructor="value: str", enum_value="first")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "publish public types")
    base_ref = _git(repo, "rev-parse", "HEAD")
    _write_public_types(
        repo,
        constructor="value: str, strict: bool = False",
        enum_value="first",
    )

    report = build_impact_report(repo, base_ref=base_ref)

    changes = {record["symbol"]: record for record in report["changed_public_symbols"]}
    assert changes["PublicClass"]["before"] != changes["PublicClass"]["after"]
    assert "strict: bool=False" in changes["PublicClass"]["after"]


def test_AC_meta_dependency_governance_2_public_enum_members_are_reported(
    tmp_path: Path,
) -> None:
    """AC-meta.dependency-governance.2: enum members are public signatures."""

    repo, _ = _seed_repo(tmp_path)
    _write_public_types(repo, constructor="value: str", enum_value="first")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "publish public types")
    base_ref = _git(repo, "rev-parse", "HEAD")
    _write_public_types(repo, constructor="value: str", enum_value="renamed")

    report = build_impact_report(repo, base_ref=base_ref)

    changes = {record["symbol"]: record for record in report["changed_public_symbols"]}
    assert "FIRST='first'" in changes["PublicEnum"]["before"]
    assert "FIRST='renamed'" in changes["PublicEnum"]["after"]


def test_AC_meta_dependency_governance_2_annotated_defaults_are_reported(
    tmp_path: Path,
) -> None:
    """AC-meta.dependency-governance.2: annotated defaults are boundary data."""

    repo, _ = _seed_repo(tmp_path)
    _write_public_surface(
        repo,
        interface=["PUBLIC_CONTRACT", "PublicConfig"],
        source="""
        class PublicConfig:
            max_requests: int = 5

        PUBLIC_CONTRACT: dict[str, int] = {"version": 1}
        """,
    )
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "publish annotated defaults")
    base_ref = _git(repo, "rev-parse", "HEAD")
    _write_public_surface(
        repo,
        interface=["PUBLIC_CONTRACT", "PublicConfig"],
        source="""
        class PublicConfig:
            max_requests: int = 10

        PUBLIC_CONTRACT: dict[str, int] = {"version": 2}
        """,
    )

    report = build_impact_report(repo, base_ref=base_ref)

    changes = {record["symbol"]: record for record in report["changed_public_symbols"]}
    assert "max_requests: int=5" in changes["PublicConfig"]["before"]
    assert "max_requests: int=10" in changes["PublicConfig"]["after"]
    assert "{'version': 1}" in changes["PUBLIC_CONTRACT"]["before"]
    assert "{'version': 2}" in changes["PUBLIC_CONTRACT"]["after"]


def test_AC_meta_dependency_governance_2_method_decorators_are_reported(
    tmp_path: Path,
) -> None:
    """AC-meta.dependency-governance.2: method binding style is boundary data."""

    repo, _ = _seed_repo(tmp_path)
    _write_public_surface(
        repo,
        interface=["PublicService"],
        source="""
        class PublicService:
            @property
            def value(self) -> str:
                return "value"
        """,
    )
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "publish decorated method")
    base_ref = _git(repo, "rev-parse", "HEAD")
    _write_public_surface(
        repo,
        interface=["PublicService"],
        source="""
        class PublicService:
            def value(self) -> str:
                return "value"
        """,
    )

    report = build_impact_report(repo, base_ref=base_ref)

    [change] = report["changed_public_symbols"]
    assert change["symbol"] == "PublicService"
    assert "@property" in change["before"]
    assert "@property" not in change["after"]


def test_AC_meta_dependency_governance_2_generic_parameters_are_reported(
    tmp_path: Path,
) -> None:
    """AC-meta.dependency-governance.2: PEP 695 bounds are boundary data."""

    repo, _ = _seed_repo(tmp_path)
    _write_public_surface(
        repo,
        interface=["PublicGeneric", "public"],
        source="""
        class PublicGeneric[T]:
            def __new__(cls, value: T) -> "PublicGeneric[T]":
                return super().__new__(cls)

        def public[T](value: T) -> T:
            return value
        """,
    )
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "publish generic boundaries")
    base_ref = _git(repo, "rev-parse", "HEAD")
    _write_public_surface(
        repo,
        interface=["PublicGeneric", "public"],
        source="""
        class PublicGeneric[T: str]:
            def __new__(cls, value: T) -> "PublicGeneric[T]":
                return super().__new__(cls)

        def public[T: str](value: T) -> T:
            return value
        """,
    )

    report = build_impact_report(repo, base_ref=base_ref)

    changes = {record["symbol"]: record for record in report["changed_public_symbols"]}
    assert "T: str" in changes["PublicGeneric"]["after"]
    assert "T: str" in changes["public"]["after"]


def test_AC_meta_dependency_governance_2_root_export_binding_is_reported(
    tmp_path: Path,
) -> None:
    """AC-meta.dependency-governance.2: root export targets are boundary data."""

    repo, _ = _seed_repo(tmp_path)
    _write(
        repo / "apps/backend/src/provider/alternate.py",
        """
        def public(value: str) -> str:
            return value
        """,
    )
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "publish alternate implementation")
    base_ref = _git(repo, "rev-parse", "HEAD")
    _write(
        repo / "apps/backend/src/provider/__init__.py",
        'from .alternate import public\n\n__all__ = ["public"]\n',
    )

    switched = build_impact_report(repo, base_ref=base_ref)

    [change] = switched["changed_public_symbols"]
    assert change["symbol"] == "public"
    assert ".api.public" in change["before"]
    assert ".alternate.public" in change["after"]

    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "switch public implementation")
    switched_ref = _git(repo, "rev-parse", "HEAD")
    _write(
        repo / "apps/backend/src/provider/__init__.py",
        '__all__ = ["public"]\n',
    )

    removed = build_impact_report(repo, base_ref=switched_ref)

    [change] = removed["changed_public_symbols"]
    assert ".alternate.public" in change["before"]
    assert change["after"] == "dynamic-export"


def test_AC_meta_dependency_governance_2_unresolved_reexport_fails_closed(
    tmp_path: Path,
) -> None:
    """AC-meta.dependency-governance.2: broken explicit exports fail closed."""

    repo, _ = _seed_repo(tmp_path)
    _write(
        repo / "apps/backend/src/provider/__init__.py",
        'from .missing import public\n\n__all__ = ["public"]\n',
    )

    with pytest.raises(RuntimeError, match="cannot resolve export 'public'"):
        build_dependency_snapshot(repo)


def test_AC_meta_dependency_governance_2_overloads_are_reported(
    tmp_path: Path,
) -> None:
    """AC-meta.dependency-governance.2: overloads are public signatures."""

    repo, _ = _seed_repo(tmp_path)
    _write_public_surface(
        repo,
        interface=["public"],
        source="""
        from typing import Any, overload

        @overload
        def public(value: str) -> str: ...

        @overload
        def public(value: None) -> None: ...

        def public(value: Any) -> Any:
            return value
        """,
    )
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "publish overloaded boundary")
    base_ref = _git(repo, "rev-parse", "HEAD")
    _write_public_surface(
        repo,
        interface=["public"],
        source="""
        from typing import Any, overload

        @overload
        def public(value: str, strict: bool = False) -> str: ...

        @overload
        def public(value: None) -> None: ...

        def public(value: Any) -> Any:
            return value
        """,
    )

    report = build_impact_report(repo, base_ref=base_ref)

    [change] = report["changed_public_symbols"]
    assert "@overload def(value: str) -> str" in change["before"]
    assert "@overload def(value: str, strict: bool=False) -> str" in change["after"]
    assert "def(value: Any) -> Any" in change["before"]
    assert "def(value: Any) -> Any" in change["after"]


def test_AC_meta_dependency_governance_2_wildcard_honors_target_all(
    tmp_path: Path,
) -> None:
    """AC-meta.dependency-governance.2: wildcard bindings obey target __all__."""

    repo, _ = _seed_repo(tmp_path)
    _write(
        repo / "apps/backend/src/provider/alternate.py",
        """
        def public(value: int) -> int:
            return value

        __all__: list[str] = []
        """,
    )
    _write(
        repo / "apps/backend/src/provider/__init__.py",
        """
        from .api import public
        from .alternate import *

        __all__ = ["public"]
        """,
    )
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "publish guarded wildcard")
    base_ref = _git(repo, "rev-parse", "HEAD")
    _write(
        repo / "apps/backend/src/provider/api.py",
        """
        def public(value: str, strict: bool = False) -> str:
            return value
        """,
    )

    report = build_impact_report(repo, base_ref=base_ref)

    [change] = report["changed_public_symbols"]
    assert ".api.public" in change["before"]
    assert ".api.public" in change["after"]
    assert "strict: bool=False" in change["after"]


def test_AC_meta_dependency_governance_2_protocol_methods_are_reported(
    tmp_path: Path,
) -> None:
    """AC-meta.dependency-governance.2: public protocols include dunder methods."""

    repo, _ = _seed_repo(tmp_path)
    _write_public_surface(
        repo,
        interface=["PublicCollection"],
        source="""
        from collections.abc import Iterator

        class PublicCollection:
            def __iter__(self) -> Iterator[str]:
                return iter(())

            def _normalize(self, value: str) -> str:
                return value
        """,
    )
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "publish iterable boundary")
    base_ref = _git(repo, "rev-parse", "HEAD")
    _write_public_surface(
        repo,
        interface=["PublicCollection"],
        source="""
        from collections.abc import Iterator

        class PublicCollection:
            def __iter__(self) -> Iterator[int]:
                return iter(())

            def _normalize(self, value: object) -> object:
                return value
        """,
    )

    report = build_impact_report(repo, base_ref=base_ref)

    [change] = report["changed_public_symbols"]
    assert "__iter__(self) -> Iterator[str]" in change["before"]
    assert "__iter__(self) -> Iterator[int]" in change["after"]
    assert "_normalize" not in change["before"]
    assert "_normalize" not in change["after"]


def test_AC_meta_dependency_governance_2_lazy_root_binding_is_reported(
    tmp_path: Path,
) -> None:
    """AC-meta.dependency-governance.2: lazy root exports retain their targets."""

    repo, _ = _seed_repo(tmp_path)
    _write(
        repo / "apps/backend/src/provider/__init__.py",
        """
        from importlib import import_module

        _EXPORTS = {"public": "src.provider.api"}
        __all__ = ["public"]

        def __getattr__(name: str) -> object:
            module = _EXPORTS.get(name)
            if module is None:
                raise AttributeError(name)
            return getattr(import_module(module), name)
        """,
    )

    snapshot = build_dependency_snapshot(repo)

    record = next(
        record
        for record in snapshot["public_symbols"]
        if record["package"] == "provider" and record["symbol"] == "public"
    )
    assert record["resolution"] == "reexport"
    assert "lazy:src.provider.api.public" in record["signature"]
    assert "def(value: str) -> str" in record["signature"]


def test_AC_meta_dependency_governance_2_unknown_lazy_branch_fails_closed(
    tmp_path: Path,
) -> None:
    """AC-meta.dependency-governance.2: ambiguous lazy exports fail closed."""

    repo, _ = _seed_repo(tmp_path)
    _write(
        repo / "apps/backend/src/provider/alternate.py",
        """
        def public(value: int) -> int:
            return value
        """,
    )
    _write(
        repo / "apps/backend/src/provider/__init__.py",
        """
        from importlib import import_module

        FLAG = object()
        __all__ = ["public"]

        def __getattr__(name: str) -> object:
            if FLAG:
                return getattr(import_module("src.provider.alternate"), name)
            return getattr(import_module("src.provider.api"), name)
        """,
    )

    with pytest.raises(RuntimeError, match="ambiguous lazy export 'public'"):
        build_dependency_snapshot(repo)


def test_AC_meta_dependency_governance_2_inherited_class_api_is_reported(
    tmp_path: Path,
) -> None:
    """AC-meta.dependency-governance.2: inherited APIs are boundary data."""

    repo, _ = _seed_repo(tmp_path)
    _write_public_surface(
        repo,
        interface=["PublicClass"],
        source="""
        class Base:
            def __init__(self, value: str) -> None:
                self.value = value

        class PublicClass(Base):
            pass
        """,
    )
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "publish inherited boundary")
    base_ref = _git(repo, "rev-parse", "HEAD")
    _write_public_surface(
        repo,
        interface=["PublicClass"],
        source="""
        class Base:
            def __init__(self, value: str, strict: bool = False) -> None:
                self.value = value

        class PublicClass(Base):
            pass
        """,
    )

    report = build_impact_report(repo, base_ref=base_ref)

    [change] = report["changed_public_symbols"]
    assert change["symbol"] == "PublicClass"
    assert "inherits[Base]" in change["before"]
    assert "strict: bool=False" in change["after"]


def test_AC_meta_dependency_governance_2_named_function_defaults_are_reported(
    tmp_path: Path,
) -> None:
    """AC-meta.dependency-governance.2: resolved defaults are boundary data."""

    repo, _ = _seed_repo(tmp_path)
    _write_public_surface(
        repo,
        interface=["public"],
        source="""
        DEFAULT = 5

        def public(value: int = DEFAULT) -> int:
            return value
        """,
    )
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "publish named default")
    base_ref = _git(repo, "rev-parse", "HEAD")
    _write_public_surface(
        repo,
        interface=["public"],
        source="""
        DEFAULT = 10

        def public(value: int = DEFAULT) -> int:
            return value
        """,
    )

    report = build_impact_report(repo, base_ref=base_ref)

    [change] = report["changed_public_symbols"]
    assert change["symbol"] == "public"
    assert "DEFAULT=5" in change["before"]
    assert "DEFAULT=10" in change["after"]


def test_AC_meta_dependency_governance_2_local_alias_target_is_reported(
    tmp_path: Path,
) -> None:
    """AC-meta.dependency-governance.2: local aliases retain target signatures."""

    repo, _ = _seed_repo(tmp_path)
    _write_public_surface(
        repo,
        interface=["Public"],
        source="""
        def _implementation(value: str) -> str:
            return value

        Public = _implementation

        def _implementation(value: int) -> int:
            return value
        """,
    )
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "publish aliased boundary")
    base_ref = _git(repo, "rev-parse", "HEAD")
    _write_public_surface(
        repo,
        interface=["Public"],
        source="""
        def _implementation(value: str, strict: bool = False) -> str:
            return value

        Public = _implementation

        def _implementation(value: int) -> int:
            return value
        """,
    )

    report = build_impact_report(repo, base_ref=base_ref)

    [change] = report["changed_public_symbols"]
    assert change["symbol"] == "Public"
    assert change["before"] != change["after"]


def test_AC_meta_dependency_governance_2_snapshot_accounts_for_every_public_symbol() -> (
    None
):
    """AC-meta.dependency-governance.2: the report cannot undercount boundaries."""

    snapshot = build_dependency_snapshot(ROOT)
    expected = {
        (package.name, symbol)
        for package in discover_packages(ROOT)
        for symbol in package.contract.interface
    }
    actual = {
        (record["package"], record["symbol"]) for record in snapshot["public_symbols"]
    }

    assert actual == expected
    assert len(snapshot["public_symbols"]) == len(expected)
    assert not [
        record
        for record in snapshot["public_symbols"]
        if record["resolution"] == "dynamic"
    ]
    assert "units_by_layer" not in snapshot
    assert {edge["kind"] for edge in snapshot["edges"]} == {"compile"}


def test_AC_meta_dependency_governance_2_cli_writes_ephemeral_ci_reports(
    tmp_path: Path,
) -> None:
    """AC-meta.dependency-governance.2: CI gets JSON data and a review summary."""

    repo, base_ref = _seed_repo(tmp_path)
    _write_package(
        repo,
        "provider",
        klass="meta",
        depends_on=[],
        parameters="value: str, strict: bool = False",
    )
    json_out = tmp_path / "dependency-report.json"
    markdown_out = tmp_path / "dependency-report.md"

    assert (
        main(
            [
                "--repo-root",
                str(repo),
                "--base-ref",
                base_ref,
                "--json-out",
                str(json_out),
                "--markdown-out",
                str(markdown_out),
            ]
        )
        == 0
    )
    report = json.loads(json_out.read_text(encoding="utf-8"))
    markdown = markdown_out.read_text(encoding="utf-8")

    assert report["base_ref"] == base_ref
    assert report["changed_public_symbols"][0]["package"] == "provider"
    assert "## DDD Dependency Impact" in markdown
    assert "| Changed public signatures | 1 |" in markdown
    assert "### Public Boundary Changes" in markdown
    assert ".api.public" in markdown
    assert "def(value: str, strict: bool=False) -> str" in markdown


def test_AC_meta_dependency_governance_2_ci_publishes_dependency_summary() -> None:
    """AC-meta.dependency-governance.2: the generated report runs in CI."""

    workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert "tools/report_ddd_dependencies.py" in workflow
    assert "DDD-DEPENDENCY-REPORT.md" in workflow
    assert (
        'cat "$RUNNER_TEMP/DDD-DEPENDENCY-REPORT.md" >> "$GITHUB_STEP_SUMMARY"'
        in workflow
    )
