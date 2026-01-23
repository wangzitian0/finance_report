#!/usr/bin/env python3
"""
Environment variable consistency validation script.

Validates consistency between:
1. secrets.ctmpl (Vault SSOT) vs config.py (Backend Code)
2. config.py (Backend Code) vs .env.example (Documentation)

Usage:
    python scripts/check_env_keys.py           # Check consistency
    python scripts/check_env_keys.py --diff    # Show detailed diff
    python scripts/check_env_keys.py --fix     # Generate fix suggestions
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


def get_project_root() -> Path:
    """Get project root directory."""
    return Path(__file__).parent.parent


def parse_secrets_ctmpl(path: Path) -> set[str]:
    """Extract KEY list from secrets.ctmpl.

    Only extracts keys that are output as environment variables.
    Ignores keys assigned to template variables (e.g., $pg_password).
    """
    if not path.exists():
        print(f"WARNING: secrets.ctmpl not found: {path}")
        return set()

    content = path.read_text()
    keys = set()

    # Parse line by line to distinguish output vars from template vars
    for line in content.splitlines():
        line = line.strip()

        # Skip template variable assignments ({{- $var := ... -}})
        if re.match(r"\{\{-?\s*\$\w+\s*:=", line):
            continue

        # Skip lines that only reference template variables without outputting
        # e.g., {{- with secret ... -}} or {{- end }}
        if re.match(r"\{\{-?\s*(with|end|if|else)", line):
            continue

        # Match environment variable outputs: KEY={{ ... .Data.data.FIELD ... }}
        # But not template variable assignments containing .Data.data.FIELD
        env_var_match = re.match(r"^([A-Z_][A-Z0-9_]*)=", line)
        if env_var_match:
            # This line outputs an env var, extract any .Data.data references
            vault_keys = re.findall(r"\.Data\.data\.(\w+)", line)
            # But these are used to construct the value, not output directly
            # We want the KEY itself (left side of =)
            keys.add(env_var_match.group(1))

    return keys


def parse_env_example(path: Path) -> set[str]:
    """Extract KEY list from .env.example."""
    if not path.exists():
        print(f"WARNING: .env.example not found: {path}")
        return set()

    content = path.read_text()
    keys = set()

    # Regex to handle:
    # 1. Optional 'export ' prefix
    # 2. Key name (word characters)
    # 3. Optional whitespace
    # 4. = sign
    # 5. Ignore comments starting with #
    pattern = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=")

    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue

        match = pattern.match(line)
        if match:
            keys.add(match.group(1))

    return keys


def parse_config_py(path: Path) -> dict[str, dict]:
    """Extract field info from config.py using simple state machine."""
    if not path.exists():
        print(f"WARNING: config.py not found: {path}")
        return {}

    content = path.read_text()
    fields = {}

    # Match field definitions: field_name: type = default or field_name: type
    pattern = r"^\s+(\w+):\s*([^=\n]+?)(?:\s*=\s*(.+))?$"

    in_settings_class = False

    for line in content.splitlines():
        # Simple state check
        if line.startswith("class Settings"):
            in_settings_class = True
            continue

        # Stop if we hit another class or end of block (heuristic)
        # Assuming Settings is the last major class or distinct enough
        if in_settings_class and line.startswith("class ") and "Settings" not in line:
            in_settings_class = False

        if not in_settings_class:
            continue

        # Skip methods/decorators
        if line.strip().startswith("@") or line.strip().startswith("def "):
            continue

        match = re.match(pattern, line)
        if not match:
            continue

        field_name = match.group(1)
        field_type = match.group(2).strip()
        default = match.group(3)

        # Skip non-config fields
        if field_name in ("model_config",):
            continue

        # Extract validation_alias="ALIAS" if present
        alias_match = re.search(r'validation_alias=["\']([^"\']+)["\']', default or "")
        # Also handle AliasChoices("ALIAS", ...)
        alias_choices_match = re.search(
            r'AliasChoices\s*\(\s*["\']([^"\']+)["\']', default or ""
        )

        if alias_match:
            env_name = alias_match.group(1)
        elif alias_choices_match:
            env_name = alias_choices_match.group(1)
        else:
            env_name = field_name.upper()

        fields[field_name] = {
            "type": field_type,
            "has_default": default is not None,
            "env_name": env_name,
        }

    return fields


def check_consistency(
    ctmpl_keys: set[str], config_fields: dict[str, dict], env_example_keys: set[str]
) -> dict:
    """Check consistency across all 3 sources."""
    config_env_names = {f["env_name"] for f in config_fields.values()}

    # Handle known aliases (e.g., S3_ACCESS_KEY -> s3_access_key)
    # config_env_names.update({
    #     'S3_ACCESS_KEY', 'S3_SECRET_KEY'  # Known aliases
    # })

    # 1. secrets.ctmpl vs config.py
    # Keys in Vault MUST exist in config.py to be used
    in_ctmpl_not_in_config = ctmpl_keys - config_env_names

    # 2. config.py vs .env.example
    # Every config field MUST be documented in .env.example
    in_config_not_in_example = config_env_names - env_example_keys

    # 3. .env.example vs config.py (Information only)
    # Keys in .env.example NOT in config.py (might be frontend keys or comments)
    in_example_not_in_config = env_example_keys - config_env_names
    # Filter out known non-backend keys (e.g. NEXT_PUBLIC_)
    suspicious_extra_keys = {
        k
        for k in in_example_not_in_config
        if not k.startswith("NEXT_PUBLIC_") and not k.startswith("DOKPLOY_")
    }

    return {
        "ctmpl_keys": ctmpl_keys,
        "config_env_names": config_env_names,
        "env_example_keys": env_example_keys,
        "missing_in_config": in_ctmpl_not_in_config,
        "undocumented_in_example": in_config_not_in_example,
        "suspicious_extra_keys": suspicious_extra_keys,
        "is_consistent": (len(in_ctmpl_not_in_config) == 0)
        and (len(in_config_not_in_example) == 0),
    }


def print_report(result: dict, verbose: bool = False) -> None:
    """Print validation report."""
    print("\n" + "=" * 60)
    print("Environment Variable Consistency Check")
    print("=" * 60)

    print(f"\nsecrets.ctmpl:   {len(result['ctmpl_keys']):3d} keys")
    print(f"config.py:       {len(result['config_env_names']):3d} fields")
    print(f".env.example:    {len(result['env_example_keys']):3d} keys")

    # Error 1: Vault has key, Backend doesn't use it
    if result["missing_in_config"]:
        print(f"\n[ERROR] In secrets.ctmpl but NOT in config.py (Unused Secret):")
        for key in sorted(result["missing_in_config"]):
            print(f"   - {key}")

    # Error 2: Backend uses key, Documentation doesn't have it
    if result["undocumented_in_example"]:
        print(f"\n[ERROR] In config.py but NOT in .env.example (Undocumented):")
        for key in sorted(result["undocumented_in_example"]):
            print(f"   - {key}")

    # Warning: Documentation has key, Backend doesn't use it
    if verbose and result["suspicious_extra_keys"]:
        print(f"\n[INFO] In .env.example but NOT in config.py (Frontend/Infra?):")
        for key in sorted(result["suspicious_extra_keys"]):
            print(f"   - {key}")

    if result["is_consistent"]:
        print("\n✅ Consistency check passed!")
    else:
        print("\n❌ Inconsistency found, please fix and retry")

    print("\n" + "=" * 60)


def generate_fix_suggestions(result: dict) -> None:
    """Generate fix suggestions."""

    if result["missing_in_config"]:
        print("\n[FIX] Add to apps/backend/src/config.py:")
        print("-" * 40)
        for key in sorted(result["missing_in_config"]):
            field_name = key.lower()
            print(f'    {field_name}: str = Field(validation_alias="{key}")')
        print("-" * 40)

    if result["undocumented_in_example"]:
        print("\n[FIX] Add to .env.example:")
        print("-" * 40)
        for key in sorted(result["undocumented_in_example"]):
            print(f"{key}=")
        print("-" * 40)


def main():
    parser = argparse.ArgumentParser(
        description="Environment variable consistency check"
    )
    parser.add_argument("--diff", action="store_true", help="Show detailed diff")
    parser.add_argument("--fix", action="store_true", help="Generate fix suggestions")
    args = parser.parse_args()

    root = get_project_root()

    ctmpl_path = root / "repo/finance_report/finance_report/10.app/secrets.ctmpl"
    config_path = root / "apps/backend/src/config.py"
    env_example_path = root / ".env.example"

    print(f"Project root: {root}")
    print(
        f"secrets.ctmpl: {ctmpl_path.relative_to(root) if ctmpl_path.exists() else 'NOT FOUND'}"
    )
    print(f"config.py:     {config_path.relative_to(root)}")
    print(f".env.example:  {env_example_path.relative_to(root)}")

    ctmpl_keys = parse_secrets_ctmpl(ctmpl_path)
    config_fields = parse_config_py(config_path)
    env_example_keys = parse_env_example(env_example_path)

    result = check_consistency(ctmpl_keys, config_fields, env_example_keys)
    print_report(result, verbose=args.diff)

    if args.fix:
        generate_fix_suggestions(result)

    sys.exit(0 if result["is_consistent"] else 1)


if __name__ == "__main__":
    main()
