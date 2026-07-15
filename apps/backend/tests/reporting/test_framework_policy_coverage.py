"""L2 -> L1 reporting-line coverage gate (EPIC-020 AC20.8 / issue #1342).

Every known L2 category — each ``AssetType`` and each
``ManualValuationComponentType`` — MUST resolve to a concrete L1 report line via
the framework policy matrix, in BOTH ``personal_us_gaap_like`` and
``personal_hkfrs_like``. A category that lands in ``UNSUPPORTED``/the gap path
(instead of a real line) fails here — this is the "no creative reports"
completeness guard: report assembly never has to improvise a line for a known
category.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.extraction.orm.layer2 import AssetType
from src.extraction.orm.layer3 import ManualValuationComponentType
from src.reporting.base.types.reporting import PersonalReportingFrameworkId, PolicyFactDomain
from src.reporting.extension.framework_policy import (
    _find_rule,
    _manual_domain_and_instrument,
    _position_domain_and_instrument,
    get_framework_policy_matrix,
)

_FRAMEWORKS = [
    PersonalReportingFrameworkId.US_GAAP_LIKE,
    PersonalReportingFrameworkId.HKFRS_LIKE,
]


def _resolves(domain: PolicyFactDomain, instrument: str, framework: PersonalReportingFrameworkId) -> bool:
    """True iff (domain, instrument) maps to a concrete matrix rule (not a gap)."""
    if domain == PolicyFactDomain.UNSUPPORTED:
        return False
    matrix = get_framework_policy_matrix(framework)
    fact = SimpleNamespace(domain=domain, instrument_type=instrument)
    rule = _find_rule(matrix, fact)
    # "Concrete L1 line": a matching rule is not enough — it must carry a non-empty
    # line_mappings (otherwise the category resolves but still has no report line).
    return rule is not None and bool(rule.line_mappings)


@pytest.mark.parametrize("framework", _FRAMEWORKS)
def test_AC20_8_1_every_asset_type_maps_to_an_l1_line(framework: PersonalReportingFrameworkId) -> None:
    """AC-reporting.pipeline.1: AC20.8.1: every AssetType resolves to an L1 report line in this framework."""
    unmapped = []
    for asset_type in AssetType:
        domain, instrument = _position_domain_and_instrument(SimpleNamespace(asset_type=asset_type))
        if not _resolves(domain, instrument, framework):
            unmapped.append(f"{asset_type.value} -> ({domain}, {instrument})")
    assert unmapped == [], f"AssetType values with no L1 line in {framework.value}: {unmapped}"


@pytest.mark.parametrize("framework", _FRAMEWORKS)
def test_AC20_8_1_every_manual_component_maps_to_an_l1_line(framework: PersonalReportingFrameworkId) -> None:
    """AC20.8.1: every ManualValuationComponentType resolves to an L1 report line."""
    unmapped = []
    for component_type in ManualValuationComponentType:
        domain, instrument = _manual_domain_and_instrument(SimpleNamespace(component_type=component_type))
        if not _resolves(domain, instrument, framework):
            unmapped.append(f"{component_type.value} -> ({domain}, {instrument})")
    assert unmapped == [], f"ManualValuationComponentType values with no L1 line in {framework.value}: {unmapped}"


def test_AC20_8_1_bond_and_other_are_mapped_not_gaps() -> None:
    """AC20.8.1 regression: BOND and OTHER (previously UNSUPPORTED) now map to a line."""
    for asset_type in (AssetType.BOND, AssetType.OTHER):
        domain, instrument = _position_domain_and_instrument(SimpleNamespace(asset_type=asset_type))
        assert domain != PolicyFactDomain.UNSUPPORTED, f"{asset_type.value} still falls to the gap path"
        assert _resolves(domain, instrument, PersonalReportingFrameworkId.US_GAAP_LIKE)
        assert _resolves(domain, instrument, PersonalReportingFrameworkId.HKFRS_LIKE)
