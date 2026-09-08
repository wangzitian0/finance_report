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


@pytest.mark.parametrize(
    "prefix", ["src.other.base.values.Status", "src.provider.base.values.Alias"]
)
def test_enum_relocation_keeps_ambiguous_bindings(prefix: str) -> None:
    """AC-meta.public-boundary.7: mismatched owner/type bindings stay exact."""
    signature = f"{prefix} -> apps/backend/src/provider/base/values.py::Status -> class(str, Enum){{OPEN='open'}}"
    assert dependency_report._normalize_literal_enum_bindings(signature) == signature


def test_enum_relocation_does_not_rewrite_quoted_text() -> None:
    """AC-meta.public-boundary.7: source-looking string defaults are data."""
    literal = "apps/backend/src/provider/base/values.py::Status -> class(str, Enum){OPEN='open'}"
    signature = f"class(Public){{description={literal!r}}}"
    assert dependency_report._normalize_literal_enum_bindings(signature) == signature


@pytest.mark.parametrize("local", [True, False])
@pytest.mark.parametrize(
    "change", ["move", "value", "default", "name", "owner", "behavior"]
)
def test_AC_meta_public_boundary_7_same_owner_enum_relocation(
    tmp_path: Path,
    local: bool,
    change: str,
) -> None:
    """AC-meta.public-boundary.7: real source moves do not hide semantic breaks."""
    repo, _ = _seed_repo(tmp_path)
    enum_source = "from enum import Enum\nclass Status(str, Enum):\n    OPEN = 'open'\n    CLOSED = 'closed'\n"
    old_module = repo / "apps/backend/src/provider/orm/status.py"
    _write(old_module, enum_source)
    before_import = (
        enum_source if local else "from src.provider.orm.status import Status\n"
    )
    _write_public_surface(
        repo,
        interface=["Public"],
        source=before_import + "class Public:\n    status: Status = Status.OPEN\n",
    )
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "publish enum default")
    base = _git(repo, "rev-parse", "HEAD")
    owner = "middle" if change == "owner" else "provider"
    name = "OtherStatus" if change == "name" else "Status"
    after_enum = enum_source.replace("class Status", f"class {name}")
    if change == "value":
        after_enum = after_enum.replace("'open'", "'changed'")
    if change == "behavior":
        after_enum += "    def __str__(self):\n        return 'changed'\n"
    _write(repo / f"apps/backend/src/{owner}/base/vocabulary.py", after_enum)
    imported = name + (" as Status" if name != "Status" else "")
    member = "CLOSED" if change == "default" else "OPEN"
    _write_public_surface(
        repo,
        interface=["Public"],
        source=f"from src.{owner}.base.vocabulary import {imported}\nclass Public:\n    status: Status = Status.{member}\n",
    )
    old_module.unlink()
    report = build_impact_report(repo, base_ref=base)
    result = dependency_report.evaluate_boundary_compatibility(
        report, consumer_proofs={}
    )
    assert result["status"] == ("compatible" if change == "move" else "blocked")
    assert len(report["changed_public_symbols"]) == 1
    if change != "move":
        assert result["unproved_consumers"] == ["consumer", "middle"]


