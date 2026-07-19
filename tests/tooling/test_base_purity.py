"""Base-layer dependency purity ratchet for #1894."""

from pathlib import Path
import json

from common.meta.extension.base_purity import discover_impurities
from common.meta.extension.check_base_purity import violations


def test_AC_meta_dependency_governance_4_base_impurity_is_exact(tmp_path: Path) -> None:
    """AC-meta.dependency-governance.4: forbidden base dependencies are explicit."""
    src = tmp_path / "apps/backend/src"
    (src / "ledger/base").mkdir(parents=True)
    (src / "ledger/base/rule.py").write_text(
        "from src.ledger.orm.journal import JournalEntry\n", encoding="utf-8"
    )
    (src / "ledger/base/pure.py").write_text(
        "from decimal import Decimal\n", encoding="utf-8"
    )

    assert discover_impurities(src) == [
        "ledger/base/rule.py::from src.ledger.orm.journal import JournalEntry"
    ]


def test_base_purity_gate_rejects_new_and_stale_debt(tmp_path: Path) -> None:
    src = tmp_path / "apps/backend/src/ledger/base"
    src.mkdir(parents=True)
    (src / "rule.py").write_text("import src.config\n", encoding="utf-8")
    baseline = tmp_path / "baseline.json"
    baseline.write_text(
        json.dumps(["retired/base.py::import src.config"]), encoding="utf-8"
    )

    findings = violations(tmp_path, baseline)

    assert any("new base impurity" in finding for finding in findings)
    assert any("stale base-purity baseline" in finding for finding in findings)
