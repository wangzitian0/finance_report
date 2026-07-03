"""Env-var classification — the config↔manifest guardrail (#1579).

The manifest owns the *dependency* env vars (`Dependency.env_vars`); every other
`Settings` field is a non-dependency env var that stays with `config` and its
domain package (charter: "feature/security/domain env vars stay with config").
:data:`NON_DEPENDENCY_ENV_FIELDS` is the explicit, reasoned register of that
second group, and :func:`check_env_classification` reconciles the two against
`Settings`: a field that is neither a declared dependency env var nor a
registered non-dependency entry is an error — so a new external backend cannot
be added to `config.py` without a manifest entry (fail-closed, the same
declared-vs-actual pattern as ``check_package_directory_coverage`` and
``check_pr_ci_evidence``).

Pure data + pure functions; no I/O and no import of `config` (the caller passes
the `Settings` class), so the module stays a `kernel` leaf.
"""

from __future__ import annotations

from pydantic import AliasChoices

from src.runtime.base.manifest import DEPENDENCY_MANIFEST, DependencyManifest

#: The reason classes a non-dependency env var may carry. Mirrors the charter's
#: ownership split: security posture, deployment identity, domain semantics,
#: feature toggles, and per-dependency tuning knobs (a knob configures *how* the
#: app uses a backend; the manifest declares *that* the backend exists).
NON_DEPENDENCY_CATEGORIES: frozenset[str] = frozenset({"security", "deployment", "domain", "feature", "tuning"})

#: Settings field name → category. Every `Settings` field that is not one of a
#: declared dependency's env vars MUST appear here; `check_env_classification`
#: rejects anything unregistered. Grouped by category for auditability.
NON_DEPENDENCY_ENV_FIELDS: dict[str, str] = {
    # ── security — auth/crypto/CORS posture, stays with config + identity ──
    "secret_key": "security",
    "jwt_algorithm": "security",
    "access_token_expire_minutes": "security",
    "llm_encryption_keys": "security",
    "cors_origins_str": "security",
    "cors_origin_regex": "security",
    # ── deployment — which build/where it runs, not what it talks to ──
    "environment": "deployment",
    "debug": "deployment",
    "git_commit_sha": "deployment",
    "next_public_app_url": "deployment",
    # ── domain — business semantics ──
    "base_currency": "domain",
    # ── feature — on/off toggles ──
    "enable_ai_reconciliation": "feature",
    "enable_ai_classification": "feature",
    "enable_storage_sweep": "feature",
    "market_data_lazy_fetch_enabled": "feature",
    # ── tuning — how a backend is used, not whether it is present ──
    "db_pool_size": "tuning",
    "db_pool_max_overflow": "tuning",
    "s3_presign_expiry_seconds": "tuning",
    "statement_review_presign_expiry_seconds": "tuning",
    "storage_sweep_grace_period_hours": "tuning",
    "storage_sweep_interval_seconds": "tuning",
    "ai_chat_completions_path": "tuning",
    "ai_layout_parsing_path": "tuning",
    "ai_json_timeout_seconds": "tuning",
    "ai_json_max_tokens": "tuning",
    "ai_json_disable_thinking": "tuning",
    "ai_json_seed": "tuning",
    "ai_extract_max_attempts": "tuning",
    "primary_model": "tuning",
    "vision_model": "tuning",
    "ocr_model": "tuning",
    "fallback_models_str": "tuning",
    "vision_fallback_models_str": "tuning",
    "market_data_fx_bridge_currency": "tuning",
    "api_rate_limit_requests": "tuning",
    "api_rate_limit_window": "tuning",
    "register_rate_limit_requests": "tuning",
    "register_rate_limit_window": "tuning",
    "otel_service_name": "tuning",
    "otel_resource_attributes": "tuning",
    "openpanel_environment": "tuning",
}


def settings_env_keys(settings_cls: type, field_name: str) -> frozenset[str]:
    """The env-var names a `Settings` field reads (alias choices, or the name)."""
    field = settings_cls.model_fields[field_name]
    alias = field.validation_alias
    if alias is None:
        return frozenset({field_name.upper()})
    if isinstance(alias, AliasChoices):
        return frozenset(str(choice) for choice in alias.choices)
    return frozenset({str(alias)})


def check_env_classification(
    settings_cls: type,
    *,
    manifest: DependencyManifest = DEPENDENCY_MANIFEST,
    non_dependency_fields: dict[str, str] | None = None,
) -> list[str]:
    """Reconcile `Settings` against the manifest; return the violations.

    A field must be exactly one of: a declared dependency env var, or a
    registered non-dependency entry. Registered-but-nonexistent entries and
    invalid categories are violations too, so the register cannot rot.
    """
    registered = NON_DEPENDENCY_ENV_FIELDS if non_dependency_fields is None else non_dependency_fields
    declared = frozenset(env_var for dep in manifest for env_var in dep.env_vars)
    errors: list[str] = []

    all_settings_keys: set[str] = set()
    for field_name in settings_cls.model_fields:
        keys = settings_env_keys(settings_cls, field_name)
        all_settings_keys |= keys
        is_dependency = bool(keys & declared)
        is_registered = field_name in registered
        if is_dependency and is_registered:
            errors.append(
                f"{field_name}: declared in the DependencyManifest AND registered in "
                "NON_DEPENDENCY_ENV_FIELDS — a field has exactly one owner"
            )
        elif not is_dependency and not is_registered:
            errors.append(
                f"{field_name}: unclassified env var — declare it in the DependencyManifest "
                "(external backend) or register it in NON_DEPENDENCY_ENV_FIELDS with a category"
            )
        if is_dependency and not keys <= declared:
            # No alias smuggling: a new alias on a dependency-owned field must be
            # declared too, or it would ride in on an already-declared sibling.
            errors.append(
                f"{field_name}: undeclared alias(es) {sorted(keys - declared)} on a "
                "dependency-owned field — declare every alias in Dependency.env_vars"
            )

    for env_var in sorted(declared - all_settings_keys):
        errors.append(f"{env_var}: declared in the DependencyManifest but no Settings field reads it")

    for field_name, category in registered.items():
        if field_name not in settings_cls.model_fields:
            errors.append(f"{field_name}: registered in NON_DEPENDENCY_ENV_FIELDS but not a Settings field")
        if category not in NON_DEPENDENCY_CATEGORIES:
            errors.append(f"{field_name}: unknown category {category!r}")

    return errors
