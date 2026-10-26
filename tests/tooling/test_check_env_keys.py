"""Tests for src.runtime.extension.env_keys"""

import pytest
from pathlib import Path

# Import functions from the script
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
# src.* lives under apps/backend, not repo root (#1669 moved this module out of
# the repo-root-relative common/config into apps/backend/src/runtime).
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "apps" / "backend"))

from src.runtime.extension.env_keys import (
    get_project_root,
    parse_env_example,
    settings_env_key_sets,
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

    def test_returns_project_root(self):
        """Should return the repository root directory."""
        result = get_project_root()
        assert (result / "common").exists()
        assert (result / "tools").exists()


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

    def test_counts_a_commented_canonical_example_as_documented(self, tmp_path):
        """AC-runtime.env-empty-values.1: an alias-chain key with no example value
        is documented as ``# KEY=`` (assigning it empty would shadow its chain),
        so the commented form must still count as documented."""
        env_file = tmp_path / ".env.example"
        env_file.write_text("""# AI provider API key (empty key = AI features disabled).
# ZAI_API_KEY=
#   export LLM_ENCRYPTION_KEYS=
DATABASE_URL=value
""")

        result = parse_env_example(env_file)

        assert result == {"ZAI_API_KEY", "LLM_ENCRYPTION_KEYS", "DATABASE_URL"}

    def test_prose_comments_are_not_mistaken_for_keys(self, tmp_path):
        """Only ``# KEY=`` counts — prose that merely mentions a key, or a section
        banner, must not register as a documented key. Inside a comment the ``=``
        must follow the key directly, so spaced prose stays prose."""
        env_file = tmp_path / ".env.example"
        env_file.write_text("""# === AI Provider ===
# AI provider API key (empty key = AI features disabled).
# Set this in your shell, not here.
# Rotate = prepend a new key and re-encrypt.
DEBUG=true
""")

        result = parse_env_example(env_file)

        assert result == {"DEBUG"}

    def test_assignments_keep_tolerating_spaces_around_equals(self, tmp_path):
        """Tightening the *commented* form must not change how real assignments
        parse — ``KEY = value`` stays a documented key."""
        env_file = tmp_path / ".env.example"
        env_file.write_text("DATABASE_URL = value\nexport DEBUG =true\n")

        result = parse_env_example(env_file)

        assert result == {"DATABASE_URL", "DEBUG"}


class TestSettingsEnvKeySets:
    """Tests for settings_env_key_sets: the real Settings model, not a source parse."""

    def test_lists_every_settings_field(self):
        from src.config import Settings

        assert set(settings_env_key_sets()) == set(Settings.model_fields)

    def test_unaliased_field_reads_its_upper_case_name(self):
        assert settings_env_key_sets()["debug"] == frozenset({"DEBUG"})

    def test_alias_choices_field_lists_every_accepted_name(self):
        assert settings_env_key_sets()["environment"] == frozenset(
            {"ENV", "ENVIRONMENT"}
        )


class TestCheckConsistency:
    """Tests for check_consistency function."""

    def test_returns_is_consistent_true_when_all_match(self):
        field_keys = {
            "database_url": frozenset({"DATABASE_URL"}),
            "api_key": frozenset({"API_KEY"}),
        }

        result = check_consistency(field_keys, {"DATABASE_URL", "API_KEY"})

        assert result["is_consistent"] is True
        assert result["undocumented_in_example"] == set()
        assert result["config_field_count"] == 2

    def test_detects_undocumented_in_example(self):
        field_keys = {
            "database_url": frozenset({"DATABASE_URL"}),
            "debug": frozenset({"DEBUG"}),
        }

        result = check_consistency(field_keys, {"DATABASE_URL"})

        assert result["is_consistent"] is False
        assert result["undocumented_in_example"] == {"DEBUG"}

    def test_documenting_any_alias_of_a_field_counts(self):
        field_keys = {"environment": frozenset({"ENV", "ENVIRONMENT"})}

        assert check_consistency(field_keys, {"ENVIRONMENT"})["is_consistent"] is True
        assert check_consistency(field_keys, {"ENV"})["is_consistent"] is True

    def test_an_aliased_field_with_no_documented_alias_is_reported_with_every_name(
        self,
    ):
        field_keys = {"environment": frozenset({"ENV", "ENVIRONMENT"})}

        result = check_consistency(field_keys, set())

        assert result["undocumented_in_example"] == {"ENV/ENVIRONMENT"}

    def test_ignores_next_public_keys_in_suspicious(self):
        field_keys = {"database_url": frozenset({"DATABASE_URL"})}

        result = check_consistency(field_keys, {"DATABASE_URL", "NEXT_PUBLIC_API_URL"})

        assert "NEXT_PUBLIC_API_URL" not in result["suspicious_extra_keys"]

    def test_ignores_dokploy_keys_in_suspicious(self):
        field_keys = {"database_url": frozenset({"DATABASE_URL"})}

        result = check_consistency(field_keys, {"DATABASE_URL", "DOKPLOY_TOKEN"})

        assert "DOKPLOY_TOKEN" not in result["suspicious_extra_keys"]

    def test_flags_other_extra_keys_as_suspicious(self):
        field_keys = {"database_url": frozenset({"DATABASE_URL"})}

        result = check_consistency(field_keys, {"DATABASE_URL", "RANDOM_KEY"})

        assert result["suspicious_extra_keys"] == {"RANDOM_KEY"}

    def test_an_alias_in_the_example_is_not_suspicious(self):
        field_keys = {"environment": frozenset({"ENV", "ENVIRONMENT"})}

        result = check_consistency(field_keys, {"ENV", "ENVIRONMENT"})

        assert result["suspicious_extra_keys"] == set()


def _report(**overrides):
    result = {
        "config_field_count": 1,
        "env_example_keys": {"KEY1"},
        "undocumented_in_example": set(),
        "suspicious_extra_keys": set(),
        "is_consistent": True,
    }
    result.update(overrides)
    return result


class TestPrintReport:
    """Tests for print_report function."""

    def test_prints_the_pass_line_when_consistent(self, capsys):
        print_report(_report())

        captured = capsys.readouterr()
        assert "Consistency check passed" in captured.out
        assert "secrets.ctmpl" not in captured.out

    def test_prints_undocumented_keys_and_the_failure_line(self, capsys):
        print_report(
            _report(undocumented_in_example={"SECRET_KEY"}, is_consistent=False)
        )

        captured = capsys.readouterr()
        assert "Undocumented" in captured.out
        assert "SECRET_KEY" in captured.out
        assert "Inconsistency found" in captured.out

    def test_verbose_shows_suspicious_keys(self, capsys):
        print_report(_report(suspicious_extra_keys={"EXTRA"}), verbose=True)

        assert "EXTRA" in capsys.readouterr().out

    def test_quiet_hides_suspicious_keys(self, capsys):
        print_report(_report(suspicious_extra_keys={"EXTRA"}))

        assert "EXTRA" not in capsys.readouterr().out


class TestGenerateFixSuggestions:
    """Tests for generate_fix_suggestions function."""

    def test_prints_nothing_when_no_issues_exist(self, capsys):
        generate_fix_suggestions(_report())

        assert capsys.readouterr().out == ""

    def test_suggests_env_example_fix_for_undocumented(self, capsys):
        generate_fix_suggestions(
            _report(undocumented_in_example={"DEBUG"}, is_consistent=False)
        )

        captured = capsys.readouterr()
        assert ".env.example" in captured.out
        assert "tools/generate_env_reference.py" in captured.out
        assert "DEBUG=" in captured.out


class TestMainFunction:
    def _run(self, monkeypatch, root, *argv):
        from src.runtime.extension.env_keys import main

        monkeypatch.setattr(
            "src.runtime.extension.env_keys.get_project_root", lambda: root
        )
        monkeypatch.setattr(sys, "argv", ["check_env_keys.py", *argv])
        with pytest.raises(SystemExit) as exc:
            main()
        return exc.value.code

    def test_main_exits_0_for_the_committed_env_example(self, monkeypatch):
        assert self._run(monkeypatch, get_project_root()) == 0

    def test_main_exits_1_when_the_example_documents_no_settings_key(
        self, monkeypatch, tmp_path
    ):
        (tmp_path / ".env.example").write_text("")

        assert self._run(monkeypatch, tmp_path) == 1

    def test_main_exits_1_when_the_example_is_missing(self, monkeypatch, tmp_path):
        assert self._run(monkeypatch, tmp_path) == 1

    def test_main_with_diff_flag_lists_keys_the_example_has_beyond_settings(
        self, monkeypatch, tmp_path, capsys
    ):
        documented = "".join(
            f"{min(keys)}=\n" for keys in settings_env_key_sets().values()
        )
        (tmp_path / ".env.example").write_text(documented + "EXTRA_FRONTEND_KEY=1\n")

        assert self._run(monkeypatch, tmp_path, "--diff") == 0
        assert "EXTRA_FRONTEND_KEY" in capsys.readouterr().out

    def test_main_with_fix_flag_prints_the_undocumented_keys(
        self, monkeypatch, tmp_path, capsys
    ):
        (tmp_path / ".env.example").write_text("")

        assert self._run(monkeypatch, tmp_path, "--fix") == 1
        output = capsys.readouterr().out
        assert "tools/generate_env_reference.py" in output
        assert "DEBUG=" in output
