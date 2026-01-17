#!/usr/bin/env python3
"""
Environment variable consistency validation script.

Validates consistency between secrets.ctmpl (Vault SSOT) and config.py (type definitions).

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
    """Extract KEY list from secrets.ctmpl."""
    if not path.exists():
        print(f"WARNING: secrets.ctmpl not found: {path}")
        return set()
    
    content = path.read_text()
    # Match .Data.data.KEY_NAME
    keys = set(re.findall(r'\.Data\.data\.(\w+)', content))
    return keys


def parse_config_py(path: Path) -> dict[str, dict]:
    """Extract field info from config.py."""
    if not path.exists():
        print(f"WARNING: config.py not found: {path}")
        return {}
    
    content = path.read_text()
    fields = {}
    
    # Match field definitions: field_name: type = default or field_name: type
    pattern = r'^\s+(\w+):\s*([^=\n]+?)(?:\s*=\s*(.+))?$'
    
    for match in re.finditer(pattern, content, re.MULTILINE):
        field_name = match.group(1)
        field_type = match.group(2).strip()
        default = match.group(3)
        
        # Skip non-config fields
        if field_name in ('model_config',):
            continue
        
        fields[field_name] = {
            'type': field_type,
            'has_default': default is not None,
            'env_name': field_name.upper(),
        }
    
    return fields


def check_consistency(ctmpl_keys: set[str], config_fields: dict[str, dict]) -> dict:
    """Check consistency between ctmpl and config."""
    config_env_names = {f['env_name'] for f in config_fields.values()}
    
    # Handle known aliases (e.g., S3_ACCESS_KEY -> s3_access_key)
    config_env_names.update({
        'S3_ACCESS_KEY', 'S3_SECRET_KEY'  # Known aliases
    })
    
    in_ctmpl_not_in_config = ctmpl_keys - config_env_names
    
    return {
        'ctmpl_keys': ctmpl_keys,
        'config_env_names': config_env_names,
        'missing_in_config': in_ctmpl_not_in_config,
        'is_consistent': len(in_ctmpl_not_in_config) == 0,
    }


def print_report(result: dict, verbose: bool = False) -> None:
    """Print validation report."""
    print("\n" + "=" * 60)
    print("Environment Variable Consistency Check")
    print("=" * 60)
    
    print(f"\nsecrets.ctmpl: {len(result['ctmpl_keys'])} keys")
    if verbose:
        for key in sorted(result['ctmpl_keys']):
            print(f"   - {key}")
    
    print(f"\nconfig.py: {len(result['config_env_names'])} fields")
    
    if result['missing_in_config']:
        print(f"\nERROR: In secrets.ctmpl but not in config.py:")
        for key in sorted(result['missing_in_config']):
            print(f"   - {key}")
    
    if result['is_consistent']:
        print("\nConsistency check passed!")
    else:
        print("\nInconsistency found, please fix and retry")
    
    print("\n" + "=" * 60)


def generate_fix_suggestions(result: dict) -> None:
    """Generate fix suggestions."""
    if not result['missing_in_config']:
        print("No fixes needed")
        return
    
    print("\nSuggested additions to config.py:")
    print("-" * 40)
    for key in sorted(result['missing_in_config']):
        field_name = key.lower()
        print(f"    {field_name}: str")
    print("-" * 40)


def main():
    parser = argparse.ArgumentParser(description="Environment variable consistency check")
    parser.add_argument('--diff', action='store_true', help='Show detailed diff')
    parser.add_argument('--fix', action='store_true', help='Generate fix suggestions')
    args = parser.parse_args()
    
    root = get_project_root()
    
    ctmpl_path = root / "repo/finance_report/finance_report/10.app/secrets.ctmpl"
    config_path = root / "apps/backend/src/config.py"
    
    print(f"Project root: {root}")
    print(f"secrets.ctmpl: {ctmpl_path.relative_to(root)}")
    print(f"config.py: {config_path.relative_to(root)}")
    
    # Skip if secrets.ctmpl doesn't exist (infrastructure not yet deployed)
    if not ctmpl_path.exists():
        print(f"\nWARNING: secrets.ctmpl not found, skipping consistency check")
        print("This is expected if Vault infrastructure is not yet set up.")
        sys.exit(0)
    
    ctmpl_keys = parse_secrets_ctmpl(ctmpl_path)
    config_fields = parse_config_py(config_path)
    
    result = check_consistency(ctmpl_keys, config_fields)
    print_report(result, verbose=args.diff)
    
    if args.fix:
        generate_fix_suggestions(result)
    
    sys.exit(0 if result['is_consistent'] else 1)


if __name__ == "__main__":
    main()
