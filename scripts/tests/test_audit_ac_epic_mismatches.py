from __future__ import annotations

import sys
from pathlib import Path
from unittest import mock

import yaml

sys.path.insert(0, str(Path(__file__).parent.parent))

import audit_ac_epic_mismatches as aam


SAMPLE_REGISTRY_YAML = yaml.dump(
    {
        "version": "1.0",
        "groups": {
            "AC1": {
                "AC1.1": [
                    {
                        "id": "AC1.1.1",
                        "epic": 1,
                        "epic_name": "phase0-setup",
                        "description": "d1",
                        "mandatory": True,
                    },
                    {
                        "id": "AC1.1.2",
                        "epic": 1,
                        "epic_name": "phase0-setup",
                        "description": "d2",
                        "mandatory": False,
                    },
                ],
            },
            "AC2": {
                "AC2.1": [
                    {
                        "id": "AC2.1.1",
                        "epic": 2,
                        "epic_name": "double-entry",
                        "description": "d3",
                        "mandatory": True,
                    },
                ],
            },
        },
    }
)
INFRA_REGISTRY_YAML = yaml.dump(
    {
        "version": "1.0",
        "groups": {
            "AC3": {
                "AC3.1": [
                    {
                        "id": "AC3.1.1",
                        "epic": 3,
                        "epic_name": "infra",
                        "description": "d4",
                        "mandatory": True,
                    },
                ],
            },
        },
    }
)


class TestIsTestFile:
    def test_test_prefix_py(self):
        assert aam.is_test_file(Path("test_accounting.py"))

    def test_test_suffix_py(self):
        assert aam.is_test_file(Path("accounting_test.py"))

    def test_test_ts(self):
        assert aam.is_test_file(Path("accounting.test.ts"))

    def test_test_tsx(self):
        assert aam.is_test_file(Path("reconciliation.test.tsx"))

    def test_spec_ts(self):
        assert aam.is_test_file(Path("api.spec.ts"))

    def test_spec_tsx(self):
        assert aam.is_test_file(Path("button.spec.tsx"))

    def test_non_test_file(self):
        assert not aam.is_test_file(Path("models.py"))

    def test_plain_ts_non_test(self):
        assert not aam.is_test_file(Path("utils.ts"))

    def test_accounting_utils_non_test(self):
        assert not aam.is_test_file(Path("accounting_utils.py"))


class TestLoadRegistry:
    def _make_docs(self, tmp_path):
        docs = tmp_path / "docs"
        docs.mkdir()
        (docs / "ac_registry.yaml").write_text(SAMPLE_REGISTRY_YAML)
        (docs / "infra_registry.yaml").write_text(INFRA_REGISTRY_YAML)
        return docs

    def test_returns_dict_by_epic(self, tmp_path):
        self._make_docs(tmp_path)
        with mock.patch.object(aam, "ROOT", tmp_path):
            valid = aam.load_registry()
        assert isinstance(valid, dict)
        assert 1 in valid

    def test_feature_ac_indexed(self, tmp_path):
        self._make_docs(tmp_path)
        with mock.patch.object(aam, "ROOT", tmp_path):
            valid = aam.load_registry()
        assert "AC1.1.1" in valid[1]
        assert "AC1.1.2" in valid[1]

    def test_infra_ac_indexed(self, tmp_path):
        self._make_docs(tmp_path)
        with mock.patch.object(aam, "ROOT", tmp_path):
            valid = aam.load_registry()
        assert "AC3.1.1" in valid[3]

    def test_multiple_epics(self, tmp_path):
        self._make_docs(tmp_path)
        with mock.patch.object(aam, "ROOT", tmp_path):
            valid = aam.load_registry()
        assert 2 in valid

    def test_empty_registry_no_crash(self, tmp_path):
        docs = tmp_path / "docs"
        docs.mkdir()
        for fname in ("ac_registry.yaml", "infra_registry.yaml"):
            (docs / fname).write_text("version: '1.0'\ngroups: {}\n")
        with mock.patch.object(aam, "ROOT", tmp_path):
            valid = aam.load_registry()
        assert valid == {}


class TestWalkTests:
    def _make_test_tree(self, tmp_path):
        tests = tmp_path / "apps" / "backend" / "tests"
        tests.mkdir(parents=True)
        (tests / "test_good.py").write_text("# AC1.1.1\n")
        excl = tests / "node_modules"
        excl.mkdir()
        (excl / "test_bad.py").write_text("# AC1.1.1\n")
        return tests

    def test_finds_test_files(self, tmp_path):
        self._make_test_tree(tmp_path)
        with mock.patch.object(aam, "ROOT", tmp_path):
            files = aam.walk_tests()
        assert any(f.name == "test_good.py" for f in files)

    def test_excludes_node_modules(self, tmp_path):
        self._make_test_tree(tmp_path)
        with mock.patch.object(aam, "ROOT", tmp_path):
            files = aam.walk_tests()
        assert not any("node_modules" in f.parts for f in files)

    def test_excludes_ac_stubs(self, tmp_path):
        stubs = tmp_path / "apps" / "backend" / "tests" / "_ac_stubs"
        stubs.mkdir(parents=True)
        (stubs / "test_stub.py").write_text("")
        with mock.patch.object(aam, "ROOT", tmp_path):
            files = aam.walk_tests()
        assert not any("_ac_stubs" in str(f) for f in files)

    def test_excludes_non_test_files(self, tmp_path):
        d = tmp_path / "apps" / "backend" / "src"
        d.mkdir(parents=True)
        (d / "models.py").write_text("")
        with mock.patch.object(aam, "ROOT", tmp_path):
            files = aam.walk_tests()
        assert not any(f.name == "models.py" for f in files)


