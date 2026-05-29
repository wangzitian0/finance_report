"""Tests for tools/check_manifest.py.

Covers all four checks:
  0. Per-concept schema validation (concept value must be a mapping/dict)
  1. No duplicate owners (same file#anchor)
  2. Owner files must exist on disk
  3. Cross-ref files must exist on disk

Also covers main() and helper functions.
"""

from __future__ import annotations

from pathlib import Path
from unittest import mock

import pytest

from common.ssot import check_manifest as cm


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_concepts(**kwargs: dict) -> dict:
    """Build a minimal concepts dict for testing."""
    return kwargs


# ---------------------------------------------------------------------------
# Tests: check_concept_schema
# ---------------------------------------------------------------------------


class TestCheckConceptSchema:
    def test_valid_dicts_pass(self) -> None:
        concepts = _make_concepts(
            foo={"owner": "docs/ssot/foo.md", "description": "test"},
            bar={"owner": "docs/ssot/bar.md"},
        )
        violations = cm.check_concept_schema(concepts)
        assert violations == []

    def test_null_value_fails(self) -> None:
        concepts = _make_concepts(bad_concept=None)
        violations = cm.check_concept_schema(concepts)
        assert len(violations) == 1
        assert violations[0].check == "check0_concept_schema"
        assert "bad_concept" in violations[0].message
        assert "NoneType" in violations[0].message

    def test_string_value_fails(self) -> None:
        concepts = _make_concepts(bad_concept="just a string")
        violations = cm.check_concept_schema(concepts)
        assert len(violations) == 1
        assert violations[0].check == "check0_concept_schema"
        assert "bad_concept" in violations[0].message
        assert "str" in violations[0].message

    def test_integer_value_fails(self) -> None:
        concepts = _make_concepts(bad_concept=42)
        violations = cm.check_concept_schema(concepts)
        assert len(violations) == 1
        assert violations[0].check == "check0_concept_schema"
        assert "int" in violations[0].message

    def test_mixed_valid_invalid(self) -> None:
        concepts = _make_concepts(
            good={"owner": "docs/ssot/foo.md"},
            bad=None,
        )
        violations = cm.check_concept_schema(concepts)
        assert len(violations) == 1
        assert "bad" in violations[0].message


# ---------------------------------------------------------------------------
# Tests: check_duplicate_owners
# ---------------------------------------------------------------------------


class TestCheckDuplicateOwners:
    def test_no_duplicates_passes(self) -> None:
        concepts = _make_concepts(
            foo={"owner": "docs/ssot/foo.md#section-a"},
            bar={"owner": "docs/ssot/bar.md#section-b"},
        )
        violations = cm.check_duplicate_owners(concepts)
        assert violations == []

    def test_same_file_different_anchors_passes(self) -> None:
        concepts = _make_concepts(
            foo={"owner": "docs/ssot/foo.md#section-a"},
            bar={"owner": "docs/ssot/foo.md#section-b"},
        )
        violations = cm.check_duplicate_owners(concepts)
        assert violations == []

    def test_same_owner_including_anchor_fails(self) -> None:
        concepts = _make_concepts(
            foo={"owner": "docs/ssot/foo.md#section-a"},
            bar={"owner": "docs/ssot/foo.md#section-a"},
        )
        violations = cm.check_duplicate_owners(concepts)
        assert len(violations) == 1
        assert violations[0].check == "check1_duplicate_owners"
        assert "foo" in violations[0].message
        assert "bar" in violations[0].message

    def test_same_owner_without_anchor_fails(self) -> None:
        concepts = _make_concepts(
            foo={"owner": "docs/ssot/foo.md"},
            bar={"owner": "docs/ssot/foo.md"},
        )
        violations = cm.check_duplicate_owners(concepts)
        assert len(violations) == 1
        assert violations[0].check == "check1_duplicate_owners"

    def test_missing_owner_field_skipped(self) -> None:
        concepts = _make_concepts(
            foo={"description": "no owner field"},
        )
        violations = cm.check_duplicate_owners(concepts)
        assert violations == []

    def test_non_dict_concept_skipped(self) -> None:
        """Non-dict concepts are caught by check_concept_schema; skip here."""
        concepts = _make_concepts(foo=None, bar=None)
        violations = cm.check_duplicate_owners(concepts)
        assert violations == []

    def test_three_concepts_same_owner(self) -> None:
        concepts = _make_concepts(
            a={"owner": "docs/ssot/x.md"},
            b={"owner": "docs/ssot/x.md"},
            c={"owner": "docs/ssot/x.md"},
        )
        violations = cm.check_duplicate_owners(concepts)
        assert len(violations) == 1
        assert "a" in violations[0].message
        assert "b" in violations[0].message
        assert "c" in violations[0].message


# ---------------------------------------------------------------------------
# Tests: check_owner_files_exist
# ---------------------------------------------------------------------------


