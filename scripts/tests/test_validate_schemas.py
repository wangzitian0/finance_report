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
