#!/usr/bin/env python3
"""Validate Pydantic models in config and schemas."""

from __future__ import annotations

import argparse
import ast
import sys
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

from .project_root import get_project_root


class SchemaVisitor(ast.NodeVisitor):
    """AST visitor to extract Pydantic Field and BaseModel information."""

    def __init__(self) -> None:
        self.fields: list[dict[str, Any]] = []
        self.classes: list[str] = []
        self.current_class: str | None = None

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.current_class = node.name
        self.classes.append(node.name)
        self.generic_visit(node)
        self.current_class = None

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        if self.current_class is None:
            return
        target = node.target.value if isinstance(node.target, ast.Subscript) else node.target
        if not isinstance(target, ast.Name) or not target.id:
            return
        has_field = False
        description = None
        if isinstance(node.value, ast.Call) and isinstance(node.value.func, ast.Name) and node.value.func.id == "Field":
            has_field = True
            for kw in node.value.keywords:
                if kw.arg == "description" and isinstance(kw.value, ast.Constant):
                    description = kw.value.value
        self.fields.append(
            {
                "class": self.current_class,
                "name": target.id,
                "has_field": has_field,
                "description": description,
                "has_default": node.value is not None,
            }
        )
        self.generic_visit(node)


def parse_file_for_schemas(file_path: Path) -> SchemaVisitor:
    if not file_path.exists():
        print(f"WARNING: File not found: {file_path}")
        return SchemaVisitor()
    try:
        visitor = SchemaVisitor()
        visitor.visit(ast.parse(file_path.read_text()))
        return visitor
    except SyntaxError as exc:
        print(f"ERROR: Syntax error in {file_path}: {exc}")
        return SchemaVisitor()


def check_config_file(file_path: Path) -> dict[str, Any]:
    visitor = parse_file_for_schemas(file_path)
    issues = [
        {"type": "error", "file": str(file_path), "field": f["name"], "message": "Config field has no default value"}
        for f in visitor.fields
        if f["class"] == "Settings" and not f["has_default"]
    ]
    return {"visitor": visitor, "issues": issues}


def check_schemas_directory(dir_path: Path, *, paths: Iterable[Path] | None = None) -> dict[str, Any]:
    issues: list[dict[str, Any]] = []
    all_fields: list[dict[str, Any]] = []
    files_checked = 0
    for file_path in list(paths) if paths is not None else list(dir_path.glob("*.py")):
        if file_path.name.startswith("__"):
            continue
        files_checked += 1
        visitor = parse_file_for_schemas(file_path)
        all_fields.extend(visitor.fields)
        issues.extend(
            {
                "type": "warning",
                "file": str(file_path),
                "class": f["class"],
                "field": f["name"],
                "message": "Schema field lacks Field(description=...)",
            }
            for f in visitor.fields
            if f["has_field"] and not f["description"]
        )
    return {"files_checked": files_checked, "issues": issues, "total_fields": len(all_fields)}


def print_report(config_result: dict[str, Any], schemas_result: dict[str, Any]) -> bool:
    print(f"\n{'=' * 60}\nPydantic Schema Validation\n{'=' * 60}")
    print(f"\nConfig file checked:  {config_result['visitor'].classes}")
    print(f"Schema files checked: {schemas_result['files_checked']}")
    print(f"Total schema fields: {schemas_result['total_fields']}")
    all_issues = config_result["issues"] + schemas_result["issues"]
    if all_issues:
        print(f"\nFound {len(all_issues)} issue(s):\n")
        root = get_project_root()
        for issue in all_issues:
            print(f"[{'ERROR' if issue['type'] == 'error' else 'WARNING'}] {issue['message']}")
            if "file" in issue:
                print(f"  File: {Path(issue['file']).relative_to(root)}")
            if "class" in issue:
                print(f"  Class: {issue['class']}")
            if "field" in issue:
                print(f"  Field: {issue['field']}")
            print()
    else:
        print("\n✅ All schema validations passed!")
    print("=" * 60 + "\n")
    return not all_issues


def generate_fix_suggestions(config_result: dict[str, Any], schemas_result: dict[str, Any]) -> None:
    all_issues = config_result["issues"] + schemas_result["issues"]
    if not all_issues:
        print("No issues to fix.")
        return
    print("\n[FIX SUGGESTIONS]\n")
    by_file: dict[str, list[dict[str, Any]]] = {}
    for issue in all_issues:
        by_file.setdefault(issue.get("file", "unknown"), []).append(issue)
    root = get_project_root()
    for file_path, issues in by_file.items():
        try:
            label = str(Path(file_path).relative_to(root))
        except (ValueError, TypeError):
            label = str(file_path)
        print(f"File: {label}\n{'-' * 60}")
        for issue in issues:
            field = issue.get("field", "unknown")
            if "no default value" in issue["message"]:
                print(f'  {field}: str = Field(default="...")')
            elif "lacks Field(description=" in issue["message"]:
                print(f'  {field}: ... = Field(description="Add description here")')
        print()


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Validate Pydantic schemas and config")
    parser.add_argument("--fix", action="store_true", help="Generate fix suggestions")
    parser.add_argument("--paths", nargs="*", metavar="PATH", help="Validate only changed config/schema paths.")
    args = parser.parse_args(argv)
    root = get_project_root()
    config_path = root / "apps/backend/src/config.py"
    schemas_dir = root / "apps/backend/src/schemas"
    selected_paths = [root / path for path in args.paths] if args.paths is not None else None
    selected_config = selected_paths is None or config_path in selected_paths
    selected_schemas = (
        None
        if selected_paths is None
        else [path for path in selected_paths if path.parent == schemas_dir and path.suffix == ".py"]
    )
    config_result = check_config_file(config_path) if selected_config else {"visitor": SchemaVisitor(), "issues": []}
    schemas_result = check_schemas_directory(schemas_dir, paths=selected_schemas)
    is_valid = print_report(config_result, schemas_result)
    if args.fix:
        generate_fix_suggestions(config_result, schemas_result)
    sys.exit(0 if is_valid else 1)


if __name__ == "__main__":
    main()