@pytest.mark.parametrize("qualified", [False, True])
@pytest.mark.parametrize("public_class", [False, True])
@pytest.mark.parametrize("changed", ["unrelated", "accessed", "dependency"])
def test_AC_meta_public_boundary_6_configuration_field_projection(
    tmp_path: Path, qualified: bool, public_class: bool, changed: str
) -> None:
    """AC-meta.public-boundary.6: isolate field reads without hiding real breaks."""
    repo, _ = _seed_repo(tmp_path)
    config = repo / "apps/backend/src/config.py"
    _write(repo / "apps/backend/src/__init__.py", "")
    original = """
        from pydantic import Field, field_validator, model_validator
        from pydantic_settings import BaseSettings, SettingsConfigDict
        DEFAULT = 10
        class Settings(BaseSettings):
            model_config = SettingsConfigDict(extra="ignore")
            limit: int = Field(default=DEFAULT)
            model: str = "old-model"
            environment: str = "local"

            @field_validator("limit", mode="before")
            @classmethod
            def normalize(cls, value):
                return int(value)

            @model_validator(mode="after")
            def validate_environment(self):
                if not self.environment:
                    raise ValueError("missing environment")
                return self

        settings = Settings()
    """
    if qualified:
        original = (
            original.replace(
                "from pydantic_settings import BaseSettings, SettingsConfigDict",
                "import pydantic_settings as ps",
            )
            .replace("Settings(BaseSettings)", "Settings(ps.BaseSettings)")
            .replace(
                "model_config = SettingsConfigDict",
                "model_config = ps.SettingsConfigDict",
            )
        )
    _write(config, original)
    imported = (
        "import src.config" if qualified else "from src.config import settings as cfg"
    )
    access = "src.config.settings.limit" if qualified else "cfg.limit"
    declaration = (
        f"class Public:\n    value = lambda: {access}\n"
        if public_class
        else f"def public(value={access}):\n    return value\n"
    )
    _write_public_surface(
        repo,
        interface=["Public" if public_class else "public"],
        source=f"{imported}\n{declaration}",
    )
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "publish configuration field")
    base = _git(repo, "rev-parse", "HEAD")
    replacement = {
        "unrelated": ('"old-model"', '"new-model"'),
        "accessed": ("default=DEFAULT", "default=20"),
        "dependency": ("DEFAULT = 10", "DEFAULT = 20"),
    }[changed]
    _write(config, original.replace(*replacement))

    report = build_impact_report(repo, base_ref=base)
    result = dependency_report.evaluate_boundary_compatibility(
        report, consumer_proofs={}
    )

    assert result["status"] == ("compatible" if changed == "unrelated" else "blocked")
    assert len(report["changed_public_symbols"]) == (0 if changed == "unrelated" else 1)
    if changed != "unrelated":
        assert result["unproved_consumers"] == ["consumer", "middle"]


@pytest.mark.parametrize(
    ("access", "extra", "changed"),
    [
        ("settings", "", "model"),
        ('getattr(settings, "limit")', "", "model"),
        ("settings.missing", "", "model"),
        (
            "settings.limit",
            "def __getattribute__(self, name): return self.model",
            "model",
        ),
        (
            "settings.limit",
            '@model_validator(mode="after")\ndef validate(self):\n    self.limit = len(self.model)\n    return self',
            "model",
        ),
        (
            "settings.limit",
            '@model_validator(mode="after")\ndef validate(self):\n    self.limit = len(getattr(self, "model"))\n    return self',
            "model",
        ),
        (
            "settings.limit",
            '@field_validator("limit")\n@classmethod\ndef validate(cls, value, info):\n    return len(info.data["model"])',
            "model",
        ),
        (
            "settings.computed",
            "@property\ndef computed(self): return len(self.model)",
            "model",
        ),
        (
            "settings.limit",
            '@field_validator("limit")\n@classmethod\ndef validate(cls, value):\n    return value + 1',
            "validator",
        ),
        (
            "settings.limit",
            '@model_validator(mode="after")\ndef validate(self):\n    if not self.environment: raise ValueError("missing")\n    return self',
            "environment",
        ),
        (
            "settings.limit",
            '@model_validator(mode="before")\n@classmethod\ndef validate(cls, data): return data',
            "model",
        ),
        (
            "settings.limit",
            '@model_validator(mode="after")\ndef validate(self): return build_other()',
            "model",
        ),
        (
            "settings.limit",
            '@field_validator("limit")\n@custom_hook\ndef validate(cls, value): return value',
            "model",
        ),
        (
            "settings.limit",
            '@field_validator("limit")\n@classmethod\ndef validate(cls, value, **kwargs): return value',
            "model",
        ),
        (
            "settings.limit",
            "@field_validator(FIELD_NAME)\n@classmethod\ndef validate(cls, value): return value",
            "model",
        ),
        (
            "settings.limit",
            '@field_validator("limit")\n@classmethod\ndef validate(cls, value): return Settings.model',
            "model",
        ),
        (
            "settings.limit",
            '@field_validator("limit")\n@field_validator("model")\n@classmethod\ndef validate(cls, value): return value',
            "model",
        ),
        ("settings.limit", 'marker = "custom class construction"', "model"),
    ],
)
def test_AC_meta_public_boundary_6_ambiguous_and_validation_dependencies_still_break(
    tmp_path: Path, access: str, extra: str, changed: str
) -> None:
    """AC-meta.public-boundary.6: whole objects and validation dependencies stay guarded."""
    repo, _ = _seed_repo(tmp_path)
    config = repo / "apps/backend/src/config.py"
    original = (
        "from pydantic import field_validator, model_validator\n"
        "from pydantic_settings import BaseSettings\n"
        "class Settings(BaseSettings):\n"
        "    limit: int = 10\n"
        '    model: str = "old-model"\n'
        '    environment: str = "local"\n'
        + "".join(f"    {line}\n" for line in extra.splitlines())
        + "settings = Settings()\n"
    )
    _write(config, original)
    _write_public_surface(
        repo,
        interface=["public"],
        source=(
            f"from src.config import settings\ndef public(value={access}):\n    return value\n"
        ),
    )
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "publish conservative configuration read")
    base = _git(repo, "rev-parse", "HEAD")
    replacement = {
        "model": ('"old-model"', '"new-model"'),
        "validator": ("value + 1", "value + 2"),
        "environment": ('"local"', '"staging"'),
    }[changed]
    _write(config, original.replace(*replacement))

    report = build_impact_report(repo, base_ref=base)
    result = dependency_report.evaluate_boundary_compatibility(
        report, consumer_proofs={}
    )

    assert result["status"] == "blocked"
    assert len(report["changed_public_symbols"]) == 1


