"""
Startup environment variable check module.

Provides friendly diagnostics for missing environment variables.
"""

from __future__ import annotations

import os
import sys


def get_vault_required_keys() -> list[str]:
    """
    Return list of environment variables required in staging/production.

    These keys should be managed by Vault and rendered via secrets.ctmpl.
    This list is validated by CI using scripts/check_env_keys.py.

    Returns:
        List of environment variable keys that must be present in
        staging/production environments.
    """
    return [
        "DATABASE_URL",
        "ENVIRONMENT",
        "DEBUG",
        "BASE_CURRENCY",
        "OPENROUTER_API_KEY",
        "PRIMARY_MODEL",
        "FALLBACK_MODELS",
        "OPENROUTER_DAILY_LIMIT_USD",
        "S3_ENDPOINT",
        "S3_ACCESS_KEY",
        "S3_SECRET_KEY",
        "S3_BUCKET",
        "S3_REGION",
        "S3_PRESIGN_EXPIRY_SECONDS",
        "S3_PUBLIC_ENDPOINT",
        "S3_PUBLIC_ACCESS_KEY",
        "S3_PUBLIC_SECRET_KEY",
        "S3_PUBLIC_BUCKET",
        "REDIS_URL",
        "SECRET_KEY",
    ]


def print_loaded_config(settings) -> None:
    if os.getenv("DEBUG", "").lower() not in ("true", "1", "yes"):
        return

    print("\n" + "=" * 60)
    print("Config loaded (DEBUG mode)")
    print("=" * 60)

    # Safe fields - values can be displayed in full (non-sensitive)
    safe_fields = [
        "debug",
        "environment",
        "base_currency",
        "primary_model",
        "s3_endpoint",
        "s3_bucket",
        "cors_origin_regex",
        "otel_exporter_otlp_endpoint",
        "otel_service_name",
        "otel_resource_attributes",
    ]

    # Sensitive fields - only show "set"/"not set" status (credentials, keys)
    sensitive_fields = [
        "database_url",
        "redis_url",
        "openrouter_api_key",
        "s3_access_key",
        "s3_secret_key",
    ]

    for field in safe_fields:
        value = getattr(settings, field, None)
        if value is not None:
            print(f"  {field}: {value}")

    print("")
    for field in sensitive_fields:
        value = getattr(settings, field, None)
        status = "set" if value else "not set"
        print(f"  {field}: {status}")

    print("\nFields using defaults:")
    env_aliases = {
        "environment": "ENVIRONMENT",
    }
    defaults_used = []
    for field in safe_fields:
        env_name = env_aliases.get(field, field.upper())
        if not os.getenv(env_name):
            defaults_used.append(field)

    if defaults_used:
        for field in defaults_used:
            print(f"  - {field}")
    else:
        print("  (none)")

    print("=" * 60 + "\n")


def check_env_on_startup() -> None:
    is_staging_or_prod = os.getenv("ENVIRONMENT") in ("staging", "production") or os.getenv(
        "ENV"
    ) in ("staging", "production")

    if not is_staging_or_prod:
        return

    vault_required = get_vault_required_keys()

    missing = []
    found = []
    for key in vault_required:
        if not os.getenv(key):
            missing.append(key)
        else:
            found.append(key)

    if missing:
        missing_pct = (len(missing) * 100) // len(vault_required) if vault_required else 0
        print("\n" + "=" * 60)
        print("WARNING: Missing required variables for production")
        print("=" * 60)
        print(f"\nExpected: {len(vault_required)} keys")
        print(f"Found: {len(found)} keys")
        print(f"Missing: {len(missing)} keys ({missing_pct}%)")
        print("\nMissing keys:")
        for key in missing:
            print(f"  - {key}")
        if found:
            print(f"\nSuccessfully loaded {len(found)} keys (use DEBUG=true to see list)")
        print("\nThese should be provided by Vault.")
        print("Check secrets.ctmpl and vault-agent config.")
        print("=" * 60 + "\n")

        strict_check = os.getenv("STRICT_ENV_CHECK", "true").lower()
        if strict_check not in ("false", "0", "no"):
            print("\nERROR: Refusing to start with missing required variables.")
            print("Set STRICT_ENV_CHECK=false to override (not recommended).")
            sys.exit(1)

    has_otel_endpoint = bool(os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT"))
    if not has_otel_endpoint:
        print("\n" + "=" * 60)
        print("WARNING: SigNoz log export is disabled")
        print("=" * 60)
        print("OTEL_EXPORTER_OTLP_ENDPOINT is not set.")
        print("Production logs will remain on stdout only.")
        print("=" * 60 + "\n")
