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
        'debug', 'base_currency', 'primary_model', 
        's3_endpoint', 's3_bucket', 'cors_origin_regex',
    ]
    
    # Sensitive fields (only show if set)
    sensitive_fields = [
        'database_url', 'redis_url', 'openrouter_api_key',
        's3_access_key', 's3_secret_key',
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
    defaults_used = []
    for field in safe_fields:
        env_name = field.upper()
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
        'DATABASE_URL',
        'REDIS_URL',
        'S3_ENDPOINT',
        'S3_ACCESS_KEY', 
        'S3_SECRET_KEY',
        'S3_BUCKET',
    ]
    
    missing = []
    for key in vault_required:
        if not os.getenv(key):
            missing.append(key)
    
    if missing and os.getenv("ENV") in ("staging", "production"):
        print("\n" + "=" * 60)
        print("WARNING: Missing required variables for production")
        print("=" * 60)
        for key in missing:
            print(f"  - {key}")
        print("\nThese should be provided by Vault.")
        print("Check secrets.ctmpl and vault-agent config.")
        print("=" * 60 + "\n")
        
        # Fail in strict mode
        if os.getenv("STRICT_ENV_CHECK", "").lower() in ("true", "1"):
            sys.exit(1)
