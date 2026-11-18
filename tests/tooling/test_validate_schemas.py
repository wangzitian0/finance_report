"""Parametrized unit tests for schema_validation CLI and AST visitor."""

from __future__ import annotations

import ast as stdlib_ast
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "apps" / "backend"))

from src.runtime.extension.schema_validation import (
    SchemaVisitor,
    check_config_file,
    check_schemas_directory,
    generate_fix_suggestions,
    get_project_root,
    parse_file_for_schemas,
    print_report,
)


def test_get_project_root() -> None:
    root = get_project_root()
    assert (root / "common").exists() and (root / "tools").exists()


@pytest.mark.parametrize(
    ("code", "expected_classes", "expected_fields"),
    [
        ("class MyModel:\n    field: str\nclass AnotherModel:\n    value: int\n", ["MyModel", "AnotherModel"], ["field", "value"]),
        ('from pydantic import Field\nclass MyModel:\n    name: str = Field(description="desc")\n', ["MyModel"], ["name"]),
        ("from pydantic import Field\nclass MyModel:\n    name: str = Field()\n", ["MyModel"], ["name"]),
        ('top: int = 42\nclass MyModel:\n    req: str\n    opt: str = "x"\n', ["MyModel"], ["req", "opt"]),
    ],
)
def test_schema_visitor_parses_classes_and_fields(
    tmp_path: Path, code: str, expected_classes: list[str], expected_fields: list[str]
) -> None:
    target = tmp_path / "model.py"
    target.write_text(code, encoding="utf-8")
    visitor = parse_file_for_schemas(target)
    assert visitor.classes == expected_classes
    assert [f["name"] for f in visitor.fields] == expected_fields


def test_schema_visitor_missing_syntax_and_non_simple_targets(tmp_path: Path, capsys) -> None:
    assert parse_file_for_schemas(tmp_path / "missing.py").fields == []
    assert "WARNING" in capsys.readouterr().out
    bad = tmp_path / "bad.py"
    bad.write_text("class Broken(\n", encoding="utf-8")
    assert parse_file_for_schemas(bad).fields == []
    assert "ERROR" in capsys.readouterr().out
    visitor = SchemaVisitor()
    visitor.current_class = "MyModel"
    visitor.visit_AnnAssign(
        stdlib_ast.AnnAssign(
            target=stdlib_ast.Attribute(value=stdlib_ast.Name(id="self", ctx=stdlib_ast.Load()), attr="x", ctx=stdlib_ast.Store()),
            annotation=stdlib_ast.Name(id="int", ctx=stdlib_ast.Load()),
            value=None,
            simple=0,
        )
    )
    assert visitor.fields == []


@pytest.mark.parametrize(
    ("content", "expected_error_count"),
    [
        ("class Settings:\n    database_url: str\n    debug: bool = False\n", 1),
        ('class Settings:\n    database_url: str = "sqlite:///x"\n    debug: bool = False\n', 0),
        ("class Other:\n    x: str\nclass Settings:\n    debug: bool = False\n", 0),
    ],
)
def test_check_config_file(tmp_path: Path, content: str, expected_error_count: int) -> None:
    cfg = tmp_path / "config.py"
    cfg.write_text(content, encoding="utf-8")
    res = check_config_file(cfg)
    assert len([i for i in res["issues"] if i["type"] == "error"]) == expected_error_count


def test_check_schemas_directory_and_reporting(tmp_path: Path, capsys) -> None:
    schemas = tmp_path / "schemas"
    schemas.mkdir()
    assert check_schemas_directory(schemas)["files_checked"] == 0
    (schemas / "__init__.py").write_text("", encoding="utf-8")
    (schemas / "user.py").write_text("from pydantic import Field\nclass U:\n    name: str = Field()\n", encoding="utf-8")
    res = check_schemas_directory(schemas)
    assert res["files_checked"] == 1 and len(res["issues"]) == 1

    assert print_report({"visitor": SchemaVisitor(), "issues": []}, {"files_checked": 1, "issues": [], "total_fields": 1}) is True
    assert print_report({"visitor": SchemaVisitor(), "issues": [{"type": "error", "message": "err", "field": "x"}]}, {"files_checked": 0, "issues": [], "total_fields": 0}) is False
    generate_fix_suggestions(
        {"issues": [{"type": "error", "file": "/x/config.py", "field": "db", "message": "Config field has no default value"}]},
        {"issues": [{"type": "warning", "file": "/x/s.py", "class": "U", "field": "name", "message": "Schema field lacks Field(description=...)"}]},
    )
    out = capsys.readouterr().out
    assert "db" in out and "description=" in out


@pytest.mark.parametrize(("cfg_body", "expected_code"), [("debug: bool = False", 0), ("database_url: str", 1)])
def test_main_exit_codes(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, cfg_body: str, expected_code: int) -> None:
    from src.runtime.extension.schema_validation import main

    cfg = tmp_path / "apps" / "backend" / "src" / "config.py"
    cfg.parent.mkdir(parents=True, exist_ok=True)
    cfg.write_text(f"class Settings:\n    {cfg_body}\n", encoding="utf-8")
    (tmp_path / "apps" / "backend" / "src" / "schemas").mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr("src.runtime.extension.schema_validation.get_project_root", lambda: tmp_path)
    monkeypatch.setattr(sys, "argv", ["validate_schemas.py"])
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == expected_code
