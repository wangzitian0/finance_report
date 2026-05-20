"""Tests for scripts/build_ac_traceability.py.

Covers _load_registry, load_all_acs, find_test_files, collect_references,
helper utilities (_ac_sort_key, _is_manual, _rel, _md_escape, _slug),
render_document, and main() in both write and --check modes.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest import mock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import build_ac_traceability as bat  # noqa: E402


SAMPLE_REGISTRY = """\
version: '1.0'
total: 3
acs:
  - id: AC1.1.1
    epic: 1
    epic_name: phase0-setup
    description: 'System deployment check'
    mandatory: true
  - id: AC1.1.2
    epic: 1
    epic_name: phase0-setup
    description: 'Manual verification needed'
    mandatory: false
  - id: AC2.1.1
    epic: 2
    epic_name: double-entry-core
    description: 'Balanced entries stored'
    mandatory: true
"""

INFRA_REGISTRY = """\
version: '1.0'
total: 1
acs:
  - id: IAC1.1.1
    epic: 1
    epic_name: phase0-setup
    description: 'CI pipeline production deploy'
    mandatory: true
"""


class TestLoadRegistry:
    def test_loads_entries(self, tmp_path):
        f = tmp_path / "reg.yaml"
        f.write_text(SAMPLE_REGISTRY)
        acs = bat._load_registry(f)
        assert len(acs) == 3

    def test_field_values(self, tmp_path):
        f = tmp_path / "reg.yaml"
        f.write_text(SAMPLE_REGISTRY)
        acs = bat._load_registry(f)
        ac = acs[0]
        assert ac.id == "AC1.1.1"
        assert ac.epic == 1
        assert ac.epic_name == "phase0-setup"
        assert ac.mandatory is True

    def test_missing_file_exits(self, tmp_path):
        with pytest.raises(SystemExit):
            bat._load_registry(tmp_path / "nonexistent.yaml")

    def test_empty_file_returns_empty(self, tmp_path):
        f = tmp_path / "empty.yaml"
        f.write_text("{}")
        acs = bat._load_registry(f)
        assert acs == []


class TestLoadAllAcs:
    def test_combines_both_registries(self, tmp_path):
        feat = tmp_path / "ac_registry.yaml"
        feat.write_text(SAMPLE_REGISTRY)
        infra = tmp_path / "infra_registry.yaml"
        infra.write_text(INFRA_REGISTRY)
        acs = bat.load_all_acs(feat, infra)
        ids = [ac.id for ac in acs]
        assert "AC1.1.1" in ids
        assert "IAC1.1.1" in ids

    def test_deduplication_feature_wins(self, tmp_path):
        dup_registry = """\
version: '1.0'
total: 1
acs:
  - id: AC1.1.1
    epic: 1
    epic_name: infra-version
    description: 'Infra duplicate'
    mandatory: false
