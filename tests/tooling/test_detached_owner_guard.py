"""Contracts for production-faithful backend persistence proof debt burn-down."""

from __future__ import annotations

from pathlib import Path

from common.testing import detached_owner_guard

ROOT = Path(__file__).resolve().parents[2]


def test_AC8_13_128_detects_direct_detached_owner_uuid4_shortcuts(tmp_path: Path) -> None:
    """AC8.13.128: direct DB-backed user_id=uuid4() owner shortcuts are counted."""
    test_file = tmp_path / "apps" / "backend" / "tests" / "accounting" / "test_shortcut.py"
    test_file.parent.mkdir(parents=True)
    test_file.write_text(
        """
from uuid import uuid4

from src.models import Account, User


def test_shortcut():
    User(id=uuid4(), email="ok@example.com", hashed_password="x")
    Account(user_id=uuid4(), name="Detached", type="ASSET", currency="SGD")
""".lstrip(),
        encoding="utf-8",
    )

    findings = detached_owner_guard.scan_paths(
        [tmp_path / "apps" / "backend" / "tests"],
        repo_root=tmp_path,
    )

    assert [finding.relative_path for finding in findings] == ["apps/backend/tests/accounting/test_shortcut.py"]
    assert findings[0].line == 8
    assert findings[0].pattern == "user_id=uuid4()"


def test_AC8_13_128_detects_attribute_uuid4_and_scans_single_files(tmp_path: Path) -> None:
    """AC8.13.128: scanner handles pathlib file inputs and uuid.uuid4 calls."""
    test_file = tmp_path / "shortcut.py"
    test_file.write_text(
        """
import uuid

from src.models import Account


def test_shortcut():
    Account(user_id=uuid.uuid4(), name="Detached", type="ASSET", currency="SGD")
""".lstrip(),
        encoding="utf-8",
    )

    findings = detached_owner_guard.scan_paths([test_file], repo_root=tmp_path)

    assert len(findings) == 1
    assert findings[0].relative_path == "shortcut.py"
    assert findings[0].source.startswith("Account(user_id=uuid.uuid4()")


def test_AC8_13_128_ignores_non_uuid4_user_ids(tmp_path: Path) -> None:
    """AC8.13.128: only direct uuid4 owner shortcuts count against the budget."""
    test_file = tmp_path / "apps" / "backend" / "tests" / "test_safe.py"
    test_file.parent.mkdir(parents=True)
    test_file.write_text(
        """
from uuid import uuid4

from src.models import Account


def test_safe(user):
    owner_id = uuid4()
    Account(user_id=user.id, name="Real user", type="ASSET", currency="SGD")
    Account(user_id=owner_id, name="Assigned first", type="ASSET", currency="SGD")
""".lstrip(),
        encoding="utf-8",
    )

    assert detached_owner_guard.scan_paths([test_file], repo_root=Path("/outside/root")) == []


def test_AC8_13_128_budget_fails_on_growth() -> None:
    """AC8.13.128: detached-owner shortcut growth fails closed."""
    finding = detached_owner_guard.DetachedOwnerFinding(
        relative_path="apps/backend/tests/accounting/test_shortcut.py",
        line=1,
        pattern="user_id=uuid4()",
        source="Account(user_id=uuid4())",
    )

    result = detached_owner_guard.evaluate_budget([finding], max_allowed=0)

    assert result.ok is False
    assert result.count == 1
    assert "exceeds allowed budget 0" in result.message


def test_AC8_13_128_formats_findings_with_limit() -> None:
    """AC8.13.128: failure output is bounded when the shortcut list is long."""
    findings = [
        detached_owner_guard.DetachedOwnerFinding(
            relative_path=f"apps/backend/tests/test_{index}.py",
            line=index + 1,
            pattern="user_id=uuid4()",
            source="Account(user_id=uuid4())",
        )
        for index in range(3)
    ]

    output = detached_owner_guard._format_findings(findings, limit=2)

    assert "apps/backend/tests/test_0.py:1: user_id=uuid4()" in output
    assert "apps/backend/tests/test_1.py:2: user_id=uuid4()" in output
    assert "... 1 more" in output
    assert "test_2.py" not in output


