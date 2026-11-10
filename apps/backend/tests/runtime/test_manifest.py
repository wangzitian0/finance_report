from __future__ import annotations; import pytest; from infra2_sdk.runtime.health import DependencyStatus; from src.config import settings; from src.runtime import APP_OWNED_TIERS, DEPENDENCY_MANIFEST, Dependency, DependencyKind, EnvTier; pytestmark = pytest.mark.no_db; _CONFIG_BACKING = {'database': 'database_url', 'object_storage': 's3_endpoint', 'llm': 'ai_base_url', 'cache': 'redis_url', 'workflow_engine': 'prefect_api_url', 'telemetry': 'otel_exporter_otlp_endpoint', 'analytics': 'openpanel_api_url', 'market_data': 'market_data_yahoo_timeout_seconds'}
def test_manifest_declares_the_known_external_dependencies() -> None:
    assert DEPENDENCY_MANIFEST.names() == frozenset(_CONFIG_BACKING)
    for (_m1_name, _m1_attr) in _CONFIG_BACKING.items(): assert _m1_name in DEPENDENCY_MANIFEST.names(); assert hasattr(settings, _m1_attr), f'{_m1_name}: settings.{_m1_attr} missing'
    from src.config import Settings; from src.runtime.base.env_classification import settings_env_keys; _m2_all_keys = {_m2_key for _m2_field in Settings.model_fields for _m2_key in settings_env_keys(Settings, _m2_field)}
    for _m2_dep in DEPENDENCY_MANIFEST:
        assert _m2_dep.env_vars, _m2_dep.name
        for _m2_env_var in _m2_dep.env_vars: assert _m2_env_var.isupper(), f'{_m2_dep.name}: env var {_m2_env_var!r} should be UPPER_SNAKE'; assert _m2_env_var in _m2_all_keys, f'{_m2_dep.name}: no Settings field reads {_m2_env_var}'
    for _m3_dep in DEPENDENCY_MANIFEST: assert _m3_dep.required_in, _m3_dep.name
    with pytest.raises(ValueError): Dependency(name='x', kind=DependencyKind.CODE_DOMINANT, required_in=frozenset(), env_vars=frozenset({'X'}), summary='s')
    _m4_model = {_m4_d.name for _m4_d in DEPENDENCY_MANIFEST if _m4_d.kind is DependencyKind.MODEL_DOMINANT}; assert _m4_model == {'llm'}
    for _m5_tier in EnvTier: _m5_required = DEPENDENCY_MANIFEST.required_for(_m5_tier); assert {'database', 'object_storage'} <= _m5_required
    assert 'llm' in DEPENDENCY_MANIFEST.required_for(EnvTier.STAGING); assert 'llm' not in DEPENDENCY_MANIFEST.required_for(EnvTier.PREVIEW); assert 'cache' in DEPENDENCY_MANIFEST.required_for(EnvTier.PRODUCTION); assert 'cache' not in DEPENDENCY_MANIFEST.required_for(EnvTier.PREVIEW); assert 'market_data' in DEPENDENCY_MANIFEST.required_for(EnvTier.PRODUCTION); assert 'market_data' not in DEPENDENCY_MANIFEST.required_for(EnvTier.GITHUB_CI); assert APP_OWNED_TIERS == frozenset({EnvTier.LOCAL_DEV, EnvTier.LOCAL_CI, EnvTier.GITHUB_CI}); assert {_m7_s.value for _m7_s in DependencyStatus} == {'present', 'absent'}