"""
        feat = tmp_path / "ac_registry.yaml"
        feat.write_text(SAMPLE_REGISTRY)
        infra = tmp_path / "infra_registry.yaml"
        infra.write_text(dup_registry)
        acs = bat.load_all_acs(feat, infra)
        matching = [ac for ac in acs if ac.id == "AC1.1.1"]
        assert len(matching) == 1
        assert matching[0].epic_name == "phase0-setup"


class TestFindTestFiles:
    def test_finds_test_py(self, tmp_path):
        d = tmp_path / "tests"
        d.mkdir()
        (d / "test_accounting.py").write_text("")
        files = bat.find_test_files([d])
        assert any("test_accounting.py" in str(f) for f in files)

    def test_finds_test_ts(self, tmp_path):
        d = tmp_path / "tests"
        d.mkdir()
        (d / "accounting.test.ts").write_text("")
        files = bat.find_test_files([d])
        assert any(".test.ts" in str(f) for f in files)

    def test_excludes_node_modules(self, tmp_path):
        d = tmp_path / "tests"
        d.mkdir()
        nm = d / "node_modules"
        nm.mkdir()
        (nm / "test_bad.py").write_text("")
        files = bat.find_test_files([d])
        assert not any("node_modules" in str(f) for f in files)

    def test_missing_dir_skipped(self, tmp_path):
        files = bat.find_test_files([tmp_path / "nonexistent"])
        assert files == []

    def test_returns_sorted(self, tmp_path):
        d = tmp_path / "tests"
        d.mkdir()
        (d / "test_z.py").write_text("")
        (d / "test_a.py").write_text("")
        files = bat.find_test_files([d])
        names = [f.name for f in files]
        assert names == sorted(names)


class TestCollectReferences:
    def test_basic_collection(self, tmp_path):
        f = tmp_path / "test_x.py"
        f.write_text("# AC1.1.1 AC2.1.1\n")
        refs = bat.collect_references([f])
        assert "AC1.1.1" in refs
        assert "AC2.1.1" in refs

    def test_each_file_at_most_once_per_ac(self, tmp_path):
        f = tmp_path / "test_x.py"
        f.write_text("AC1.1.1 again AC1.1.1\n")
        refs = bat.collect_references([f])
        assert len(refs["AC1.1.1"].real_files) == 1

    def test_multiple_files(self, tmp_path):
        f1 = tmp_path / "test_a.py"
        f2 = tmp_path / "test_b.py"
        f1.write_text("AC1.1.1")
        f2.write_text("AC1.1.1")
        refs = bat.collect_references([f1, f2])
        assert len(refs["AC1.1.1"].real_files) == 2

    def test_unreadable_file_skipped(self, tmp_path):
        f = tmp_path / "test_x.py"
        f.write_text("AC1.1.1")
        with mock.patch.object(Path, "read_text", side_effect=OSError("no access")):
            refs = bat.collect_references([f])
        assert refs == {}

    def test_classifies_placeholder_and_stub_references(self, tmp_path):
        """AC8.13.35: The audit builder separates placeholder and stub references."""
        placeholder = tmp_path / "gap.test.ts"
        placeholder.write_text("test('AC1.1.1', () => expect(true).toBe(true));\n")
        stub_dir = tmp_path / "_ac_stubs"
        stub_dir.mkdir()
        stub = stub_dir / "test_stub.py"
        stub.write_text("# AC2.1.1\ndef test_stub(): pass\n")

        refs = bat.collect_references([placeholder, stub])

        assert refs["AC1.1.1"].placeholder_files == {placeholder}
        assert refs["AC2.1.1"].stub_files == {stub}


class TestHelpers:
    def test_ac_sort_key_numeric(self):
        assert bat._ac_sort_key("AC1.2.10") > bat._ac_sort_key("AC1.2.9")

    def test_ac_sort_key_basic(self):
        assert bat._ac_sort_key("AC1.1.1") == (1, 1, 1)

    def test_is_manual_manual_verification(self):
        ac = bat.AC("AC1.1.1", 1, "x", "manual verification needed", True)
        assert bat._is_manual(ac)

    def test_is_manual_production_deploy(self):
        ac = bat.AC("AC1.1.1", 1, "x", "production deploy check", True)
        assert bat._is_manual(ac)

    def test_is_manual_false(self):
        ac = bat.AC("AC1.1.1", 1, "x", "run automated tests", True)
        assert not bat._is_manual(ac)

    def test_is_deprecated_full_strikethrough(self):
        ac = bat.AC("AC12.24.1", 12, "x", "~~metrics endpoint deprecated~~", True)
        assert bat._is_deprecated(ac)

    def test_is_deprecated_false_no_strikethrough(self):
        ac = bat.AC("AC1.1.1", 1, "x", "normal description", True)
        assert not bat._is_deprecated(ac)

    def test_is_deprecated_false_partial_strikethrough(self):
        ac = bat.AC("AC1.1.1", 1, "x", "~~only start strikethrough", True)
        assert not bat._is_deprecated(ac)

    def test_is_deprecated_false_empty_like(self):
        # ~~~~ has no content between the markers; regex requires at least one char
        ac = bat.AC("AC1.1.1", 1, "x", "~~~~", True)
        assert not bat._is_deprecated(ac)

    def test_is_deprecated_minimum_valid(self):
        # ~~x~~ is the minimum valid deprecated description (one char between markers)
        ac = bat.AC("AC1.1.1", 1, "x", "~~x~~", True)
        assert bat._is_deprecated(ac)

    def test_rel_inside_repo(self, tmp_path):
        f = tmp_path / "apps" / "backend" / "tests" / "test_x.py"
        f.parent.mkdir(parents=True)
        f.touch()
        with mock.patch.object(bat, "REPO_ROOT", tmp_path):
            result = bat._rel(f)
        assert result == "apps/backend/tests/test_x.py"

    def test_rel_outside_repo(self, tmp_path):
        f = tmp_path / "some" / "external" / "file.py"
        result = bat._rel(f)
        assert "external" in result

    def test_md_escape_pipe(self):
        assert bat._md_escape("a|b") == "a\\|b"

    def test_md_escape_newline(self):
        assert bat._md_escape("a\nb") == "a b"

    def test_md_escape_strips(self):
        assert bat._md_escape("  text  ") == "text"

    def test_slug_with_name(self):
        assert bat._slug(1, "phase0-setup") == "epic-001-phase0-setup"

    def test_slug_without_name(self):
        assert bat._slug(5, "") == "epic-005"

    def test_slug_sanitizes_special_chars(self):
        result = bat._slug(2, "Double Entry / Core")
        assert "/" not in result
        assert " " not in result

    def test_strip_date_normalizes_date_line(self):
        text = "> **Generated**: 2024-01-01 (mechanically by `scripts/build_ac_traceability.py`)"
        assert bat._strip_date(text) == "> **Generated**: DATE (mechanically by `scripts/build_ac_traceability.py`)"

    def test_strip_date_different_dates_produce_same_output(self):
        old = "> **Generated**: 2024-01-01 (mechanically by `scripts/build_ac_traceability.py`)"
        new = "> **Generated**: 2099-12-31 (mechanically by `scripts/build_ac_traceability.py`)"
        assert bat._strip_date(old) == bat._strip_date(new)

    def test_strip_date_leaves_other_lines_unchanged(self):
        text = "## Some Heading\n> **Generated**: 2024-01-01\nother content"
        result = bat._strip_date(text)
        assert "## Some Heading" in result
        assert "other content" in result
        assert "2024-01-01" not in result


class TestRenderDocument:
    def _make_acs(self):
        return [
            bat.AC("AC1.1.1", 1, "phase0-setup", "Setup complete", True),
            bat.AC("AC1.1.2", 1, "phase0-setup", "Manual verification needed", False),
            bat.AC("AC2.1.1", 2, "double-entry", "Balanced entries", True),
        ]

    def test_contains_header(self, tmp_path):
        acs = self._make_acs()
        rendered = bat.render_document(acs, {}, [tmp_path], "2024-01-01")
        assert "# AC-to-Test Traceability Audit" in rendered

    def test_contains_executive_summary(self, tmp_path):
        acs = self._make_acs()
        rendered = bat.render_document(acs, {}, [tmp_path], "2024-01-01")
        assert "Executive Summary" in rendered

    def test_covered_ac_shows_checkmark(self, tmp_path):
        acs = self._make_acs()
        f = tmp_path / "test_x.py"
        f.touch()
        refs = {"AC1.1.1": bat.ACReferenceStats(real_files={f})}
        rendered = bat.render_document(acs, refs, [tmp_path], "2024-01-01")
        assert "✅ real" in rendered

    def test_missing_mandatory_shows_missing(self, tmp_path):
        acs = self._make_acs()
        rendered = bat.render_document(acs, {}, [tmp_path], "2024-01-01")
        assert "❌ missing" in rendered

    def test_manual_ac_shows_yellow(self, tmp_path):
        acs = [bat.AC("AC1.1.1", 1, "x", "manual verification", True)]
        rendered = bat.render_document(acs, {}, [tmp_path], "2024-01-01")
        assert "🟡 manual" in rendered

    def test_optional_no_ref_shows_grey(self, tmp_path):
        acs = [bat.AC("AC1.1.2", 1, "x", "optional feature", False)]
        rendered = bat.render_document(acs, {}, [tmp_path], "2024-01-01")
        assert "⚪ (optional, no ref)" in rendered

    def test_optional_with_ref_shows_optional_checkmark(self, tmp_path):
        acs = [bat.AC("AC1.1.2", 1, "x", "optional feature", False)]
        f = tmp_path / "test_x.py"
        f.touch()
        refs = {"AC1.1.2": bat.ACReferenceStats(real_files={f})}
        rendered = bat.render_document(acs, refs, [tmp_path], "2024-01-01")
        assert "✅ real (optional)" in rendered

    def test_placeholder_and_stub_statuses_are_not_real_coverage(self, tmp_path):
        """AC8.13.35: Audit output reports fake references without counting coverage."""
        acs = [
            bat.AC("AC1.1.1", 1, "x", "placeholder AC", True),
            bat.AC("AC1.1.2", 1, "x", "stub AC", True),
        ]
        rendered = bat.render_document(
            acs,
            {
                "AC1.1.1": bat.ACReferenceStats(
                    placeholder_files={tmp_path / "gap.test.ts"}
                ),
                "AC1.1.2": bat.ACReferenceStats(
                    stub_files={tmp_path / "_ac_stubs" / "test_stub.py"}
                ),
            },
            [tmp_path],
            "2024-01-01",
        )

        assert "| **Mandatory ACs with real test reference** | 0 | 0.0% |" in rendered
        assert "| **Mandatory ACs with only placeholder reference** | 1 | - |" in rendered
        assert "| **Mandatory ACs with only stub reference** | 1 | - |" in rendered
        assert "🧪 placeholder-only" in rendered
        assert "🧱 stub-only" in rendered

    def test_deprecated_ac_shows_deprecated_status(self, tmp_path):
        acs = [bat.AC("AC12.24.1", 12, "x", "~~deprecated feature~~", True)]
        rendered = bat.render_document(acs, {}, [tmp_path], "2024-01-01")
        assert "🚫 deprecated" in rendered

    def test_deprecated_ac_not_counted_as_missing(self, tmp_path):
        acs = [bat.AC("AC12.24.1", 12, "x", "~~deprecated feature~~", True)]
        rendered = bat.render_document(acs, {}, [tmp_path], "2024-01-01")
        assert "❌ missing" not in rendered

    def test_deprecated_ac_not_counted_as_mandatory(self, tmp_path):
        acs = [
            bat.AC("AC1.1.1", 1, "x", "normal AC", True),
            bat.AC("AC12.24.1", 12, "x", "~~deprecated~~", True),
        ]
        rendered = bat.render_document(
            acs,
            {"AC1.1.1": bat.ACReferenceStats(real_files={tmp_path / "test_x.py"})},
            [tmp_path],
            "2024-01-01",
        )
        # Only 1 mandatory AC (the non-deprecated one), covered 1
        assert "| **Mandatory ACs** | 1 |" in rendered

    def test_deprecated_ac_appears_in_executive_summary(self, tmp_path):
        acs = [bat.AC("AC12.24.1", 12, "x", "~~deprecated~~", True)]
        rendered = bat.render_document(acs, {}, [tmp_path], "2024-01-01")
        assert "**Deprecated ACs**" in rendered

    def test_empty_epic_name_fallback(self, tmp_path):
        acs = [bat.AC("AC5.1.1", 5, "", "Some AC", True)]
        rendered = bat.render_document(acs, {}, [tmp_path], "2024-01-01")
        assert "EPIC-005" in rendered

    def test_zero_acs_no_crash(self, tmp_path):
        rendered = bat.render_document([], {}, [tmp_path], "2024-01-01")
        assert "# AC-to-Test Traceability Audit" in rendered

    def test_regeneration_footer(self, tmp_path):
        rendered = bat.render_document([], {}, [tmp_path], "2024-01-01")
        assert "Regeneration" in rendered


class TestMain:
    def _build_env(self, tmp_path):
        feat = tmp_path / "ac_registry.yaml"
        feat.write_text(SAMPLE_REGISTRY)
        infra = tmp_path / "infra_registry.yaml"
        infra.write_text("version: '1.0'\ntotal: 0\nacs: []\n")
        test_dir = tmp_path / "tests"
        test_dir.mkdir()
        (test_dir / "test_x.py").write_text("# AC1.1.1 AC2.1.1\n")
        output = tmp_path / "output.md"
        return feat, infra, test_dir, output

    def test_write_mode(self, tmp_path):
        feat, infra, test_dir, output = self._build_env(tmp_path)
        args = [
            "build_ac_traceability.py",
            f"--feature-registry={feat}",
            f"--infra-registry={infra}",
            f"--test-dir={test_dir}",
            f"--output={output}",
            "--today=2024-01-01",
        ]
        with mock.patch("sys.argv", args):
            rc = bat.main()
        assert rc == 0
        assert output.exists()

    def test_check_mode_up_to_date(self, tmp_path):
        feat, infra, test_dir, output = self._build_env(tmp_path)
        args_write = [
            "build_ac_traceability.py",
            f"--feature-registry={feat}",
            f"--infra-registry={infra}",
            f"--test-dir={test_dir}",
            f"--output={output}",
            "--today=2024-01-01",
        ]
        with mock.patch("sys.argv", args_write):
            bat.main()

        args_check = args_write + ["--check"]
        with mock.patch("sys.argv", args_check):
            rc = bat.main()
        assert rc == 0

    def test_check_mode_different_date_passes(self, tmp_path):
        """--check must pass when only the date header changed (regression for stale CI)."""
        feat, infra, test_dir, output = self._build_env(tmp_path)
        args_write = [
            "build_ac_traceability.py",
            f"--feature-registry={feat}",
            f"--infra-registry={infra}",
            f"--test-dir={test_dir}",
            f"--output={output}",
            "--today=2024-01-01",
        ]
        with mock.patch("sys.argv", args_write):
            bat.main()

        # Simulate CI running on a later day with a different --today
        args_check = [
            "build_ac_traceability.py",
            f"--feature-registry={feat}",
            f"--infra-registry={infra}",
            f"--test-dir={test_dir}",
            f"--output={output}",
            "--today=2099-12-31",
            "--check",
        ]
        with mock.patch("sys.argv", args_check):
            rc = bat.main()
        assert rc == 0, "check should pass when only the date header differs"

    def test_check_mode_stale(self, tmp_path):
        feat, infra, test_dir, output = self._build_env(tmp_path)
        output.write_text("old content")
        args = [
            "build_ac_traceability.py",
            f"--feature-registry={feat}",
            f"--infra-registry={infra}",
            f"--test-dir={test_dir}",
            f"--output={output}",
            "--today=2024-01-01",
            "--check",
        ]
        with mock.patch("sys.argv", args):
            rc = bat.main()
        assert rc == 1

    def test_check_mode_missing_output(self, tmp_path):
        feat, infra, test_dir, output = self._build_env(tmp_path)
        missing = tmp_path / "nonexistent.md"
        args = [
            "build_ac_traceability.py",
            f"--feature-registry={feat}",
            f"--infra-registry={infra}",
            f"--test-dir={test_dir}",
            f"--output={missing}",
            "--today=2024-01-01",
            "--check",
        ]
        with mock.patch("sys.argv", args):
            rc = bat.main()
        assert rc == 1

    def test_default_test_dirs_used_when_no_test_dir_flag(self, tmp_path):
        feat, infra, test_dir, output = self._build_env(tmp_path)
        args = [
            "build_ac_traceability.py",
            f"--feature-registry={feat}",
            f"--infra-registry={infra}",
            f"--output={output}",
            "--today=2024-01-01",
        ]
        with mock.patch("sys.argv", args):
            rc = bat.main()
        assert rc == 0