class TestFixtureClassification:
    def test_scripts_tests_file_is_fixture_file(self, tmp_path):
        scripts_tests = tmp_path / "scripts" / "tests"
        scripts_tests.mkdir(parents=True)
        fixture = scripts_tests / "test_fake_ac_fixture.py"
        fixture.write_text("# AC99.1.1\n")
        with mock.patch.object(aam, "ROOT", tmp_path):
            assert aam.is_fixture_test_file(fixture)

    def test_product_test_file_is_not_fixture_file(self, tmp_path):
        product_tests = tmp_path / "apps" / "backend" / "tests"
        product_tests.mkdir(parents=True)
        test_file = product_tests / "test_real_behavior.py"
        test_file.write_text("# AC1.1.1\n")
        with mock.patch.object(aam, "ROOT", tmp_path):
            assert not aam.is_fixture_test_file(test_file)

    def test_path_outside_root_is_not_fixture_file(self, tmp_path):
        outside = tmp_path.parent / "test_outside.py"
        with mock.patch.object(aam, "ROOT", tmp_path):
            assert not aam.is_fixture_test_file(outside)


class TestMain:
    def _setup(self, tmp_path):
        docs = tmp_path / "docs"
        docs.mkdir()
        (docs / "ac_registry.yaml").write_text(SAMPLE_REGISTRY_YAML)
        (docs / "infra_registry.yaml").write_text(INFRA_REGISTRY_YAML)
        tests = tmp_path / "tests"
        tests.mkdir()
        return tests

    def test_clean_run_no_mismatches(self, tmp_path, capsys):
        tests = self._setup(tmp_path)
        (tests / "test_x.py").write_text("# AC1.1.1 AC2.1.1\n")
        with mock.patch.object(aam, "ROOT", tmp_path):
            aam.main()
        out = capsys.readouterr().out
        assert "Actionable mismatched refs: **0**" in out
        assert "Fixture-only mismatched refs: **0**" in out

    def test_bad_ref_detected(self, tmp_path, capsys):
        tests = self._setup(tmp_path)
        (tests / "test_x.py").write_text("# AC9.9.9\n")
        with mock.patch.object(aam, "ROOT", tmp_path):
            aam.main()
        out = capsys.readouterr().out
        assert "Actionable mismatched refs: **1**" in out
        assert "Fixture-only mismatched refs: **0**" in out
        assert "## Actionable Mismatches" in out

    def test_fixture_exclude_label_for_scripts_tests(self, tmp_path, capsys):
        """AC8.13.35: Synthetic script-test fixture IDs are not actionable mismatches."""
        self._setup(tmp_path)
        scripts_tests = tmp_path / "scripts" / "tests"
        scripts_tests.mkdir(parents=True)
        (scripts_tests / "test_x.py").write_text("# AC9.9.9\n")
        with mock.patch.object(aam, "ROOT", tmp_path):
            aam.main()
        out = capsys.readouterr().out
        assert "Actionable mismatched refs: **0**" in out
        assert "Fixture-only mismatched refs: **1**" in out
        assert "FIXTURE-EXCLUDE" in out

    def test_relocate_suggestion_when_alt_epic_matches(self, tmp_path, capsys):
        docs = tmp_path / "docs"
        docs.mkdir()
        registry = yaml.dump(
            {
                "version": "1.0",
                "total": 2,
                "acs": [
                    {"id": "AC1.1.1", "epic": 1, "description": "d", "mandatory": True},
                    {"id": "AC2.1.1", "epic": 2, "description": "d", "mandatory": True},
                ],
            }
        )
        (docs / "ac_registry.yaml").write_text(registry)
        (docs / "infra_registry.yaml").write_text("version: '1.0'\ngroups: {}\n")
        tests = tmp_path / "tests"
        tests.mkdir()
        (tests / "test_x.py").write_text("AC2.1.1 AC2.1.2\n")
        with mock.patch.object(aam, "ROOT", tmp_path):
            aam.main()
        out = capsys.readouterr().out
        assert "RELOCATE-FILE" in out or "EXTEND-REGISTRY" in out or "MIXED" in out

    def test_mixed_actionable_suggestion_for_multiple_ref_epics(self, tmp_path, capsys):
        tests = self._setup(tmp_path)
        (tests / "test_x.py").write_text("# AC8.9.9 AC9.9.9\n")
        with mock.patch.object(aam, "ROOT", tmp_path):
            aam.main()
        out = capsys.readouterr().out
        assert "Actionable mismatched refs: **2**" in out
        assert "MIXED - per-ref decision" in out

    def test_total_refs_counted(self, tmp_path, capsys):
        tests = self._setup(tmp_path)
        (tests / "test_x.py").write_text("AC1.1.1 AC1.1.2 AC2.1.1\n")
        with mock.patch.object(aam, "ROOT", tmp_path):
            aam.main()
        out = capsys.readouterr().out
        assert "Total ACx.y.z refs scanned: **3**" in out

    def test_unreadable_file_skipped(self, tmp_path, capsys):
        tests = self._setup(tmp_path)
        f = tests / "test_x.py"
        f.write_text("AC1.1.1\n")
        preset_registry = {
            1: {"AC1.1.1": {"epic": 1, "description": "d", "mandatory": True}}
        }
        with mock.patch.object(aam, "ROOT", tmp_path):
            with mock.patch.object(aam, "load_registry", return_value=preset_registry):
                with mock.patch.object(
                    Path, "read_text", side_effect=OSError("no access")
                ):
                    aam.main()
        out = capsys.readouterr().out
        assert "Total ACx.y.z refs scanned: **0**" in out
