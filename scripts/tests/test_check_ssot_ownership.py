"""Tests for scripts/check_ssot_ownership.py"""
from __future__ import annotations

import runpy
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import check_ssot_ownership  # noqa: F401 (module reference for monkeypatch)
from check_ssot_ownership import (
    MUST_BE_ABSENT,
    MUST_BE_ARCHIVED,
    REPO_ROOT,
    RULE_KEYWORDS,
    TRANSLATION_PAIRS,
    Violation,
    check_must_be_absent,
    check_must_be_archived,
    check_rule_cross_references,
    check_translation_parity,
    count_lines,
    has_cross_reference,
    main,
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

    def test_skips_when_file_missing(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """When one file in a pair doesn't exist the pair is silently skipped."""
        en = tmp_path / "DECISIONS.md"
        en.write_text("line1\nline2")
        zh_missing = tmp_path / "DECISIONS_ZH.md"  # NOT created
        monkeypatch.setattr(
            "check_ssot_ownership.TRANSLATION_PAIRS",
            [(zh_missing, en)],
        )
        assert check_translation_parity() == []

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

    def test_oserror_reading_file_is_skipped(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A file that raises OSError when read is silently skipped (no violation)."""
        bad_file = tmp_path / "docs" / "project" / "UNREADABLE.md"
        bad_file.parent.mkdir(parents=True)
        bad_file.write_text("trigger keyword FLOAT monetary amounts here\n")

        import re as _re

        monkeypatch.setattr("check_ssot_ownership.REPO_ROOT", tmp_path)
        monkeypatch.setattr(
            "check_ssot_ownership.RULE_KEYWORDS",
            [
                (
                    "Decimal monetary rule",
                    _re.compile(r"FLOAT.*monetary", _re.IGNORECASE),
                    "docs/ssot/accounting.md",
                    "#decimal-rule",
                )
            ],
        )
        monkeypatch.setattr("check_ssot_ownership.CHECK4_EXEMPT_PATHS", set())

        original_read_text = Path.read_text

        def _raise_if_target(self, *args, **kwargs):
            if self == bad_file:
                raise OSError("permission denied")
            return original_read_text(self, *args, **kwargs)

        monkeypatch.setattr(Path, "read_text", _raise_if_target)
        violations = check_rule_cross_references()
        assert violations == []


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


# ---------------------------------------------------------------------------
# main() function
# ---------------------------------------------------------------------------


class TestMain:
    def test_main_no_violations_quiet(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """main() with no violations and no --verbose returns 0 silently."""
        monkeypatch.setattr(sys, "argv", ["check_ssot_ownership.py"])
        assert main() == 0

    def test_main_no_violations_verbose(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ) -> None:
        """main() with --verbose prints summary and returns 0."""
        monkeypatch.setattr(sys, "argv", ["check_ssot_ownership.py", "--verbose"])
        result = main()
        captured = capsys.readouterr()
        assert result == 0
        assert "SSOT ownership lint" in captured.out
        assert "OK: SSOT ownership lint passed." in captured.out

    def test_main_with_violations_returns_1(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ) -> None:
        """main() prints grouped violations and returns 1 when checks fail."""
        fake_violation = Violation(
            check="check1_translation_parity",
            message="DECISIONS_ZH.md has 10 lines but DECISIONS.md has only 5 lines.",
        )

        monkeypatch.setattr(sys, "argv", ["check_ssot_ownership.py"])
        monkeypatch.setattr(
            "check_ssot_ownership.check_translation_parity",
            lambda: [fake_violation],
        )
        result = main()
        captured = capsys.readouterr()
        assert result == 1
        assert "SSOT ownership lint found 1 violation" in captured.err
        assert "check1_translation_parity" in captured.err
        assert fake_violation.message in captured.err

    def test_main_entrypoint(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """sys.exit(main()) is called when the script runs as __main__."""
        monkeypatch.setattr(sys, "argv", ["check_ssot_ownership.py"])
        with pytest.raises(SystemExit) as exc_info:
            runpy.run_path(
                str(Path(__file__).parent.parent / "check_ssot_ownership.py"),
                run_name="__main__",
            )
        assert exc_info.value.code == 0
