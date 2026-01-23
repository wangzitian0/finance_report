"""
Startup environment variable check module.

Provides friendly diagnostics for missing environment variables.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def get_vault_managed_keys_from_env_example() -> list[str]:
    env_example_path = Path(__file__).parents[3] / ".env.example"

    if not env_example_path.exists():
        return []

    required_keys = []
    lines = env_example_path.read_text().splitlines()

    pending_vault_marker = None
    vault_prefix_pattern = None

    for i, line in enumerate(lines):
        stripped = line.strip()

        if "[VAULT]" in stripped and stripped.startswith("#"):
            pending_vault_marker = i

            if "All " in stripped and "_*" in stripped:
                parts = stripped.split("All ")[1].split("_*")[0]
                vault_prefix_pattern = parts.strip() + "_"
            else:
                vault_prefix_pattern = None
            continue

        if not stripped or stripped.startswith("#"):
            continue

        if "=" in stripped:
            key = stripped.split("=")[0].strip()
            if not key:
                continue

            if pending_vault_marker is not None and (i - pending_vault_marker) <= 10:
                if vault_prefix_pattern and key.startswith(vault_prefix_pattern):
                    required_keys.append(key)
                elif not vault_prefix_pattern:
                    required_keys.append(key)
            else:
                pending_vault_marker = None
                vault_prefix_pattern = None

    return required_keys


def print_loaded_config(settings) -> None:
    if os.getenv("DEBUG", "").lower() not in ("true", "1", "yes"):
        return

    print("\n" + "=" * 60)
    print("Config loaded (DEBUG mode)")
    print("=" * 60)

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

    vault_required = get_vault_managed_keys_from_env_example()

    if not vault_required:
        fallback_keys = [
            "DATABASE_URL",
            "REDIS_URL",
            "S3_ENDPOINT",
            "S3_ACCESS_KEY",
            "S3_SECRET_KEY",
            "S3_BUCKET",
        ]
        vault_required = fallback_keys

    missing = []
    for key in vault_required:
        if not os.getenv(key):
            missing.append(key)

    if missing:
        print("\n" + "=" * 60)
        print("WARNING: Missing required variables for production")
        print("=" * 60)
        for key in missing:
            print(f"  - {key}")
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
