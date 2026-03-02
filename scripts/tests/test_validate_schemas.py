"""Tests for scripts/validate_schemas.py"""

import pytest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

from validate_schemas import (
    get_project_root,
    SchemaVisitor,
    parse_file_for_schemas,
    check_config_file,
    check_schemas_directory,
    print_report,
    generate_fix_suggestions,
)


class TestGetProjectRoot:
    def test_returns_path(self):
        result = get_project_root()
        assert isinstance(result, Path)

    def test_returns_parent_of_scripts_dir(self):
        result = get_project_root()
        assert (result / "scripts").exists() or result.name != "scripts"


class TestSchemaVisitor:
    def test_visit_class_def_extracts_class_names(self, tmp_path):
        test_file = tmp_path / "test_model.py"
        test_file.write_text("""
class MyModel:
    field: str

class AnotherModel:
    value: int
""")

        visitor = parse_file_for_schemas(test_file)

        assert "MyModel" in visitor.classes
        assert "AnotherModel" in visitor.classes

    def test_visit_ann_assign_extracts_fields(self, tmp_path):
        test_file = tmp_path / "test_model.py"
        test_file.write_text("""
class MyModel:
    name: str
    count: int = 0
""")

        visitor = parse_file_for_schemas(test_file)

        field_names = [f["name"] for f in visitor.fields]
        assert "name" in field_names
        assert "count" in field_names

    def test_extracts_field_with_description(self, tmp_path):
        test_file = tmp_path / "test_model.py"
        test_file.write_text("""
from pydantic import Field

class MyModel:
    name: str = Field(description="User's name")
""")

        visitor = parse_file_for_schemas(test_file)

        field = next(f for f in visitor.fields if f["name"] == "name")
        assert field["has_field"] is True
        assert field["description"] == "User's name"

    def test_field_without_description(self, tmp_path):
        test_file = tmp_path / "test_model.py"
        test_file.write_text("""
from pydantic import Field

class MyModel:
    name: str = Field()
""")

        visitor = parse_file_for_schemas(test_file)

        field = next(f for f in visitor.fields if f["name"] == "name")
        assert field["has_field"] is True
        assert field["description"] is None

    def test_detects_has_default(self, tmp_path):
        test_file = tmp_path / "test_model.py"
        test_file.write_text("""
class MyModel:
    required_field: str
    optional_field: str = "default"
""")

        visitor = parse_file_for_schemas(test_file)

        required = next(f for f in visitor.fields if f["name"] == "required_field")
        optional = next(f for f in visitor.fields if f["name"] == "optional_field")

        assert required["has_default"] is False
        assert optional["has_default"] is True


class TestParseFileForSchemas:
    def test_returns_empty_visitor_for_missing_file(self, tmp_path, capsys):
        missing_file = tmp_path / "nonexistent.py"
        result = parse_file_for_schemas(missing_file)

        assert isinstance(result, SchemaVisitor)
        assert result.fields == []
        assert result.classes == []
        captured = capsys.readouterr()
        assert "WARNING" in captured.out

    def test_returns_empty_visitor_for_syntax_error(self, tmp_path, capsys):
        bad_file = tmp_path / "bad.py"
        bad_file.write_text("class Broken(\n")

        result = parse_file_for_schemas(bad_file)

        assert isinstance(result, SchemaVisitor)
        assert result.fields == []
        captured = capsys.readouterr()
        assert "ERROR" in captured.out or "Syntax error" in captured.out

    def test_parses_simple_pydantic_model(self, tmp_path):
        test_file = tmp_path / "model.py"
        test_file.write_text("""
from pydantic import BaseModel, Field

class UserSchema(BaseModel):
    name: str = Field(description="User name")
    email: str = Field(description="Email address")
""")

        visitor = parse_file_for_schemas(test_file)

        assert "UserSchema" in visitor.classes
        assert len(visitor.fields) == 2


