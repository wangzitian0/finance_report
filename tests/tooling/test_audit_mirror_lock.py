"""Single-kernel lock for ``common.audit`` -> ``apps/backend/src/audit`` (#2752).

``apps/backend/src/audit`` is the single Python kernel implementation. ``common/audit``
holds only the package contract, the bare-Python tooling guards/vector loaders, and
``__init__.py`` which bridges ``common.audit.*`` directly to ``src.audit.*`` without
requiring SQLAlchemy at import time.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import common.audit
import src.audit
from common.testing.ac_proof import ac_proof

REPO = Path(__file__).resolve().parents[2]
COMMON_ROOT = REPO / "common/audit"

ALLOWED_COMMON_PY_FILES = {
    "__init__.py",
    "contract.py",
    "extension/cascade_ownership.py",
    "money/guard.py",
    "money/conformance/__init__.py",
    "quantity/conformance/__init__.py",
    "ratio/conformance/__init__.py",
    "unit_price/conformance/__init__.py",
}


@ac_proof(
    proof_id="test_audit_mirrored_modules_are_ast_equal",
    ac_ids=["AC-audit.43.1"],
    ci_tier="pr_ci",
    issue="#2752",
)
def test_AC_audit_43_1_mirrored_modules_are_ast_equal() -> None:
    """AC-audit.43.1: common/audit has zero duplicate kernel files and bridges to src.audit."""
    actual = {str(p.relative_to(COMMON_ROOT)) for p in COMMON_ROOT.rglob("*.py")}
    assert actual == ALLOWED_COMMON_PY_FILES

    assert common.audit.Money is src.audit.Money
    assert common.audit.Ratio is src.audit.Ratio
    assert common.audit.Quantity is src.audit.Quantity
    assert common.audit.UnitPrice is src.audit.UnitPrice
    assert common.audit.TraceRecord is src.audit.TraceRecord

    probe = (
        "import sys; sys.modules['sqlalchemy'] = None; "
        "import common.audit, common.audit.money, common.audit.base.trace, "
        "common.audit.extension.trace_adapters"
    )
    res = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )
    assert res.returncode == 0, res.stderr