def test_AC8_13_128_cli_lists_findings_and_exits_zero(tmp_path: Path, capsys) -> None:
    """AC8.13.128: CLI can list current findings while staying under budget."""
    test_file = tmp_path / "apps" / "backend" / "tests" / "test_shortcut.py"
    test_file.parent.mkdir(parents=True)
    test_file.write_text(
        """
from uuid import uuid4

from src.models import Account


def test_shortcut():
    Account(user_id=uuid4(), name="Detached", type="ASSET", currency="SGD")
""".lstrip(),
        encoding="utf-8",
    )

    exit_code = detached_owner_guard.main(
        [
            "--repo-root",
            str(tmp_path),
            "--path",
            Path("apps/backend/tests").as_posix(),
            "--max-allowed",
            "1",
            "--list-findings",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "within allowed budget 1" in captured.out
    assert "apps/backend/tests/test_shortcut.py" in captured.out
    assert captured.err == ""


def test_AC8_13_128_cli_fails_on_budget_growth(tmp_path: Path, capsys) -> None:
    """AC8.13.128: CLI returns nonzero and prints findings on budget growth."""
    test_file = tmp_path / "apps" / "backend" / "tests" / "test_shortcut.py"
    test_file.parent.mkdir(parents=True)
    test_file.write_text(
        """
from uuid import uuid4

from src.models import Account


def test_shortcut():
    Account(user_id=uuid4(), name="Detached", type="ASSET", currency="SGD")
""".lstrip(),
        encoding="utf-8",
    )

    exit_code = detached_owner_guard.main(
        [
            "--repo-root",
            str(tmp_path),
            "--path",
            Path("apps/backend/tests").as_posix(),
            "--max-allowed",
            "0",
            "--show-limit",
            "1",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 1
    assert captured.out == ""
    assert "exceeds allowed budget 0" in captured.err
    assert "apps/backend/tests/test_shortcut.py" in captured.err


def test_AC8_13_128_current_repo_shortcuts_do_not_exceed_budget() -> None:
    """AC8.13.128: the current detached-owner count is a non-growth ceiling."""
    findings = detached_owner_guard.scan_default_paths(ROOT)
    result = detached_owner_guard.evaluate_budget(findings)

    assert result.ok, result.message


def test_AC8_13_128_ci_and_local_lint_run_detached_owner_guard() -> None:
    """AC8.13.128: CI and local lint both run the detached-owner growth guard."""
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    lint_block = workflow.split("  lint:", 1)[1].split("  schema-migrations:", 1)[0]
    local_lint = (ROOT / "tools" / "_lib" / "dev" / "cli.py").read_text(encoding="utf-8")

    assert "tools/check_detached_owner_shortcuts.py" in lint_block
    assert "tools/check_detached_owner_shortcuts.py" in local_lint


def test_AC8_13_128_command_entrypoint_delegates_to_common_guard() -> None:
    """AC8.13.128: command wrapper delegates to the common guard implementation."""
    from tools import check_detached_owner_shortcuts

    assert check_detached_owner_shortcuts.main is detached_owner_guard.main


def test_AC8_13_129_schema_docs_distinguish_fast_fixture_and_production_faithful_lane() -> None:
    """AC8.13.129: schema SSOT names each backend persistence proof mode."""
    schema_doc = (ROOT / "docs" / "ssot" / "schema.md").read_text(encoding="utf-8")

    assert "Base.metadata.create_all()" in schema_doc
    assert "fast fixture schema" in schema_doc
    assert "production-faithful backend business persistence" in schema_doc
    assert "detached-owner" in schema_doc