class TestCheckConfigFile:
    def test_detects_field_without_default_as_error(self, tmp_path):
        config_file = tmp_path / "config.py"
        config_file.write_text("""
class Settings:
    database_url: str
    debug: bool = False
""")

        result = check_config_file(config_file)

        errors = [i for i in result["issues"] if i["type"] == "error"]
        assert len(errors) == 1
        assert errors[0]["field"] == "database_url"

    def test_no_error_when_all_fields_have_defaults(self, tmp_path):
        config_file = tmp_path / "config.py"
        config_file.write_text("""
class Settings:
    database_url: str = "postgres://localhost/db"
    debug: bool = False
""")

        result = check_config_file(config_file)

        errors = [i for i in result["issues"] if i["type"] == "error"]
        assert len(errors) == 0

    def test_returns_visitor_in_result(self, tmp_path):
        config_file = tmp_path / "config.py"
        config_file.write_text("""
class Settings:
    debug: bool = False
""")

        result = check_config_file(config_file)

        assert "visitor" in result
        assert isinstance(result["visitor"], SchemaVisitor)

    def test_only_checks_settings_class(self, tmp_path):
        config_file = tmp_path / "config.py"
        config_file.write_text("""
class OtherClass:
    required_field: str

class Settings:
    debug: bool = False
""")

        result = check_config_file(config_file)

        # OtherClass.required_field should not trigger an error
        errors = [i for i in result["issues"] if i["type"] == "error"]
        assert len(errors) == 0


class TestCheckSchemasDirectory:
    def test_warns_field_without_description(self, tmp_path):
        schemas_dir = tmp_path / "schemas"
        schemas_dir.mkdir()
        schema_file = schemas_dir / "user.py"
        schema_file.write_text("""
from pydantic import Field

class UserSchema:
    name: str = Field()
""")

        result = check_schemas_directory(schemas_dir)

        warnings = [i for i in result["issues"] if i["type"] == "warning"]
        assert len(warnings) == 1
        assert "lacks Field(description=" in warnings[0]["message"]

    def test_no_warning_when_description_present(self, tmp_path):
        schemas_dir = tmp_path / "schemas"
        schemas_dir.mkdir()
        schema_file = schemas_dir / "user.py"
        schema_file.write_text("""
from pydantic import Field

class UserSchema:
    name: str = Field(description="The name")
""")

        result = check_schemas_directory(schemas_dir)

        warnings = [i for i in result["issues"] if i["type"] == "warning"]
        assert len(warnings) == 0

    def test_skips_init_files(self, tmp_path):
        schemas_dir = tmp_path / "schemas"
        schemas_dir.mkdir()

        init_file = schemas_dir / "__init__.py"
        init_file.write_text("# init file")

        schema_file = schemas_dir / "user.py"
        schema_file.write_text("""
class UserSchema:
    name: str
""")

        result = check_schemas_directory(schemas_dir)

        # Only user.py should be counted
        assert result["files_checked"] == 1

    def test_returns_total_fields_count(self, tmp_path):
        schemas_dir = tmp_path / "schemas"
        schemas_dir.mkdir()
        schema_file = schemas_dir / "user.py"
        schema_file.write_text("""
class UserSchema:
    name: str
    email: str
    age: int
""")

        result = check_schemas_directory(schemas_dir)

        assert result["total_fields"] == 3

    def test_handles_empty_directory(self, tmp_path):
        schemas_dir = tmp_path / "schemas"
        schemas_dir.mkdir()

        result = check_schemas_directory(schemas_dir)

        assert result["files_checked"] == 0
        assert result["issues"] == []


