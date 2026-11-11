"""Env-var classification — the config↔manifest guardrail (#1579)."""

from __future__ import annotations

from pydantic import AliasChoices
from pydantic_settings import BaseSettings

from src.runtime.base.manifest import DEPENDENCY_MANIFEST, DependencyManifest

NON_DEPENDENCY_CATEGORIES: frozenset[str] = frozenset({"security", "deployment", "domain", "feature", "tuning"})

NON_DEPENDENCY_ENV_FIELDS: dict[str, str] = {
    field: category
    for category, fields in (
        (
            "security",
            "secret_key jwt_algorithm access_token_expire_minutes llm_encryption_keys "
            "cors_origins_str cors_origin_regex trust_proxy",
        ),
        ("deployment", "environment debug git_commit_sha next_public_app_url"),
        ("domain", "base_currency"),
        (
            "feature",
            "enable_ai_reconciliation enable_ai_classification auto_accept_ai_suggestions "
            "enable_storage_sweep market_data_lazy_fetch_enabled statement_disposition_mode",
        ),
        (
            "tuning",
            "db_pool_size db_pool_max_overflow s3_presign_expiry_seconds "
            "statement_review_presign_expiry_seconds storage_sweep_grace_period_hours "
            "storage_sweep_interval_seconds ai_chat_completions_path ai_json_timeout_seconds "
            "ai_json_max_tokens ai_json_disable_thinking ai_json_seed ai_extract_max_attempts "
            "large_model small_model multimodal_model market_data_fx_bridge_currency "
            "api_rate_limit_requests api_rate_limit_window register_rate_limit_requests "
            "register_rate_limit_window otel_service_name otel_resource_attributes "
            "openpanel_environment reconciliation_auto_accept_threshold "
            "reconciliation_review_threshold llm_cassette_engage llm_cassette_refresh llm_live",
        ),
    )
    for field in fields.split()
}


def settings_env_keys(settings_cls: type[BaseSettings], field_name: str) -> frozenset[str]:
    """Return the env-var names a `Settings` field reads."""
    alias = settings_cls.model_fields[field_name].validation_alias
    if alias is None:
        return frozenset({field_name.upper()})
    if isinstance(alias, AliasChoices):
        return frozenset(str(choice) for choice in alias.choices)
    return frozenset({str(alias)})


def check_env_classification(
    settings_cls: type[BaseSettings],
    *,
    manifest: DependencyManifest = DEPENDENCY_MANIFEST,
    non_dependency_fields: dict[str, str] | None = None,
) -> list[str]:
    """Reconcile `Settings` against the manifest and return any violations."""
    registered = NON_DEPENDENCY_ENV_FIELDS if non_dependency_fields is None else non_dependency_fields
    declared = frozenset(env_var for dep in manifest for env_var in dep.env_vars)
    errors: list[str] = []
    all_settings_keys: set[str] = set()

    for field_name in settings_cls.model_fields:
        keys = settings_env_keys(settings_cls, field_name)
        all_settings_keys |= keys
        is_dep = bool(keys & declared)
        is_reg = field_name in registered
        if is_dep and is_reg:
            errors.append(
                f"{field_name}: declared in the DependencyManifest AND registered in "
                "NON_DEPENDENCY_ENV_FIELDS — a field has exactly one owner"
            )
        elif not is_dep and not is_reg:
            errors.append(
                f"{field_name}: unclassified env var — declare it in the DependencyManifest "
                "(external backend) or register it in NON_DEPENDENCY_ENV_FIELDS with a category"
            )
        if is_dep and not keys <= declared:
            errors.append(
                f"{field_name}: undeclared alias(es) {sorted(keys - declared)} on a "
                "dependency-owned field — declare every alias in Dependency.env_vars"
            )

    errors.extend(
        f"{env_var}: declared in the DependencyManifest but no Settings field reads it"
        for env_var in sorted(declared - all_settings_keys)
    )
    for field_name, category in registered.items():
        if field_name not in settings_cls.model_fields:
            errors.append(f"{field_name}: registered in NON_DEPENDENCY_ENV_FIELDS but not a Settings field")
        if category not in NON_DEPENDENCY_CATEGORIES:
            errors.append(f"{field_name}: unknown category {category!r}")
    return errors
