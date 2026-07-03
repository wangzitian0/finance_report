"""Five-layer package topology — ``meta < infra < middleware < domain < app``.

The placement of packages in layers is global topology, so it is owned by the
L0 ``meta`` package as a central map (``PACKAGE_LAYER`` in
``common/meta/base/layering.py``) — packages do not self-claim a class; the old
per-contract ``klass="kernel|platform|core"`` vocabulary is retired. Rules
proven here:

- the old three-word vocabulary is rejected at model construction;
- every discovered package resolves its layer from the central map;
- a contract that *does* declare ``klass`` must agree with the map;
- ``depends_on`` edges never point to a higher layer (in particular ``meta``
  itself depends on nothing — the tier vocabulary lives inside ``meta.base``);
- the layer vocabulary stays importable without pydantic (the lightweight CI
  lint env guarantee inherited from ``authority_matrix``);
- the readme carries the authoritative mermaid layer diagram.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from common.meta import PackageContract
from common.meta.base.layering import LAYER_RANK, PACKAGE_LAYER
from common.meta.extension.check_package_contract import discover_packages

REPO = Path(__file__).resolve().parents[2]


def _contract(name: str, **overrides: object) -> PackageContract:
    kwargs: dict[str, object] = {
        "name": name,
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


# ── vocabulary ────────────────────────────────────────────────────────────────


def test_layer_rank_is_the_five_layer_order() -> None:
    """L0 meta < L1 infra < L2 middleware < L3 domain < L4 app."""
    assert LAYER_RANK == {
        "meta": 0,
        "infra": 1,
        "middleware": 2,
        "domain": 3,
        "app": 4,
    }


@pytest.mark.parametrize("legacy", ["kernel", "platform", "core"])
def test_old_klass_vocabulary_is_rejected(legacy: str) -> None:
    """The retired kernel/platform/core words no longer construct a contract."""
    with pytest.raises(ValidationError):
        _contract("synthetic-legacy", klass=legacy)


def test_new_layer_vocabulary_is_accepted() -> None:
    """A package not in the central map declares its layer explicitly."""
    assert _contract("synthetic-new", klass="infra").klass == "infra"


# ── central map as the single placement source ───────────────────────────────


def test_package_layer_map_covers_every_registered_package() -> None:
    """Every discovered contract resolves a layer from PACKAGE_LAYER."""
    missing = [p.name for p in discover_packages(REPO) if p.name not in PACKAGE_LAYER]
    assert missing == [], f"packages with no central placement: {missing}"


def test_mapped_package_needs_no_declared_klass() -> None:
    """A package in the central map gets its layer as a default."""
    assert _contract("ledger").klass == "domain"
    assert _contract("runtime").klass == "infra"
    assert _contract("counter").klass == "middleware"
    assert _contract("meta").klass == "meta"


def test_declared_klass_must_match_central_map() -> None:
    """A self-claim that contradicts the L0 map is rejected, not silently won."""
    with pytest.raises(ValidationError):
        _contract("ledger", klass="infra")


def test_unmapped_package_requires_a_declared_klass() -> None:
    """No map entry + no declaration = unplaceable, rejected at construction."""
    with pytest.raises(ValidationError):
        _contract("synthetic-unmapped")


# ── edges: never up ──────────────────────────────────────────────────────────


def test_no_depends_on_edge_points_to_a_higher_layer() -> None:
    """Declared depends_on edges go down or sideways, never up the five layers."""
    offenders: list[str] = []
    for pkg in discover_packages(REPO):
        my_rank = LAYER_RANK[pkg.contract.klass]
        for dep in pkg.contract.depends_on:
            dep_layer = PACKAGE_LAYER.get(dep)
            if dep_layer is not None and LAYER_RANK[dep_layer] > my_rank:
                offenders.append(
                    f"{pkg.name} ({pkg.contract.klass}) -> {dep} ({dep_layer})"
                )
    assert offenders == [], f"upward depends_on edges: {offenders}"


def test_meta_depends_on_nothing() -> None:
    """L0 has no downward edge to point at — the tier vocabulary is internal."""
    (meta,) = [p for p in discover_packages(REPO) if p.name == "meta"]
    assert meta.contract.depends_on == []


def test_testing_does_not_declare_a_middleware_dependency() -> None:
    """The L1 testing package must not depend upward on the L2 value language."""
    (testing,) = [p for p in discover_packages(REPO) if p.name == "testing"]
    assert "money" not in testing.contract.depends_on


# ── stdlib-only guarantee ────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "module",
    ["common.meta.base.layering", "common.meta.base.authority_matrix"],
)
def test_layer_vocabulary_imports_without_pydantic(module: str) -> None:
    """The L0 vocabulary modules stay importable in the pydantic-free lint env."""
    code = f"import sys; sys.modules['pydantic'] = None; import {module}"
    proc = subprocess.run(
        [sys.executable, "-c", code],
        cwd=REPO,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr


# ── the diagram is the doc ───────────────────────────────────────────────────


def test_readme_carries_the_mermaid_five_layer_diagram() -> None:
    """common/meta/readme.md holds the authoritative layer diagram."""
    text = (REPO / "common/meta/readme.md").read_text(encoding="utf-8")
    assert "```mermaid" in text
    for layer in ("meta", "infra", "middleware", "domain", "app"):
        assert layer in text