class TestPrintReport:
    def test_returns_true_when_no_issues(self, capsys):
        config_result = {
            "visitor": SchemaVisitor(),
            "issues": [],
        }
        schemas_result = {
            "files_checked": 5,
            "issues": [],
            "total_fields": 20,
        }

        result = print_report(config_result, schemas_result)

        assert result is True
        captured = capsys.readouterr()
        assert "All schema validations passed" in captured.out

    def test_returns_false_when_issues_exist(self, capsys):
        config_result = {
            "visitor": SchemaVisitor(),
            "issues": [{"type": "error", "message": "Missing default", "field": "x"}],
        }
        schemas_result = {
            "files_checked": 5,
            "issues": [],
            "total_fields": 20,
        }

        result = print_report(config_result, schemas_result)

        assert result is False
        captured = capsys.readouterr()
        assert "ERROR" in captured.out

    def test_prints_warnings(self, capsys):
        config_result = {
            "visitor": SchemaVisitor(),
            "issues": [],
        }
        schemas_result = {
            "files_checked": 5,
            "issues": [
                {"type": "warning", "message": "Missing description", "field": "y"}
            ],
            "total_fields": 20,
        }

        result = print_report(config_result, schemas_result)

        assert result is False
        captured = capsys.readouterr()
        assert "WARNING" in captured.out


class TestGenerateFixSuggestions:
    def test_does_not_crash_with_no_issues(self, capsys):
        config_result = {"issues": []}
        schemas_result = {"issues": []}

        generate_fix_suggestions(config_result, schemas_result)

        captured = capsys.readouterr()
        assert "No issues to fix" in captured.out

    def test_suggests_fix_for_missing_default(self, capsys, tmp_path):
        config_file = tmp_path / "config.py"
        config_result = {
            "issues": [
                {
                    "type": "error",
                    "file": str(config_file),
                    "field": "database_url",
                    "message": "Config field has no default value",
                }
            ]
        }
        schemas_result = {"issues": []}

        generate_fix_suggestions(config_result, schemas_result)

        captured = capsys.readouterr()
        assert "database_url" in captured.out
        assert 'Field(default="...")' in captured.out

    def test_suggests_fix_for_missing_description(self, capsys, tmp_path):
        schema_file = tmp_path / "schema.py"
        config_result = {"issues": []}
        schemas_result = {
            "issues": [
                {
                    "type": "warning",
                    "file": str(schema_file),
                    "class": "UserSchema",
                    "field": "name",
                    "message": "Schema field lacks Field(description=...)",
                }
            ]
        }

        generate_fix_suggestions(config_result, schemas_result)

        captured = capsys.readouterr()
        assert "name" in captured.out
        assert "description=" in captured.out


# ---------------------------------------------------------------------------
# Coverage gap: visit_AnnAssign outside class (line 47)
# ---------------------------------------------------------------------------