@pytest.mark.parametrize(
    ("class_header", "field", "construction"),
    [
        ("class Settings(UnknownBase):", "limit: int = 10", "Settings()"),
        ("class Settings(BaseSettings):", "limit: int = 10", "Settings(limit=20)"),
        (
            "class Settings(BaseSettings):",
            "limit: int = Field(default_factory=compute)",
            "Settings()",
        ),
        (
            "class Settings(BaseSettings):",
            "limit: Annotated[int, custom_hook] = 10",
            "Settings()",
        ),
        (
            "@custom_hook\nclass Settings(BaseSettings):",
            "limit: int = 10",
            "Settings()",
        ),
    ],
)
def test_AC_meta_public_boundary_6_unsupported_construction_is_conservative(
    tmp_path: Path, class_header: str, field: str, construction: str
) -> None:
    """AC-meta.public-boundary.6: unsupported construction never assumes independence."""
    repo, _ = _seed_repo(tmp_path)
    config = repo / "apps/backend/src/config.py"
    original = (
        "from pydantic_settings import BaseSettings\n"
        f"{class_header}\n    {field}\n    model: str = 'old'\n"
        f"settings = {construction}\n"
    )
    _write(config, original)
    _write_public_surface(
        repo,
        interface=["public"],
        source=(
            "from src.config import settings\ndef public(value=settings.limit):\n    return value\n"
        ),
    )
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "publish unsupported construction")
    base = _git(repo, "rev-parse", "HEAD")
    _write(config, original.replace("'old'", "'new'"))

    result = dependency_report.evaluate_boundary_compatibility(
        build_impact_report(repo, base_ref=base), consumer_proofs={}
    )

    assert result["status"] == "blocked"


