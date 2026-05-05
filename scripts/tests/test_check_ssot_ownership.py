"""Tests for scripts/check_ssot_ownership.py"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from check_ssot_ownership import (
    MUST_BE_ABSENT,
    MUST_BE_ARCHIVED,
    REPO_ROOT,
    RULE_KEYWORDS,
    TRANSLATION_PAIRS,
    check_must_be_absent,
    check_must_be_archived,
    check_rule_cross_references,
    check_translation_parity,
    count_lines,
    has_cross_reference,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class TestCountLines:
    def test_empty_file(self, tmp_path: Path) -> None:
        f = tmp_path / "empty.md"
        f.write_text("")
        assert count_lines(f) == 0

    def test_single_line(self, tmp_path: Path) -> None:
        f = tmp_path / "one.md"
        f.write_text("hello")
        assert count_lines(f) == 1

    def test_multi_line(self, tmp_path: Path) -> None:
        f = tmp_path / "multi.md"
        f.write_text("a\nb\nc")
        assert count_lines(f) == 3

    def test_missing_file_returns_zero(self, tmp_path: Path) -> None:
        missing = tmp_path / "nonexistent.md"
        assert count_lines(missing) == 0


class TestHasCrossReference:
    def test_contains_ssot_file_path(self) -> None:
        text = "See: docs/ssot/reconciliation.md for details"
        assert has_cross_reference(text, "docs/ssot/reconciliation.md") is True

    def test_contains_basename(self) -> None:
        text = "See reconciliation.md for the definition"
        assert has_cross_reference(text, "docs/ssot/reconciliation.md") is True

    def test_absent_returns_false(self) -> None:
        text = "Nothing relevant here"
        assert has_cross_reference(text, "docs/ssot/reconciliation.md") is False


# ---------------------------------------------------------------------------
# Check 1 — translation parity
# ---------------------------------------------------------------------------


class TestCheckTranslationParity:
    def test_passes_when_zh_le_en(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        en = tmp_path / "DECISIONS.md"
        zh = tmp_path / "DECISIONS_ZH.md"
        en.write_text("line1\nline2\nline3")
        zh.write_text("行1\n行2")

        monkeypatch.setattr(
            "check_ssot_ownership.TRANSLATION_PAIRS",
            [(zh, en)],
        )
        violations = check_translation_parity()
        assert violations == []

    def test_fails_when_zh_gt_en(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        en = tmp_path / "DECISIONS.md"
        zh = tmp_path / "DECISIONS_ZH.md"
        en.write_text("line1\nline2")
        zh.write_text("行1\n行2\n行3\n行4")

        monkeypatch.setattr("check_ssot_ownership.REPO_ROOT", tmp_path)
        monkeypatch.setattr(
            "check_ssot_ownership.TRANSLATION_PAIRS",
            [(zh, en)],
        )
        violations = check_translation_parity()
        assert len(violations) == 1
        assert "ZH translation must not exceed EN source" in violations[0].message

    def test_real_decisions_files_pass(self) -> None:
        """Actual DECISIONS.md / DECISIONS_ZH.md must satisfy ZH ≤ EN."""
        violations = check_translation_parity()
        assert violations == [], "\n".join(v.message for v in violations)


# ---------------------------------------------------------------------------
# Check 2 — must-be-archived
# ---------------------------------------------------------------------------


class TestCheckMustBeArchived:
    def test_passes_when_files_absent(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "check_ssot_ownership.MUST_BE_ARCHIVED",
            [tmp_path / "should-not-exist.md"],
        )
        assert check_must_be_archived() == []

    def test_fails_when_file_present(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        bad = tmp_path / "AC-AUDIT-2026-02-25.md"
        bad.write_text("old content")
        monkeypatch.setattr("check_ssot_ownership.REPO_ROOT", tmp_path)
        monkeypatch.setattr("check_ssot_ownership.MUST_BE_ARCHIVED", [bad])
        violations = check_must_be_archived()
        assert len(violations) == 1
        assert "must be moved to" in violations[0].message

    def test_real_archived_files_are_absent(self) -> None:
        """Files that must be archived must not exist in docs/project/ root."""
        violations = check_must_be_archived()
        assert violations == [], "\n".join(v.message for v in violations)


# ---------------------------------------------------------------------------
# Check 3 — must-be-absent
# ---------------------------------------------------------------------------


class TestCheckMustBeAbsent:
    def test_passes_when_files_absent(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "check_ssot_ownership.MUST_BE_ABSENT",
            [tmp_path / "deleted-file.md"],
        )
        assert check_must_be_absent() == []

    def test_fails_when_file_present(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        present = tmp_path / "EPIC-016-IMPLEMENTATION-PLAN.md"
        present.write_text("leftover")
        monkeypatch.setattr("check_ssot_ownership.REPO_ROOT", tmp_path)
        monkeypatch.setattr("check_ssot_ownership.MUST_BE_ABSENT", [present])
        violations = check_must_be_absent()
        assert len(violations) == 1
        assert "must not exist" in violations[0].message

    def test_real_absent_files_are_gone(self) -> None:
        """Merged/renamed files must not exist at old paths."""
        violations = check_must_be_absent()
        assert violations == [], "\n".join(v.message for v in violations)


# ---------------------------------------------------------------------------
# Check 4 — rule cross-references
# ---------------------------------------------------------------------------


class TestCheckRuleCrossReferences:
    def test_passes_ssot_file_exempt(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Files inside docs/ssot/ are never flagged."""
        ssot_dir = tmp_path / "docs" / "ssot"
        ssot_dir.mkdir(parents=True)
        f = ssot_dir / "accounting.md"
        f.write_text("NEVER use FLOAT for monetary amounts.\n")

        monkeypatch.setattr("check_ssot_ownership.REPO_ROOT", tmp_path)
        violations = check_rule_cross_references()
        assert violations == []

    def test_flags_doc_without_cross_ref(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Markdown docs outside ssot/ that mention a rule must have a cross-reference."""
        ssot_dir = tmp_path / "docs" / "ssot"
        ssot_dir.mkdir(parents=True)
        # Create a canonical owner file
        (ssot_dir / "accounting.md").write_text("canonical\n")

        project_dir = tmp_path / "docs" / "project"
        project_dir.mkdir(parents=True)
        epic = project_dir / "EPIC-099.test.md"
        # Mention a rule keyword without a cross-reference
        epic.write_text("NEVER use FLOAT for monetary amounts in our system.\n")

        import re as _re

        monkeypatch.setattr("check_ssot_ownership.REPO_ROOT", tmp_path)
        monkeypatch.setattr(
            "check_ssot_ownership.RULE_KEYWORDS",
            [
                (
                    "Decimal monetary rule",
                    _re.compile(r"NEVER.*float.*monetary|FLOAT.*monetary", _re.IGNORECASE),
                    "docs/ssot/accounting.md",
                    "#decimal-rule",
                )
            ],
        )
        monkeypatch.setattr("check_ssot_ownership.CHECK4_EXEMPT_PATHS", set())
        violations = check_rule_cross_references()
        assert len(violations) == 1
        assert "accounting.md" in violations[0].message

    def test_passes_doc_with_cross_ref(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Markdown docs with a cross-reference are not flagged."""
        ssot_dir = tmp_path / "docs" / "ssot"
        ssot_dir.mkdir(parents=True)
        (ssot_dir / "accounting.md").write_text("canonical\n")

        project_dir = tmp_path / "docs" / "project"
        project_dir.mkdir(parents=True)
        epic = project_dir / "EPIC-099.test.md"
        # Mention the rule AND include a cross-reference
        epic.write_text(
            "NEVER use FLOAT for monetary amounts.\n"
            "See: docs/ssot/accounting.md#decimal-rule for details.\n"
        )

        import re as _re

        monkeypatch.setattr("check_ssot_ownership.REPO_ROOT", tmp_path)
        monkeypatch.setattr(
            "check_ssot_ownership.RULE_KEYWORDS",
            [
                (
                    "Decimal monetary rule",
                    _re.compile(r"NEVER.*float.*monetary|FLOAT.*monetary", _re.IGNORECASE),
                    "docs/ssot/accounting.md",
                    "#decimal-rule",
                )
            ],
        )
        monkeypatch.setattr("check_ssot_ownership.CHECK4_EXEMPT_PATHS", set())
        violations = check_rule_cross_references()
        assert violations == []

    def test_real_repo_passes(self) -> None:
        """The actual repository must pass all cross-reference checks."""
        violations = check_rule_cross_references()
        assert violations == [], "\n".join(v.message for v in violations)


# ---------------------------------------------------------------------------
# Integration — full run on real repo
# ---------------------------------------------------------------------------


class TestFullRunOnRealRepo:
    def test_all_checks_pass(self) -> None:
        """All checks must pass on the real repository."""
        violations = (
            check_translation_parity()
            + check_must_be_archived()
            + check_must_be_absent()
            + check_rule_cross_references()
        )
        assert violations == [], "\n".join(v.message for v in violations)
