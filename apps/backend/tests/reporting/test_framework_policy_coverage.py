'EPIC-020'; from __future__ import annotations; from types import SimpleNamespace; import pytest; from src.extraction.orm.layer2 import AssetType; from src.pricing import ManualValuationComponentType; from src.reporting.extension.framework_policy import _find_rule, _manual_domain_and_instrument, _position_domain_and_instrument, get_framework_policy_matrix; from src.schemas.reporting import PersonalReportingFrameworkId, PolicyFactDomain; _FRAMEWORKS = [PersonalReportingFrameworkId.US_GAAP_LIKE, PersonalReportingFrameworkId.HKFRS_LIKE]
def _resolves(domain: PolicyFactDomain, instrument: str, framework: PersonalReportingFrameworkId) -> bool:
    if domain == PolicyFactDomain.UNSUPPORTED: return False
    matrix = get_framework_policy_matrix(framework); fact = SimpleNamespace(domain=domain, instrument_type=instrument); rule = _find_rule(matrix, fact); return rule is not None and bool(rule.line_mappings)
@pytest.mark.parametrize('framework', _FRAMEWORKS)
def test_AC20_8_1_every_asset_type_maps_to_an_l1_line(framework: PersonalReportingFrameworkId) -> None:
    'AC-reporting.pipeline.1 AC20.8.1'; unmapped = []
    for asset_type in AssetType: domain, instrument = _position_domain_and_instrument(SimpleNamespace(asset_type=asset_type)); unmapped.append(f'{asset_type.value} -> ({domain}, {instrument})') if not _resolves(domain, instrument, framework) else None
    assert unmapped == [], f'AssetType values with no L1 line in {framework.value}: {unmapped}'
@pytest.mark.parametrize('framework', _FRAMEWORKS)
def test_AC20_8_1_every_manual_component_maps_to_an_l1_line(framework: PersonalReportingFrameworkId) -> None:
    'AC20.8.1'; unmapped = []
    for component_type in ManualValuationComponentType: domain, instrument = _manual_domain_and_instrument(SimpleNamespace(component_type=component_type)); unmapped.append(f'{component_type.value} -> ({domain}, {instrument})') if not _resolves(domain, instrument, framework) else None
    assert unmapped == [], f'ManualValuationComponentType values with no L1 line in {framework.value}: {unmapped}'
def test_AC20_8_1_bond_and_other_are_mapped_not_gaps() -> None:
    'AC20.8.1'
    for asset_type in (AssetType.BOND, AssetType.OTHER): domain, instrument = _position_domain_and_instrument(SimpleNamespace(asset_type=asset_type)); assert domain != PolicyFactDomain.UNSUPPORTED, f'{asset_type.value} still falls to the gap path'; assert _resolves(domain, instrument, PersonalReportingFrameworkId.US_GAAP_LIKE); assert _resolves(domain, instrument, PersonalReportingFrameworkId.HKFRS_LIKE)