class TestSchemaVisitorEdgeCases:
    def test_ann_assign_outside_class_is_ignored(self, tmp_path):
        """visit_AnnAssign returns early when current_class is None (line 47)."""
        test_file = tmp_path / "test_model.py"
        test_file.write_text("""
# Module-level annotation, not inside any class
top_level_var: int = 42

class MyModel:
    name: str
""")
        visitor = parse_file_for_schemas(test_file)
        # top_level_var should NOT appear in fields
        field_names = [f["name"] for f in visitor.fields]
        assert "top_level_var" not in field_names
        assert "name" in field_names

    def test_subscript_target_ann_assign(self, tmp_path):
        """visit_AnnAssign with subscript target (lines 52-59)."""
        test_file = tmp_path / "test_model.py"
        test_file.write_text("""
from typing import Optional

class MyModel:
    name: str
    optional_field: Optional[int] = None
""")
        visitor = parse_file_for_schemas(test_file)
        field_names = [f["name"] for f in visitor.fields]
        assert "name" in field_names
        assert "optional_field" in field_names

    def test_complex_subscript_target_skipped(self, tmp_path):
        """visit_AnnAssign with non-Name subscript value returns (line 56-57)."""
        import ast as stdlib_ast
        visitor = SchemaVisitor()
        visitor.current_class = "MyModel"
        # Manually create a node with Subscript target where value is not Name
        node = stdlib_ast.AnnAssign(
            target=stdlib_ast.Subscript(
                value=stdlib_ast.Attribute(
                    value=stdlib_ast.Name(id="self", ctx=stdlib_ast.Load()),
                    attr="data",
                    ctx=stdlib_ast.Load(),
                ),
                slice=stdlib_ast.Constant(value=0),
                ctx=stdlib_ast.Store(),
            ),
            annotation=stdlib_ast.Name(id="int", ctx=stdlib_ast.Load()),
            value=stdlib_ast.Constant(value=0),
            simple=0,
        )
        visitor.visit_AnnAssign(node)
        assert len(visitor.fields) == 0

    def test_non_name_non_subscript_target_skipped(self, tmp_path):
        """visit_AnnAssign with target that's neither Name nor Subscript (line 58-59)."""
        import ast as stdlib_ast
        visitor = SchemaVisitor()
        visitor.current_class = "MyModel"
        node = stdlib_ast.AnnAssign(
            target=stdlib_ast.Attribute(
                value=stdlib_ast.Name(id="self", ctx=stdlib_ast.Load()),
                attr="field",
                ctx=stdlib_ast.Store(),
            ),
            annotation=stdlib_ast.Name(id="int", ctx=stdlib_ast.Load()),
            value=None,
            simple=0,
        )
        visitor.visit_AnnAssign(node)
        assert len(visitor.fields) == 0

    def test_empty_field_name_guard(self, tmp_path):
        """visit_AnnAssign returns when field_name is empty (line 61-62)."""
        import ast as stdlib_ast
        visitor = SchemaVisitor()
        visitor.current_class = "MyModel"
        node = stdlib_ast.AnnAssign(
            target=stdlib_ast.Name(id="", ctx=stdlib_ast.Store()),
            annotation=stdlib_ast.Name(id="int", ctx=stdlib_ast.Load()),
            value=None,
            simple=1,
        )
        visitor.visit_AnnAssign(node)
        assert len(visitor.fields) == 0


# ---------------------------------------------------------------------------
# Coverage gap: print_report file path + class display (lines 194-197)
# ---------------------------------------------------------------------------


class TestPrintReportEdgeCases:
    def test_prints_file_path_and_class(self, capsys, tmp_path, monkeypatch):
        """print_report shows file path relative to root and class (lines 193-197)."""
        monkeypatch.setattr("validate_schemas.get_project_root", lambda: tmp_path)
        config_result = {
            "visitor": SchemaVisitor(),
            "issues": [
                {
                    "type": "error",
                    "file": str(tmp_path / "config.py"),
                    "class": "Settings",
                    "field": "database_url",
                    "message": "Config field has no default value",
                }
            ],
        }
        schemas_result = {
            "files_checked": 0,
            "issues": [],
            "total_fields": 0,
        }
        result = print_report(config_result, schemas_result)
        assert result is False
        captured = capsys.readouterr()
        assert "Class: Settings" in captured.out
        assert "Field: database_url" in captured.out
        assert "File: config.py" in captured.out

    def test_prints_issue_without_file(self, capsys):
        """print_report handles issue without 'file' key."""
        config_result = {
            "visitor": SchemaVisitor(),
            "issues": [
                {
                    "type": "error",
                    "field": "x",
                    "message": "Some error",
                }
            ],
        }
        schemas_result = {
            "files_checked": 0,
            "issues": [],
            "total_fields": 0,
        }
        result = print_report(config_result, schemas_result)
        assert result is False
        captured = capsys.readouterr()
        assert "ERROR" in captured.out


# ---------------------------------------------------------------------------
# Coverage gap: generate_fix_suggestions path fallback (line 230)
# ---------------------------------------------------------------------------