class TestCheckOwnerFilesExist:
    def test_existing_file_passes(self, tmp_path: Path) -> None:
        existing = tmp_path / "docs" / "ssot" / "foo.md"
        existing.parent.mkdir(parents=True)
        existing.write_text("content")

        concepts = _make_concepts(foo={"owner": "docs/ssot/foo.md#some-anchor"})
        with mock.patch.object(cm, "REPO_ROOT", tmp_path):
            violations = cm.check_owner_files_exist(concepts)
        assert violations == []

    def test_missing_file_fails(self, tmp_path: Path) -> None:
        concepts = _make_concepts(foo={"owner": "docs/ssot/missing.md"})
        with mock.patch.object(cm, "REPO_ROOT", tmp_path):
            violations = cm.check_owner_files_exist(concepts)
        assert len(violations) == 1
        assert violations[0].check == "check2_owner_exists"
        assert "foo" in violations[0].message
        assert "missing.md" in violations[0].message

    def test_missing_owner_field_reported(self, tmp_path: Path) -> None:
        concepts = _make_concepts(foo={"description": "no owner"})
        with mock.patch.object(cm, "REPO_ROOT", tmp_path):
            violations = cm.check_owner_files_exist(concepts)
        assert len(violations) == 1
        assert violations[0].check == "check2_owner_exists"
        assert "no 'owner'" in violations[0].message

    def test_anchor_stripped_correctly(self, tmp_path: Path) -> None:
        existing = tmp_path / "docs" / "ssot" / "foo.md"
        existing.parent.mkdir(parents=True)
        existing.write_text("content")

        # Should resolve docs/ssot/foo.md (ignoring #anchor)
        concepts = _make_concepts(foo={"owner": "docs/ssot/foo.md#anchor-here"})
        with mock.patch.object(cm, "REPO_ROOT", tmp_path):
            violations = cm.check_owner_files_exist(concepts)
        assert violations == []

    def test_non_dict_concept_skipped(self, tmp_path: Path) -> None:
        """Non-dict concepts are caught by check_concept_schema; skip here."""
        concepts = _make_concepts(foo=None)
        with mock.patch.object(cm, "REPO_ROOT", tmp_path):
            violations = cm.check_owner_files_exist(concepts)
        assert violations == []


# ---------------------------------------------------------------------------
# Tests: check_crossref_files_exist
# ---------------------------------------------------------------------------


class TestCheckCrossrefFilesExist:
    def test_existing_crossref_passes(self, tmp_path: Path) -> None:
        ref_file = tmp_path / "AGENTS.md"
        ref_file.write_text("content")

        concepts = _make_concepts(
            foo={"owner": "docs/ssot/foo.md", "cross_refs": ["AGENTS.md"]}
        )
        with mock.patch.object(cm, "REPO_ROOT", tmp_path):
            violations = cm.check_crossref_files_exist(concepts)
        assert violations == []

    def test_missing_crossref_fails(self, tmp_path: Path) -> None:
        concepts = _make_concepts(
            foo={
                "owner": "docs/ssot/foo.md",
                "cross_refs": ["docs/missing.md"],
            }
        )
        with mock.patch.object(cm, "REPO_ROOT", tmp_path):
            violations = cm.check_crossref_files_exist(concepts)
        assert len(violations) == 1
        assert violations[0].check == "check3_crossref_exists"
        assert "foo" in violations[0].message
        assert "missing.md" in violations[0].message

    def test_no_crossrefs_passes(self) -> None:
        concepts = _make_concepts(foo={"owner": "docs/ssot/foo.md"})
        violations = cm.check_crossref_files_exist(concepts)
        assert violations == []

    def test_empty_crossrefs_passes(self) -> None:
        concepts = _make_concepts(foo={"owner": "docs/ssot/foo.md", "cross_refs": []})
        violations = cm.check_crossref_files_exist(concepts)
        assert violations == []

    def test_anchor_in_crossref_stripped(self, tmp_path: Path) -> None:
        ref_file = tmp_path / "docs" / "ssot" / "bar.md"
        ref_file.parent.mkdir(parents=True)
        ref_file.write_text("content")

        concepts = _make_concepts(
            foo={
                "owner": "docs/ssot/foo.md",
                "cross_refs": ["docs/ssot/bar.md#some-section"],
            }
        )
        with mock.patch.object(cm, "REPO_ROOT", tmp_path):
            violations = cm.check_crossref_files_exist(concepts)
        assert violations == []

    def test_crossrefs_as_string_fails(self) -> None:
        """cross_refs must be a list; a scalar string is a schema error."""
        concepts = _make_concepts(
            foo={
                "owner": "docs/ssot/foo.md",
                "cross_refs": "AGENTS.md",
            }
        )
        violations = cm.check_crossref_files_exist(concepts)
        assert len(violations) == 1
        assert violations[0].check == "check3_crossref_exists"
        assert "str" in violations[0].message
        assert "foo" in violations[0].message

    def test_crossrefs_entry_not_a_string_fails(self, tmp_path: Path) -> None:
        """Items in cross_refs must be strings."""
        concepts = _make_concepts(
            foo={
                "owner": "docs/ssot/foo.md",
                "cross_refs": [42],
            }
        )
        with mock.patch.object(cm, "REPO_ROOT", tmp_path):
            violations = cm.check_crossref_files_exist(concepts)
        assert len(violations) == 1
        assert violations[0].check == "check3_crossref_exists"
        assert "int" in violations[0].message

    def test_non_dict_concept_skipped(self) -> None:
        """Non-dict concepts are caught by check_concept_schema; skip here."""
        concepts = _make_concepts(foo=None)
        violations = cm.check_crossref_files_exist(concepts)
        assert violations == []


