"""Tests for scripts/check_env_keys.py"""

import pytest
from pathlib import Path

# Import functions from the script
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

from check_env_keys import (
    get_project_root,
    parse_secrets_ctmpl,
    parse_env_example,
    parse_config_py,
    check_consistency,
    print_report,
    generate_fix_suggestions,
)


class TestGetProjectRoot:
    """Tests for get_project_root function."""

    def test_returns_path(self):
        """Should return a Path object."""
        result = get_project_root()
        assert isinstance(result, Path)

    def test_returns_parent_of_scripts_dir(self):
        """Should return parent of scripts directory."""
        result = get_project_root()
        # The scripts directory should be a child of project root
        assert (result / "scripts").exists() or result.name != "scripts"


class TestParseSecretsCtmpl:
    """Tests for parse_secrets_ctmpl function."""

    def test_returns_empty_set_for_missing_file(self, tmp_path, capsys):
        """Should return empty set when file doesn't exist."""
        missing_file = tmp_path / "nonexistent.ctmpl"
        result = parse_secrets_ctmpl(missing_file)

        assert result == set()
        captured = capsys.readouterr()
        assert "WARNING" in captured.out

    def test_extracts_env_var_keys(self, tmp_path):
        """Should extract KEY names from KEY=value lines."""
        ctmpl_file = tmp_path / "secrets.ctmpl"
        ctmpl_file.write_text("""DATABASE_URL={{ with secret "..." }}{{ .Data.data.url }}{{ end }}
S3_BUCKET={{ with secret "..." }}{{ .Data.data.bucket }}{{ end }}
""")

        result = parse_secrets_ctmpl(ctmpl_file)

        assert "DATABASE_URL" in result
        assert "S3_BUCKET" in result
        assert len(result) == 2

    def test_skips_template_variable_assignments(self, tmp_path):
        """Should skip {{- $var := ...}} template variable assignments."""
        ctmpl_file = tmp_path / "secrets.ctmpl"
        ctmpl_file.write_text("""{{- $pg_password := with secret "..." }}{{ .Data.data.password }}{{ end }}
DATABASE_URL=postgres://user:{{ $pg_password }}@host/db
""")

        result = parse_secrets_ctmpl(ctmpl_file)

        # Should only have DATABASE_URL, not the template var
        assert "DATABASE_URL" in result
        assert len(result) == 1

    def test_skips_control_flow_lines(self, tmp_path):
        """Should skip {{- with/end/if/else ...}} control flow."""
        ctmpl_file = tmp_path / "secrets.ctmpl"
        ctmpl_file.write_text("""{{- with secret "secret/path" -}}
DATABASE_URL={{ .Data.data.url }}
{{- end }}
{{- if .Data.data.optional }}
OPTIONAL_KEY={{ .Data.data.optional }}
{{- else }}
FALLBACK_KEY=default
{{- end }}
""")

        result = parse_secrets_ctmpl(ctmpl_file)

        assert "DATABASE_URL" in result
        assert "OPTIONAL_KEY" in result
        assert "FALLBACK_KEY" in result

    def test_handles_empty_file(self, tmp_path):
        """Should return empty set for empty file."""
        ctmpl_file = tmp_path / "secrets.ctmpl"
        ctmpl_file.write_text("")

        result = parse_secrets_ctmpl(ctmpl_file)

        assert result == set()


class TestParseEnvExample:
    """Tests for parse_env_example function."""

    def test_returns_empty_set_for_missing_file(self, tmp_path, capsys):
        """Should return empty set when file doesn't exist."""
        missing_file = tmp_path / ".env.example"
        result = parse_env_example(missing_file)

        assert result == set()
        captured = capsys.readouterr()
        assert "WARNING" in captured.out

    def test_extracts_simple_keys(self, tmp_path):
        """Should extract simple KEY=value pairs."""
        env_file = tmp_path / ".env.example"
        env_file.write_text("""DATABASE_URL=postgres://localhost/db
DEBUG=true
API_KEY=secret123
""")

        result = parse_env_example(env_file)

        assert "DATABASE_URL" in result
        assert "DEBUG" in result
        assert "API_KEY" in result

    def test_skips_comments(self, tmp_path):
        """Should skip lines starting with #."""
        env_file = tmp_path / ".env.example"
        env_file.write_text("""# This is a comment
DATABASE_URL=value
# Another comment
DEBUG=true
""")

        result = parse_env_example(env_file)

        assert "DATABASE_URL" in result
        assert "DEBUG" in result
        assert len(result) == 2

    def test_skips_blank_lines(self, tmp_path):
        """Should skip blank lines."""
        env_file = tmp_path / ".env.example"
        env_file.write_text("""DATABASE_URL=value

DEBUG=true

""")

        result = parse_env_example(env_file)

        assert len(result) == 2

    def test_handles_export_prefix(self, tmp_path):
        """Should handle optional 'export ' prefix."""
        env_file = tmp_path / ".env.example"
        env_file.write_text("""export DATABASE_URL=value
DEBUG=true
export API_KEY=secret
""")

        result = parse_env_example(env_file)

        assert "DATABASE_URL" in result
        assert "DEBUG" in result
        assert "API_KEY" in result

    def test_handles_whitespace(self, tmp_path):
        """Should handle leading whitespace."""
        env_file = tmp_path / ".env.example"
        env_file.write_text("""  DATABASE_URL=value
    export DEBUG=true
""")

        result = parse_env_example(env_file)

        assert "DATABASE_URL" in result
        assert "DEBUG" in result


