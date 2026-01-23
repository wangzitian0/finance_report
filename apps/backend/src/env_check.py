"""
Startup environment variable check module.

Provides friendly diagnostics for missing environment variables.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def get_vault_managed_keys_from_env_example() -> list[str]:
    """
    Parse .env.example to extract Vault-managed environment variable keys.

    Identifies keys marked with [VAULT] comments by:
    1. Finding lines with "[VAULT]" marker (must be in a comment)
    2. Extracting optional prefix pattern from "All X_*" format
    3. Collecting keys within 10-line window after marker
    4. If prefix exists, filtering keys that match the pattern

    Returns:
        List of environment variable keys that should be managed by Vault
        in staging/production environments. Returns empty list if .env.example
        not found or cannot be parsed.

    Example .env.example format:
        # [VAULT] All S3_* variables managed by Vault
        S3_ENDPOINT=http://localhost:9000
        S3_ACCESS_KEY=minio
        S3_SECRET_KEY=local_secret

        # [VAULT] Managed by Vault in production
        DATABASE_URL=postgresql://...
    """
    import logging

    logger = logging.getLogger(__name__)
    env_example_path = Path(__file__).parents[3] / ".env.example"

    if not env_example_path.exists():
        logger.warning(
            "env_check: .env.example not found, using fallback keys",
            extra={"expected_path": str(env_example_path)},
        )
        return []

    try:
        lines = env_example_path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError) as e:
        logger.error(
            "env_check: Failed to read .env.example",
            extra={"error": str(e), "error_type": type(e).__name__, "path": str(env_example_path)},
        )
        return []

    try:
        required_keys = []
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
                # Reset state if we're past the 10-line window
                if pending_vault_marker is not None and (i - pending_vault_marker) > 10:
                    pending_vault_marker = None
                    vault_prefix_pattern = None
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

        if not required_keys:
            logger.warning(
                "env_check: Parser found 0 Vault-managed keys in .env.example",
                extra={
                    "vault_markers_found": sum(1 for line in lines if "[VAULT]" in line),
                    "total_lines": len(lines),
                },
            )
        else:
            logger.debug(
                "env_check: Parsed Vault-managed keys",
                extra={"key_count": len(required_keys), "keys": required_keys},
            )

        return required_keys
    except Exception as e:
        logger.error(
            "env_check: Parser failed while processing .env.example",
            extra={
                "error": str(e),
                "error_type": type(e).__name__,
                "line_count": len(lines) if "lines" in locals() else 0,
            },
        )
        return []


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

    vault_required = get_vault_managed_keys_from_env_example()

    if not vault_required:
        import logging

        logger = logging.getLogger(__name__)
        logger.warning(
            "env_check: Parser returned no keys, using comprehensive fallback list",
            extra={"fallback_count": 20},
        )
        fallback_keys = [
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
        vault_required = fallback_keys

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