class TestGenerateFixSuggestionsEdgeCases:
    def test_fallback_when_file_not_under_project_root(self, capsys):
        """generate_fix_suggestions falls back to absolute path (line 231-233)."""
        config_result = {
            "issues": [
                {
                    "type": "error",
                    "file": "/some/random/path/config.py",
                    "field": "db_url",
                    "message": "Config field has no default value",
                }
            ]
        }
        schemas_result = {"issues": []}
        generate_fix_suggestions(config_result, schemas_result)
        captured = capsys.readouterr()
        assert "/some/random/path/config.py" in captured.out
        assert "db_url" in captured.out

    def test_fix_for_missing_description(self, capsys):
        """generate_fix_suggestions handles 'lacks Field(description=' issues."""
        config_result = {"issues": []}
        schemas_result = {
            "issues": [
                {
                    "type": "warning",
                    "file": "/tmp/schema.py",
                    "class": "UserSchema",
                    "field": "email",
                    "message": "Schema field lacks Field(description=...)",
                }
            ]
        }
        generate_fix_suggestions(config_result, schemas_result)
        captured = capsys.readouterr()
        assert "email" in captured.out
        assert "description=" in captured.out

    def test_fix_with_unknown_file(self, capsys):
        """generate_fix_suggestions handles issue without 'file' key."""
        config_result = {
            "issues": [
                {
                    "type": "error",
                    "message": "Config field has no default value",
                    "field": "x",
                }
            ]
        }
        schemas_result = {"issues": []}
        generate_fix_suggestions(config_result, schemas_result)
        captured = capsys.readouterr()
        assert "unknown" in captured.out


# ---------------------------------------------------------------------------
# Coverage gap: main() function (lines 247-269, 273)
# ---------------------------------------------------------------------------


class TestMain:
    def test_main_exits_0_when_valid(self, monkeypatch, tmp_path):
        """main() exits 0 when no issues found (lines 247-269)."""
        from validate_schemas import main

        config_file = tmp_path / "apps" / "backend" / "src" / "config.py"
        config_file.parent.mkdir(parents=True, exist_ok=True)
        config_file.write_text("""
class Settings:
    debug: bool = False
""")
        schemas_dir = tmp_path / "apps" / "backend" / "src" / "schemas"
        schemas_dir.mkdir(parents=True, exist_ok=True)
        schema_file = schemas_dir / "user.py"
        schema_file.write_text("""
from pydantic import Field
class UserSchema:
    name: str = Field(description="The name")
""")

        monkeypatch.setattr(
            "validate_schemas.get_project_root", lambda: tmp_path
        )
        monkeypatch.setattr(sys, "argv", ["validate_schemas.py"])

        with pytest.raises(SystemExit) as exc:
            main()
        assert exc.value.code == 0

    def test_main_exits_1_when_issues(self, monkeypatch, tmp_path):
        """main() exits 1 when issues found."""
        from validate_schemas import main

        config_file = tmp_path / "apps" / "backend" / "src" / "config.py"
        config_file.parent.mkdir(parents=True, exist_ok=True)
        config_file.write_text("""
class Settings:
    database_url: str
""")
        schemas_dir = tmp_path / "apps" / "backend" / "src" / "schemas"
        schemas_dir.mkdir(parents=True, exist_ok=True)

        monkeypatch.setattr(
            "validate_schemas.get_project_root", lambda: tmp_path
        )
        monkeypatch.setattr(sys, "argv", ["validate_schemas.py"])

        with pytest.raises(SystemExit) as exc:
            main()
        assert exc.value.code == 1

    def test_main_with_fix_flag(self, monkeypatch, tmp_path):
        """main() with --fix flag generates suggestions (lines 266-267)."""
        from validate_schemas import main

        config_file = tmp_path / "apps" / "backend" / "src" / "config.py"
        config_file.parent.mkdir(parents=True, exist_ok=True)
        config_file.write_text("""
class Settings:
    database_url: str
""")
        schemas_dir = tmp_path / "apps" / "backend" / "src" / "schemas"
        schemas_dir.mkdir(parents=True, exist_ok=True)

        monkeypatch.setattr(
            "validate_schemas.get_project_root", lambda: tmp_path
        )
        monkeypatch.setattr(sys, "argv", ["validate_schemas.py", "--fix"])

        with pytest.raises(SystemExit) as exc:
            main()
        assert exc.value.code == 1