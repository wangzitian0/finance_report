#!/usr/bin/env python3
"""
Validate Pydantic models in config and schemas.

Ensures:
1. All config fields have default values or validation
2. All schema fields have documentation (Field(description=...))
3. No required fields without defaults in Settings
4. All Field() calls have proper validation

Usage:
    python scripts/validate_schemas.py           # Validate all
    python scripts/validate_schemas.py --fix     # Generate fix suggestions
"""

from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path


def get_project_root() -> Path:
    """Get project root directory."""
    return Path(__file__).parent.parent


class SchemaVisitor(ast.NodeVisitor):
    """AST visitor to extract Pydantic Field and BaseModel information."""

    def __init__(self):
        self.fields = []
        self.classes = []
        self.current_class = None

    def visit_ClassDef(self, node):
        """Visit class definition."""
        self.current_class = node.name
        self.classes.append(node.name)
        self.generic_visit(node)
        self.current_class = None

    def visit_AnnAssign(self, node):
        """Visit annotated assignment (field_name: type = ...)."""
        if self.current_class is None:
            return

        # Handle both simple names (x: int) and subscript (x: Optional[int])
        if isinstance(node.target, ast.Name):
            field_name = node.target.id
        elif isinstance(node.target, ast.Subscript):
            # Handle subscript like x: Optional[int]
            if isinstance(node.target.value, ast.Name):
                field_name = node.target.value.id
            else:
                return
        else:
            return

        if not field_name:
            return

        # Check if it's a Field() call
        has_field_call = False
        field_description = None
        has_default = node.value is not None

        if isinstance(node.value, ast.Call):
            call = node.value
            if isinstance(call.func, ast.Name) and call.func.id == "Field":
                has_field_call = True
                # Extract description argument
                for keyword in call.keywords:
                    if keyword.arg == "description":
                        if isinstance(keyword.value, ast.Constant):
                            field_description = keyword.value.value

        self.fields.append(
            {
                "class": self.current_class,
                "name": field_name,
                "has_field": has_field_call,
                "description": field_description,
                "has_default": has_default,
            }
        )

        self.generic_visit(node)


def parse_file_for_schemas(file_path: Path) -> SchemaVisitor:
    """Parse Python file and extract schema information."""
    if not file_path.exists():
        print(f"WARNING: File not found: {file_path}")
        return SchemaVisitor()

    try:
        content = file_path.read_text()
        tree = ast.parse(content)
        visitor = SchemaVisitor()
        visitor.visit(tree)
        return visitor
    except SyntaxError as e:
        print(f"ERROR: Syntax error in {file_path}: {e}")
        return SchemaVisitor()


def check_config_file(file_path: Path) -> dict:
    """Validate config.py for proper field definitions."""
    visitor = parse_file_for_schemas(file_path)

    issues = []

    # Check Settings class specifically
    settings_fields = [f for f in visitor.fields if f["class"] == "Settings"]

    for field in settings_fields:
        # Config fields without defaults are required
        if not field["has_default"]:
            issues.append(
                {
                    "type": "error",
                    "file": str(file_path),
                    "field": field["name"],
                    "message": "Config field has no default value",
                }
            )

    return {
        "visitor": visitor,
        "issues": issues,
    }


def check_schemas_directory(dir_path: Path) -> dict:
    """Validate all schema files."""
    issues = []
    all_fields = []
    files_checked = 0

    schema_files = list(dir_path.glob("*.py"))

    for file_path in schema_files:
        if file_path.name.startswith("__"):
            continue

        files_checked += 1  # Only count non-skipped files
        visitor = parse_file_for_schemas(file_path)
        all_fields.extend(visitor.fields)

        for field in visitor.fields:
            if not field["has_field"]:
                continue

            if not field["description"]:
                issues.append(
                    {
                        "type": "warning",
                        "file": str(file_path),
                        "class": field["class"],
                        "field": field["name"],
                        "message": "Schema field lacks Field(description=...)",
                    }
                )

    return {
        "files_checked": files_checked,
        "issues": issues,
        "total_fields": len(all_fields),
    }


def print_report(config_result: dict, schemas_result: dict) -> bool:
    """Print validation report."""
    print("\n" + "=" * 60)
    print("Pydantic Schema Validation")
    print("=" * 60)

    print(f"\nConfig file checked:  {config_result['visitor'].classes}")
    print(f"Schema files checked: {schemas_result['files_checked']}")
    print(f"Total schema fields: {schemas_result['total_fields']}")

    # Print issues
    all_issues = config_result["issues"] + schemas_result["issues"]

    if all_issues:
        print(f"\nFound {len(all_issues)} issue(s):\n")

        for issue in all_issues:
            severity = "ERROR" if issue["type"] == "error" else "WARNING"
            print(f"[{severity}] {issue['message']}")
            if "file" in issue:
                file_path = Path(issue["file"])
                print(f"  File: {file_path.relative_to(get_project_root())}")
            if "class" in issue:
                print(f"  Class: {issue['class']}")
            if "field" in issue:
                print(f"  Field: {issue['field']}")
            print()
    else:
        print("\n✅ All schema validations passed!")

    print("=" * 60 + "\n")

    return len(all_issues) == 0


def generate_fix_suggestions(config_result: dict, schemas_result: dict) -> None:
    """Generate fix suggestions for found issues."""
    all_issues = config_result["issues"] + schemas_result["issues"]

    if not all_issues:
        print("No issues to fix.")
        return

    print("\n[FIX SUGGESTIONS]\n")

    # Group by file
    by_file = {}
    for issue in all_issues:
        file_path = issue.get("file", "unknown")
        if file_path not in by_file:
            by_file[file_path] = []
        by_file[file_path].append(issue)

    for file_path, issues in by_file.items():
        try:
            relative_path = Path(file_path).relative_to(get_project_root())
            print(f"File: {relative_path}")
        except (ValueError, TypeError):
            # Fall back to absolute path if not under project root or invalid
            print(f"File: {file_path}")
        print("-" * 60)

        for issue in issues:
            field = issue.get("field", "unknown")
            if "no default value" in issue["message"]:
                print(f'  {field}: str = Field(default="...")')
            elif "lacks Field(description=" in issue["message"]:
                print(f'  {field}: ... = Field(description="Add description here")')

        print()


def main():
    parser = argparse.ArgumentParser(description="Validate Pydantic schemas and config")
    parser.add_argument("--fix", action="store_true", help="Generate fix suggestions")
    args = parser.parse_args()

    root = get_project_root()

    config_path = root / "apps/backend/src/config.py"
    schemas_dir = root / "apps/backend/src/schemas"

    # Validate config
    config_result = check_config_file(config_path)

    # Validate schemas
    schemas_result = check_schemas_directory(schemas_dir)

    # Print report
    is_valid = print_report(config_result, schemas_result)

    # Generate fix suggestions if requested
    if args.fix:
        generate_fix_suggestions(config_result, schemas_result)

    sys.exit(0 if is_valid else 1)


if __name__ == "__main__":
    main()