class TestParseConfigPy:
    """Tests for parse_config_py function."""

    def test_returns_empty_dict_for_missing_file(self, tmp_path, capsys):
        """Should return empty dict when file doesn't exist."""
        missing_file = tmp_path / "config.py"
        result = parse_config_py(missing_file)

        assert result == {}
        captured = capsys.readouterr()
        assert "WARNING" in captured.out

    def test_extracts_field_from_settings_class(self, tmp_path):
        """Should extract annotated fields from Settings class."""
        config_file = tmp_path / "config.py"
        config_file.write_text("""
from pydantic import Field
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    database_url: str = Field(default="postgres://localhost/db")
    debug: bool = False
""")

        result = parse_config_py(config_file)

        assert "database_url" in result
        assert result["database_url"]["env_name"] == "DATABASE_URL"
        assert result["database_url"]["has_default"] is True
        assert "debug" in result

    def test_extracts_validation_alias(self, tmp_path):
        """Should extract validation_alias from Field()."""
        config_file = tmp_path / "config.py"
        config_file.write_text("""
from pydantic import Field
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    db_url: str = Field(validation_alias="DATABASE_URL")
""")

        result = parse_config_py(config_file)

        assert "db_url" in result
        assert result["db_url"]["env_name"] == "DATABASE_URL"

    def test_extracts_alias_choices(self, tmp_path):
        """Should extract AliasChoices from Field()."""
        config_file = tmp_path / "config.py"
        config_file.write_text("""
from pydantic import Field, AliasChoices
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    s3_key: str = Field(validation_alias=AliasChoices("S3_ACCESS_KEY", "s3_access_key"))
""")

        result = parse_config_py(config_file)

        assert "s3_key" in result
        assert result["s3_key"]["env_name"] == "S3_ACCESS_KEY"

    def test_skips_model_config(self, tmp_path):
        """Should skip model_config field."""
        config_file = tmp_path / "config.py"
        config_file.write_text("""
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    model_config = {"env_file": ".env"}
    database_url: str = "default"
""")

        result = parse_config_py(config_file)

        assert "model_config" not in result
        assert "database_url" in result

    def test_skips_methods_and_decorators(self, tmp_path):
        """Should skip methods and decorators."""
        config_file = tmp_path / "config.py"
        config_file.write_text("""
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    database_url: str = "default"
    
    @property
    def db_string(self) -> str:
        return self.database_url
    
    def get_url(self):
        return self.database_url
""")

        result = parse_config_py(config_file)

        assert len(result) == 1
        assert "database_url" in result

    def test_stops_at_next_class(self, tmp_path):
        """Should stop parsing when another class is encountered."""
        config_file = tmp_path / "config.py"
        config_file.write_text("""
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    database_url: str = "default"

class OtherModel:
    other_field: str = "value"
""")

        result = parse_config_py(config_file)

        assert "database_url" in result
        assert "other_field" not in result