# ---------------------------------------------------------------------------
# Tests: _file_part helper
# ---------------------------------------------------------------------------


class TestFilePart:
    def test_no_anchor(self) -> None:
        assert cm._file_part("docs/ssot/foo.md") == "docs/ssot/foo.md"

    def test_with_anchor(self) -> None:
        assert cm._file_part("docs/ssot/foo.md#section") == "docs/ssot/foo.md"

    def test_multiple_hashes(self) -> None:
        assert cm._file_part("path/file.md#a#b") == "path/file.md"


# ---------------------------------------------------------------------------
# Tests: main()
# ---------------------------------------------------------------------------


class TestMain:
    def test_manifest_not_found_exits_1(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with (
            mock.patch("sys.argv", ["check_manifest.py"]),
            mock.patch.object(cm, "MANIFEST_PATH", tmp_path / "missing.yaml"),
        ):
            with pytest.raises(SystemExit) as exc_info:
                cm.main()
        assert exc_info.value.code == 1

    def test_empty_concepts_exits_1(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        manifest = tmp_path / "MANIFEST.yaml"
        manifest.write_text("concepts: {}\n")
        with (
            mock.patch("sys.argv", ["check_manifest.py"]),
            mock.patch.object(cm, "MANIFEST_PATH", manifest),
        ):
            result = cm.main()
        assert result == 1

    def test_valid_manifest_passes(self, tmp_path: Path) -> None:
        # Create a real file to satisfy existence checks
        ssot_dir = tmp_path / "docs" / "ssot"
        ssot_dir.mkdir(parents=True)
        (ssot_dir / "foo.md").write_text("content")
        (ssot_dir / "bar.md").write_text("content")

        manifest = tmp_path / "MANIFEST.yaml"
        manifest.write_text(
            "concepts:\n"
            "  concept_a:\n"
            "    owner: docs/ssot/foo.md#section-a\n"
            "    description: test\n"
            "  concept_b:\n"
            "    owner: docs/ssot/bar.md#section-b\n"
            "    description: test\n"
            "    cross_refs:\n"
            "      - docs/ssot/foo.md\n"
        )
        with (
            mock.patch("sys.argv", ["check_manifest.py"]),
            mock.patch.object(cm, "MANIFEST_PATH", manifest),
            mock.patch.object(cm, "REPO_ROOT", tmp_path),
        ):
            result = cm.main()
        assert result == 0

    def test_manifest_violation_exits_1(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        manifest = tmp_path / "MANIFEST.yaml"
        manifest.write_text(
            "concepts:\n"
            "  concept_a:\n"
            "    owner: docs/ssot/foo.md\n"
            "  concept_b:\n"
            "    owner: docs/ssot/foo.md\n"
        )
        with (
            mock.patch("sys.argv", ["check_manifest.py"]),
            mock.patch.object(cm, "MANIFEST_PATH", manifest),
            mock.patch.object(cm, "REPO_ROOT", tmp_path),
        ):
            result = cm.main()
        assert result == 1

    def test_actual_manifest_passes(self) -> None:
        """Smoke test: the real MANIFEST.yaml in the repo must pass."""
        with mock.patch("sys.argv", ["check_manifest.py"]):
            result = cm.main()
        assert result == 0

    def test_null_concept_value_fails(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """A concept mapped to null must trigger check0_concept_schema."""
        manifest = tmp_path / "MANIFEST.yaml"
        manifest.write_text("concepts:\n  bad_concept:\n")
        with (
            mock.patch("sys.argv", ["check_manifest.py"]),
            mock.patch.object(cm, "MANIFEST_PATH", manifest),
            mock.patch.object(cm, "REPO_ROOT", tmp_path),
        ):
            result = cm.main()
        assert result == 1
        captured = capsys.readouterr()
        assert "check0_concept_schema" in captured.err
        assert "bad_concept" in captured.err

    def test_string_crossrefs_fails(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """cross_refs as a scalar string must fail with a clear message."""
        ssot_dir = tmp_path / "docs" / "ssot"
        ssot_dir.mkdir(parents=True)
        (ssot_dir / "foo.md").write_text("content")

        manifest = tmp_path / "MANIFEST.yaml"
        manifest.write_text(
            "concepts:\n"
            "  my_concept:\n"
            "    owner: docs/ssot/foo.md\n"
            "    cross_refs: AGENTS.md\n"
        )
        with (
            mock.patch("sys.argv", ["check_manifest.py"]),
            mock.patch.object(cm, "MANIFEST_PATH", manifest),
            mock.patch.object(cm, "REPO_ROOT", tmp_path),
        ):
            result = cm.main()
        assert result == 1
        captured = capsys.readouterr()
        assert "check3_crossref_exists" in captured.err
