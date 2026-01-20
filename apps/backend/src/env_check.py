"""
Startup environment variable check module.

Provides friendly diagnostics for missing environment variables.
"""

from __future__ import annotations

import os
import sys


def print_loaded_config(settings) -> None:
    """Print loaded config summary (for debugging)."""
    if os.getenv("DEBUG", "").lower() not in ("true", "1", "yes"):
        return

    print("\n" + "=" * 60)
    print("Config loaded (DEBUG mode)")
    print("=" * 60)

    # Safe fields (can display values)
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

    # Sensitive fields (only show if set)
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

    # Show fields using defaults
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
    """Check critical environment variables at startup."""
    # Keys required in Vault (required for staging/production)
    vault_required = [
        "DATABASE_URL",
        "REDIS_URL",
        "S3_ENDPOINT",
        "S3_ACCESS_KEY",
        "S3_SECRET_KEY",
        "S3_BUCKET",
    ]

    missing = []
    for key in vault_required:
        if not os.getenv(key):
            missing.append(key)

    is_staging_or_prod = os.getenv("ENVIRONMENT") in ("staging", "production") or os.getenv(
        "ENV"
    ) in ("staging", "production")

    if missing and is_staging_or_prod:
        print("\n" + "=" * 60)
        print("WARNING: Missing required variables for production")
        print("=" * 60)
        for key in missing:
            print(f"  - {key}")
        print("\nThese should be provided by Vault.")
        print("Check secrets.ctmpl and vault-agent config.")
        print("=" * 60 + "\n")

        # SECURITY: Fail by default in production, allow override with STRICT_ENV_CHECK=false
        strict_check = os.getenv("STRICT_ENV_CHECK", "true").lower()
        if strict_check not in ("false", "0", "no"):
            print("\nERROR: Refusing to start with missing required variables.")
            print("Set STRICT_ENV_CHECK=false to override (not recommended).")
            sys.exit(1)

    is_production_env = is_staging_or_prod
    has_otel_endpoint = bool(os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT"))
    if is_production_env and not has_otel_endpoint:
        print("\n" + "=" * 60)
        print("WARNING: SigNoz log export is disabled")
        print("=" * 60)
        print("OTEL_EXPORTER_OTLP_ENDPOINT is not set.")
        print("Production logs will remain on stdout only.")
        print("=" * 60 + "\n")