class TestCheckConsistency:
    """Tests for check_consistency function."""

    def test_returns_is_consistent_true_when_all_match(self):
        """Should return is_consistent=True when all sources match."""
        ctmpl_keys = {"DATABASE_URL", "API_KEY"}
        config_fields = {
            "database_url": {"env_name": "DATABASE_URL"},
            "api_key": {"env_name": "API_KEY"},
        }
        env_example_keys = {"DATABASE_URL", "API_KEY"}

        result = check_consistency(ctmpl_keys, config_fields, env_example_keys)

        assert result["is_consistent"] is True
        assert result["missing_in_config"] == set()
        assert result["undocumented_in_example"] == set()

    def test_detects_missing_in_config(self):
        """Should detect keys in ctmpl but not in config."""
        ctmpl_keys = {"DATABASE_URL", "MISSING_KEY"}
        config_fields = {
            "database_url": {"env_name": "DATABASE_URL"},
        }
        env_example_keys = {"DATABASE_URL", "MISSING_KEY"}

        result = check_consistency(ctmpl_keys, config_fields, env_example_keys)

        assert result["is_consistent"] is False
        assert "MISSING_KEY" in result["missing_in_config"]

    def test_detects_undocumented_in_example(self):
        """Should detect keys in config but not in env_example."""
        ctmpl_keys = {"DATABASE_URL"}
        config_fields = {
            "database_url": {"env_name": "DATABASE_URL"},
            "debug": {"env_name": "DEBUG"},
        }
        env_example_keys = {"DATABASE_URL"}

        result = check_consistency(ctmpl_keys, config_fields, env_example_keys)

        assert result["is_consistent"] is False
        assert "DEBUG" in result["undocumented_in_example"]

    def test_ignores_next_public_keys_in_suspicious(self):
        """Should NOT flag NEXT_PUBLIC_ keys as suspicious."""
        ctmpl_keys = {"DATABASE_URL"}
        config_fields = {
            "database_url": {"env_name": "DATABASE_URL"},
        }
        env_example_keys = {"DATABASE_URL", "NEXT_PUBLIC_API_URL"}

        result = check_consistency(ctmpl_keys, config_fields, env_example_keys)

        assert "NEXT_PUBLIC_API_URL" not in result["suspicious_extra_keys"]

    def test_ignores_dokploy_keys_in_suspicious(self):
        """Should NOT flag DOKPLOY_ keys as suspicious."""
        ctmpl_keys = {"DATABASE_URL"}
        config_fields = {
            "database_url": {"env_name": "DATABASE_URL"},
        }
        env_example_keys = {"DATABASE_URL", "DOKPLOY_TOKEN"}

        result = check_consistency(ctmpl_keys, config_fields, env_example_keys)

        assert "DOKPLOY_TOKEN" not in result["suspicious_extra_keys"]

    def test_flags_other_extra_keys_as_suspicious(self):
        """Should flag other extra keys as suspicious."""
        ctmpl_keys = {"DATABASE_URL"}
        config_fields = {
            "database_url": {"env_name": "DATABASE_URL"},
        }
        env_example_keys = {"DATABASE_URL", "RANDOM_KEY"}

        result = check_consistency(ctmpl_keys, config_fields, env_example_keys)

        assert "RANDOM_KEY" in result["suspicious_extra_keys"]


class TestPrintReport:
    """Tests for print_report function."""

    def test_does_not_crash_with_consistent_result(self, capsys):
        """Should print report without crashing when consistent."""
        result = {
            "ctmpl_keys": {"KEY1"},
            "config_env_names": {"KEY1"},
            "env_example_keys": {"KEY1"},
            "missing_in_config": set(),
            "undocumented_in_example": set(),
            "suspicious_extra_keys": set(),
            "is_consistent": True,
        }

        print_report(result)

        captured = capsys.readouterr()
        assert "Consistency check passed" in captured.out

    def test_does_not_crash_with_inconsistent_result(self, capsys):
        """Should print report without crashing when inconsistent."""
        result = {
            "ctmpl_keys": {"KEY1", "KEY2"},
            "config_env_names": {"KEY1"},
            "env_example_keys": {"KEY1"},
            "missing_in_config": {"KEY2"},
            "undocumented_in_example": set(),
            "suspicious_extra_keys": set(),
            "is_consistent": False,
        }

        print_report(result)

        captured = capsys.readouterr()
        assert "ERROR" in captured.out
        assert "KEY2" in captured.out

    def test_verbose_shows_suspicious_keys(self, capsys):
        """Should show suspicious keys when verbose=True."""
        result = {
            "ctmpl_keys": {"KEY1"},
            "config_env_names": {"KEY1"},
            "env_example_keys": {"KEY1", "EXTRA"},
            "missing_in_config": set(),
            "undocumented_in_example": set(),
            "suspicious_extra_keys": {"EXTRA"},
            "is_consistent": True,
        }

        print_report(result, verbose=True)

        captured = capsys.readouterr()
        assert "EXTRA" in captured.out


class TestGenerateFixSuggestions:
    """Tests for generate_fix_suggestions function."""

    def test_does_not_crash_with_no_issues(self, capsys):
        """Should not crash when no issues exist."""
        result = {
            "missing_in_config": set(),
            "undocumented_in_example": set(),
        }

        generate_fix_suggestions(result)

        # Should not raise

    def test_suggests_config_fix_for_missing_keys(self, capsys):
        """Should suggest config.py fix for missing keys."""
        result = {
            "missing_in_config": {"DATABASE_URL"},
            "undocumented_in_example": set(),
        }

        generate_fix_suggestions(result)

        captured = capsys.readouterr()
        assert "config.py" in captured.out
        assert "DATABASE_URL" in captured.out

    def test_suggests_env_example_fix_for_undocumented(self, capsys):
        """Should suggest .env.example fix for undocumented keys."""
        result = {
            "missing_in_config": set(),
            "undocumented_in_example": {"DEBUG"},
        }

        generate_fix_suggestions(result)

        captured = capsys.readouterr()
        assert ".env.example" in captured.out
        assert "DEBUG=" in captured.out