@pytest.mark.parametrize("changed", ["base", "class-default", "annotated-config"])
def test_AC_meta_public_boundary_6_projection_retains_base_and_class_defaults(
    tmp_path: Path, changed: str
) -> None:
    """AC-meta.public-boundary.6: construction semantics and class-local inputs remain visible."""
    repo, _ = _seed_repo(tmp_path)
    config = repo / "apps/backend/src/config.py"
    original = """
        from pydantic import BaseModel
        from pydantic_settings import BaseSettings, SettingsConfigDict
        class Settings(BaseSettings):
            model_config: SettingsConfigDict = SettingsConfigDict(env_prefix="FIRST_")
            seed: int = 10
            limit: int = seed
            model: str = "unchanged"
        settings = Settings()
    """
    _write(config, original)
    _write_public_surface(
        repo,
        interface=["public"],
        source=(
            "from src.config import settings\ndef public(value=settings.limit):\n    return value\n"
        ),
    )
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "publish configuration construction")
    base = _git(repo, "rev-parse", "HEAD")
    replacement = {
        "base": ("Settings(BaseSettings)", "Settings(BaseModel)"),
        "class-default": ("seed: int = 10", "seed: int = 20"),
        "annotated-config": ('env_prefix="FIRST_"', 'env_prefix="SECOND_"'),
    }[changed]
    _write(config, original.replace(*replacement))

    result = dependency_report.evaluate_boundary_compatibility(
        build_impact_report(repo, base_ref=base), consumer_proofs={}
    )

    assert result["status"] == "blocked"


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


def test_AC_meta_dependency_governance_2_imported_default_is_reported(
    tmp_path: Path,
) -> None:
    """AC-meta.dependency-governance.2: imported defaults are boundary data."""

    repo, _ = _seed_repo(tmp_path)
    _write_public_surface(
        repo,
        interface=["public"],
        source="""
        from .constants import DEFAULT

        def public(value: int = DEFAULT) -> int:
            return value
        """,
    )
    constants = repo / "apps/backend/src/provider/constants.py"
    _write(constants, "DEFAULT = 5\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "publish imported default")
    base_ref = _git(repo, "rev-parse", "HEAD")
    _write(constants, "DEFAULT = 10\n")

    report = build_impact_report(repo, base_ref=base_ref)

    [change] = report["changed_public_symbols"]
    assert change["symbol"] == "public"
    assert change["before"] != change["after"]


def test_AC_meta_dependency_governance_2_annotation_alias_is_reported(
    tmp_path: Path,
) -> None:
    """AC-meta.dependency-governance.2: annotation aliases are boundary data."""

    repo, _ = _seed_repo(tmp_path)
    _write_public_surface(
        repo,
        interface=["Public"],
        source="""
        _Input = int | str

        class Public:
            value: _Input

            def transform(self, value: _Input) -> _Input:
                return value
        """,
    )
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "publish annotation alias")
    base_ref = _git(repo, "rev-parse", "HEAD")
    _write_public_surface(
        repo,
        interface=["Public"],
        source="""
        _Input = int | str | bytes

        class Public:
            value: _Input

            def transform(self, value: _Input) -> _Input:
                return value
        """,
    )

    report = build_impact_report(repo, base_ref=base_ref)

    [change] = report["changed_public_symbols"]
    assert change["symbol"] == "Public"
    assert change["before"] != change["after"]


def test_AC_meta_dependency_governance_2_default_uses_assignment_time_value(
    tmp_path: Path,
) -> None:
    """AC-meta.dependency-governance.2: defaults retain captured value bindings."""

    repo, _ = _seed_repo(tmp_path)
    _write_public_surface(
        repo,
        interface=["public"],
        source="""
        A = 1
        B = A
        A = 2

        def public(value: int = B) -> int:
            return value
        """,
    )
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "publish captured default")
    base_ref = _git(repo, "rev-parse", "HEAD")
    _write_public_surface(
        repo,
        interface=["public"],
        source="""
        A = 2
        B = A
        A = 2

        def public(value: int = B) -> int:
            return value
        """,
    )

    report = build_impact_report(repo, base_ref=base_ref)

    [change] = report["changed_public_symbols"]
    assert change["symbol"] == "public"
    assert change["before"] != change["after"]


def test_AC_meta_dependency_governance_2_type_checking_alias_is_reported(
    tmp_path: Path,
) -> None:
    """AC-meta.dependency-governance.2: type-checking aliases are boundary data."""

    repo, _ = _seed_repo(tmp_path)
    _write_public_surface(
        repo,
        interface=["public"],
        source="""
        from typing import TYPE_CHECKING

        if TYPE_CHECKING:
            _Input = int | str

        def public(value: _Input) -> _Input:
            return value
        """,
    )
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "publish type-checking alias")
    base_ref = _git(repo, "rev-parse", "HEAD")
    _write_public_surface(
        repo,
        interface=["public"],
        source="""
        from typing import TYPE_CHECKING

        if TYPE_CHECKING:
            _Input = int | str | bytes

        def public(value: _Input) -> _Input:
            return value
        """,
    )

    report = build_impact_report(repo, base_ref=base_ref)

    [change] = report["changed_public_symbols"]
    assert change["symbol"] == "public"
    assert change["before"] != change["after"]


