"""Public ORM export ratchet for #1894."""

from __future__ import annotations

import json
from pathlib import Path

from common.meta.extension.check_public_orm_exports import main, violations
from common.meta.extension.public_orm_exports import discover_public_orm_exports


def test_AC_meta_dependency_governance_5_public_orm_exports_are_exact(
    tmp_path: Path,
) -> None:
    """AC-meta.dependency-governance.5: root ORM exports are exact debt."""
    src = tmp_path / "apps/backend/src/ledger"
    src.mkdir(parents=True)
    (src / "__init__.py").write_text(
        "from src.ledger.orm.entry import JournalEntry\n__all__ = ['JournalEntry']\n",
        encoding="utf-8",
    )

    assert discover_public_orm_exports(tmp_path / "apps/backend/src") == [
        "ledger::JournalEntry"
    ]
    assert main() == 0


def test_public_orm_export_gate_rejects_new_and_stale_debt(tmp_path: Path) -> None:
    src = tmp_path / "apps/backend/src/ledger"
    src.mkdir(parents=True)
    (src / "__init__.py").write_text(
        "from src.ledger.orm.entry import JournalEntry\n__all__ = ['JournalEntry']\n",
        encoding="utf-8",
    )
    baseline = tmp_path / "baseline.json"
    baseline.write_text(json.dumps(["ledger::Retired"]), encoding="utf-8")

    findings = violations(tmp_path, baseline)

    assert any("new public ORM export" in finding for finding in findings)
    assert any("stale public-ORM baseline" in finding for finding in findings)


def test_public_orm_export_gate_fails_on_missing_scan_target(tmp_path: Path) -> None:
    baseline = tmp_path / "baseline.json"
    baseline.write_text("[]\n", encoding="utf-8")

    assert any(
        "cannot discover public ORM exports" in finding
        for finding in violations(tmp_path, baseline)
    )
