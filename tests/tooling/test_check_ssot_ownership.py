"""Tests for tools/check_ssot_ownership.py"""

from __future__ import annotations

import runpy
import sys
from pathlib import Path

import pytest

from common.meta.extension import (
    check_ssot_ownership,  # noqa: F401 (module reference for monkeypatch)
)
from common.meta.extension.check_ssot_ownership import (
    Violation,
    check_must_be_absent,
    check_retired_archive_roots,
    check_rule_cross_references,
    has_cross_reference,
    main,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class TestHasCrossReference:
    def test_contains_ssot_file_path(self) -> None:
        text = "See: common/reconciliation/reconciliation.md for details"
        assert (
            has_cross_reference(text, "common/reconciliation/reconciliation.md") is True
        )

    def test_contains_basename(self) -> None:
        text = "See reconciliation.md for the definition"
        assert (
            has_cross_reference(text, "common/reconciliation/reconciliation.md") is True
        )

    def test_absent_returns_false(self) -> None:
        text = "Nothing relevant here"
        assert (
            has_cross_reference(text, "common/reconciliation/reconciliation.md")
            is False
        )


# ---------------------------------------------------------------------------
# Check 1 — retired archive root files
# ---------------------------------------------------------------------------


class TestCheckRetiredArchiveRoots:
    def test_passes_when_files_absent(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "common.meta.extension.check_ssot_ownership.RETIRED_ARCHIVE_ROOT_FILES",
            [tmp_path / "should-not-exist.md"],
        )
        assert check_retired_archive_roots() == []

    def test_fails_when_file_present(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        bad = tmp_path / "AC-AUDIT-2026-02-25.md"
        bad.write_text("old content")
        monkeypatch.setattr(
            "common.meta.extension.check_ssot_ownership.REPO_ROOT", tmp_path
        )
        monkeypatch.setattr(
            "common.meta.extension.check_ssot_ownership.RETIRED_ARCHIVE_ROOT_FILES",
            [bad],
        )
        violations = check_retired_archive_roots()
        assert len(violations) == 1
        assert "must not exist" in violations[0].message
        assert "issue #548" in violations[0].message

    def test_real_archived_files_are_absent(self) -> None:
        """Retired root archive files must not exist in docs/project/ root."""
        violations = check_retired_archive_roots()
        assert violations == [], "\n".join(v.message for v in violations)


# ---------------------------------------------------------------------------
# Check 3 — must-be-absent
# ---------------------------------------------------------------------------


class TestCheckMustBeAbsent:
    def test_passes_when_files_absent(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "common.meta.extension.check_ssot_ownership.MUST_BE_ABSENT",
            [tmp_path / "deleted-file.md"],
        )
        assert check_must_be_absent() == []

    def test_fails_when_file_present(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        present = tmp_path / "EPIC-016-IMPLEMENTATION-PLAN.md"
        present.write_text("leftover")
        monkeypatch.setattr(
            "common.meta.extension.check_ssot_ownership.REPO_ROOT", tmp_path
        )
        monkeypatch.setattr(
            "common.meta.extension.check_ssot_ownership.MUST_BE_ABSENT", [present]
        )
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
    def test_passes_ssot_file_exempt(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Files inside docs/ssot/ are never flagged."""
        ssot_dir = tmp_path / "docs" / "ssot"
        ssot_dir.mkdir(parents=True)
        f = ssot_dir / "accounting.md"
        f.write_text("NEVER use FLOAT for monetary amounts.\n")

        monkeypatch.setattr(
            "common.meta.extension.check_ssot_ownership.REPO_ROOT", tmp_path
        )
        violations = check_rule_cross_references()
        assert violations == []

    def test_flags_doc_without_cross_ref(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
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

        monkeypatch.setattr(
            "common.meta.extension.check_ssot_ownership.REPO_ROOT", tmp_path
        )
        monkeypatch.setattr(
            "common.meta.extension.check_ssot_ownership.RULE_KEYWORDS",
            [
                (
                    "Decimal monetary rule",
                    _re.compile(
                        r"NEVER.*float.*monetary|FLOAT.*monetary", _re.IGNORECASE
                    ),
                    "docs/ssot/accounting.md",
                    "#decimal-rule",
                )
            ],
        )
        monkeypatch.setattr(
            "common.meta.extension.check_ssot_ownership.CHECK4_EXEMPT_PATHS", set()
        )
        violations = check_rule_cross_references()
        assert len(violations) == 1
        assert "accounting.md" in violations[0].message

    def test_passes_doc_with_cross_ref(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
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

        monkeypatch.setattr(
            "common.meta.extension.check_ssot_ownership.REPO_ROOT", tmp_path
        )
        monkeypatch.setattr(
            "common.meta.extension.check_ssot_ownership.RULE_KEYWORDS",
            [
                (
                    "Decimal monetary rule",
                    _re.compile(
                        r"NEVER.*float.*monetary|FLOAT.*monetary", _re.IGNORECASE
                    ),
                    "docs/ssot/accounting.md",
                    "#decimal-rule",
                )
            ],
        )
        monkeypatch.setattr(
            "common.meta.extension.check_ssot_ownership.CHECK4_EXEMPT_PATHS", set()
        )
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

        monkeypatch.setattr(
            "common.meta.extension.check_ssot_ownership.REPO_ROOT", tmp_path
        )
        monkeypatch.setattr(
            "common.meta.extension.check_ssot_ownership.RULE_KEYWORDS",
            [
                (
                    "Decimal monetary rule",
                    _re.compile(r"FLOAT.*monetary", _re.IGNORECASE),
                    "docs/ssot/accounting.md",
                    "#decimal-rule",
                )
            ],
        )
        monkeypatch.setattr(
            "common.meta.extension.check_ssot_ownership.CHECK4_EXEMPT_PATHS", set()
        )

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
            check_retired_archive_roots()
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
            check="check2_must_be_absent",
            message="docs/project/archive must not exist.",
        )

        monkeypatch.setattr(sys, "argv", ["check_ssot_ownership.py"])
        monkeypatch.setattr(
            "common.meta.extension.check_ssot_ownership.check_must_be_absent",
            lambda: [fake_violation],
        )
        result = main()
        captured = capsys.readouterr()
        assert result == 1
        assert "SSOT ownership lint found 1 violation" in captured.err
        assert "check2_must_be_absent" in captured.err
        assert fake_violation.message in captured.err

    def test_main_entrypoint(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """sys.exit(main()) is called when the script runs as __main__."""
        monkeypatch.setattr(sys, "argv", ["check_ssot_ownership.py"])
        with pytest.raises(SystemExit) as exc_info:
            runpy.run_path(
                str(
                    Path(__file__).resolve().parents[2]
                    / "tools"
                    / "check_ssot_ownership.py"
                ),
                run_name="__main__",
            )
        assert exc_info.value.code == 0
