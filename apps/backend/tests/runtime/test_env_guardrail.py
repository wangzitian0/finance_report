'AC-runtime.2.1'; from __future__ import annotations; import pytest; from src.config import Settings; from src.runtime import DEPENDENCY_MANIFEST, NON_DEPENDENCY_ENV_FIELDS, check_env_classification; from src.runtime.base.env_classification import NON_DEPENDENCY_CATEGORIES, settings_env_keys; pytestmark = pytest.mark.no_db
def test_every_config_env_var_is_classified() -> None:
    'AC-runtime.2.1'; assert check_env_classification(Settings) == []; _m1_errors = check_env_classification(Settings, non_dependency_fields={**NON_DEPENDENCY_ENV_FIELDS, 'database_url': 'tuning'}); assert any(('database_url' in _m1_e for _m1_e in _m1_errors)); _m2_all_keys = {_m2_key for _m2_field in Settings.model_fields for _m2_key in settings_env_keys(Settings, _m2_field)}
    for _m2_dep in DEPENDENCY_MANIFEST:
        for _m2_env_var in _m2_dep.env_vars: assert _m2_env_var in _m2_all_keys, f'{_m2_dep.name}: declared {_m2_env_var} has no Settings field'
    from src.runtime import Dependency, DependencyKind, DependencyManifest, EnvTier; _m3_stray = DependencyManifest((Dependency(name='ghost', kind=DependencyKind.CODE_DOMINANT, required_in=frozenset({EnvTier.PRODUCTION}), env_vars=frozenset({'GHOST_BACKEND_URL'}), summary='declared but bound to nothing'),)); _m3_errors = check_env_classification(Settings, manifest=_m3_stray); assert any(('GHOST_BACKEND_URL' in _m3_e for _m3_e in _m3_errors)); _m4_declared = {_m4_env_var for _m4_dep in DEPENDENCY_MANIFEST for _m4_env_var in _m4_dep.env_vars}; _m4_matched_count = 0
    for _m4_field_name in Settings.model_fields:
        _m4_keys = settings_env_keys(Settings, _m4_field_name)
        if _m4_keys & _m4_declared: assert _m4_keys <= _m4_declared, f'{_m4_field_name}: undeclared aliases {sorted(_m4_keys - _m4_declared)}'; _m4_matched_count += 1
    assert _m4_matched_count > 0, 'Expected at least one Settings field bound to dependency manifest env vars'; assert set(NON_DEPENDENCY_ENV_FIELDS.values()) <= NON_DEPENDENCY_CATEGORIES; _m6_declared = DEPENDENCY_MANIFEST.get('object_storage').env_vars; assert {'S3_PUBLIC_ENDPOINT', 'S3_PUBLIC_ACCESS_KEY', 'S3_PUBLIC_SECRET_KEY', 'S3_PUBLIC_BUCKET'} <= _m6_declared
def test_guardrail_rejects_an_unclassified_new_field() -> None:
    class WithStray(Settings): shiny_new_backend_url: str = 'http://nowhere'
    errors = check_env_classification(WithStray); assert any(('shiny_new_backend_url' in e for e in errors))