def test_AC_meta_dependency_governance_2_qualified_import_defaults_are_reported(
    tmp_path: Path,
) -> None:
    """AC-meta.dependency-governance.2: qualified defaults resolve modules."""

    repo, _ = _seed_repo(tmp_path)
    _write_public_surface(
        repo,
        interface=["public_from", "public_import"],
        source="""
        import src.provider.constants as imported_constants
        from . import constants

        def public_from(value: int = constants.DEFAULT) -> int:
            return value

        def public_import(value: int = imported_constants.DEFAULT) -> int:
            return value
        """,
    )
    constants = repo / "apps/backend/src/provider/constants.py"
    _write(constants, "DEFAULT = 5\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "publish qualified defaults")
    base_ref = _git(repo, "rev-parse", "HEAD")
    _write(constants, "DEFAULT = 10\n")

    report = build_impact_report(repo, base_ref=base_ref)

    assert {change["symbol"] for change in report["changed_public_symbols"]} == {
        "public_from",
        "public_import",
    }


def test_AC_meta_dependency_governance_2_qualified_base_api_is_reported(
    tmp_path: Path,
) -> None:
    """AC-meta.dependency-governance.2: qualified inherited APIs are boundary data."""

    repo, _ = _seed_repo(tmp_path)
    _write_public_surface(
        repo,
        interface=["Public"],
        source="""
        from . import base

        class Public(base.Base):
            pass
        """,
    )
    base_source = repo / "apps/backend/src/provider/base.py"
    _write(
        base_source,
        """
        class Base:
            def __init__(self, value: str) -> None:
                self.value = value
        """,
    )
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "publish qualified base")
    base_ref = _git(repo, "rev-parse", "HEAD")
    _write(
        base_source,
        """
        class Base:
            def __init__(self, value: str, strict: bool = False) -> None:
                self.value = value
        """,
    )

    report = build_impact_report(repo, base_ref=base_ref)

    [change] = report["changed_public_symbols"]
    assert change["symbol"] == "Public"
    assert change["before"] != change["after"]


def test_AC_meta_dependency_governance_2_qualified_assignment_alias_is_reported(
    tmp_path: Path,
) -> None:
    """AC-meta.dependency-governance.2: qualified aliases retain targets."""

    repo, _ = _seed_repo(tmp_path)
    root = repo / "apps/backend/src/provider/__init__.py"
    _write(
        root,
        """
        from . import api

        public = api.public
        __all__ = ["public"]
        """,
    )
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "publish qualified alias")
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
    assert change["symbol"] == "public"
    assert change["before"] != change["after"]


def test_AC_meta_dependency_governance_2_imported_definitions_are_reported(
    tmp_path: Path,
) -> None:
    """AC-meta.dependency-governance.2: imported definitions are boundary data."""

    repo, _ = _seed_repo(tmp_path)
    _write_public_surface(
        repo,
        interface=["public_callback", "public_type"],
        source="""
        from .types import Input, callback

        def public_type(value: Input) -> Input:
            return value

        def public_callback(fn=callback):
            return fn
        """,
    )
    definitions = repo / "apps/backend/src/provider/types.py"
    _write(
        definitions,
        """
        class Input:
            value: str

        def callback(value: str) -> str:
            return value
        """,
    )
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "publish imported definitions")
    base_ref = _git(repo, "rev-parse", "HEAD")
    _write(
        definitions,
        """
        class Input:
            value: int

        def callback(value: str, strict: bool = False) -> str:
            return value
        """,
    )

    report = build_impact_report(repo, base_ref=base_ref)

    assert {change["symbol"] for change in report["changed_public_symbols"]} == {
        "public_callback",
        "public_type",
    }


def test_AC_meta_dependency_governance_2_imported_decorator_is_reported(
    tmp_path: Path,
) -> None:
    """AC-meta.dependency-governance.2: decorator bindings are boundary data."""

    repo, _ = _seed_repo(tmp_path)
    _write_public_surface(
        repo,
        interface=["Public"],
        source="""
        from .decorators import PUBLIC_BINDING

        class Public:
            @PUBLIC_BINDING
            def value(self) -> str:
                return "value"
        """,
    )
    decorators = repo / "apps/backend/src/provider/decorators.py"
    _write(decorators, "PUBLIC_BINDING = property\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "publish imported decorator")
    base_ref = _git(repo, "rev-parse", "HEAD")
    _write(decorators, "PUBLIC_BINDING = cached_property\n")

    report = build_impact_report(repo, base_ref=base_ref)

    [change] = report["changed_public_symbols"]
    assert change["symbol"] == "Public"
    assert change["before"] != change["after"]


def test_AC_meta_dependency_governance_2_local_definition_default_is_reported(
    tmp_path: Path,
) -> None:
    """AC-meta.dependency-governance.2: local definitions are boundary data."""

    repo, _ = _seed_repo(tmp_path)
    _write_public_surface(
        repo,
        interface=["public"],
        source="""
        def callback(value: str) -> str:
            return value

        def public(fn=callback):
            return fn
        """,
    )
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "publish local definition default")
    base_ref = _git(repo, "rev-parse", "HEAD")
    _write_public_surface(
        repo,
        interface=["public"],
        source="""
        def callback(value: str, strict: bool = False) -> str:
            return value

        def public(fn=callback):
            return fn
        """,
    )

    report = build_impact_report(repo, base_ref=base_ref)

    [change] = report["changed_public_symbols"]
    assert change["symbol"] == "public"
    assert change["before"] != change["after"]


def test_AC_meta_dependency_governance_2_class_local_default_is_reported(
    tmp_path: Path,
) -> None:
    """AC-meta.dependency-governance.2: class-scope bindings are boundary data."""

    repo, _ = _seed_repo(tmp_path)
    _write_public_surface(
        repo,
        interface=["Public"],
        source="""
        class Public:
            _DEFAULT = 1

            def method(self, value: int = _DEFAULT) -> int:
                return value
        """,
    )
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "publish class-local default")
    base_ref = _git(repo, "rev-parse", "HEAD")
    _write_public_surface(
        repo,
        interface=["Public"],
        source="""
        class Public:
            _DEFAULT = 2

            def method(self, value: int = _DEFAULT) -> int:
                return value
        """,
    )

    report = build_impact_report(repo, base_ref=base_ref)

    [change] = report["changed_public_symbols"]
    assert change["symbol"] == "Public"
    assert change["before"] != change["after"]


def test_AC_meta_dependency_governance_2_relative_lazy_import_is_reported(
    tmp_path: Path,
) -> None:
    """AC-meta.dependency-governance.2: lazy imports preserve relative levels."""

    repo, _ = _seed_repo(tmp_path)
    impl = "apps/backend/src/provider/lazy"
    _write(
        repo / "common/provider/contract.py",
        f"""
        from common.meta.package_contract import PackageContract

        CONTRACT = PackageContract(
            name="provider",
            klass="meta",
            tier="CODE-ONLY",
            depends_on=[],
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
        """
        __all__ = ["public"]

        def __getattr__(name: str) -> object:
            if name == "public":
                from ..api import public
                return public
            raise AttributeError(name)
        """,
    )
    _write(
        repo / f"{impl}/api.py",
        """
        def public(value: int) -> int:
            return value
        """,
    )
    parent_api = repo / "apps/backend/src/provider/api.py"
    _write(
        parent_api,
        """
        def public(value: str) -> str:
            return value
        """,
    )
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "publish relative lazy import")
    base_ref = _git(repo, "rev-parse", "HEAD")
    _write(
        parent_api,
        """
        def public(value: str, strict: bool = False) -> str:
            return value
        """,
    )

    report = build_impact_report(repo, base_ref=base_ref)

    [change] = report["changed_public_symbols"]
    assert change["symbol"] == "public"
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
