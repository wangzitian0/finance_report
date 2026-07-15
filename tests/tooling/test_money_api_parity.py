"""Cross-language money API-parity guard (EPIC-002 AC2.19, #1167).

The conformance vectors lock money *behaviour* across ends; this locks the
*identifier surface*. Every name in ``vectors.json["shared_api"]`` MUST be
exported by BOTH the backend money module (``apps/backend/src/audit/money/__init__.py``
``__all__``) and the frontend money module (``apps/frontend/src/lib/audit/money/index.ts``
exports), so the two value-type APIs cannot silently drift (e.g. ``MONEY_DP`` vs
``MONEY_QUANTUM``, or a missing error type). Display/loose helpers are
intentionally per-end and are NOT part of the shared surface.
"""

import ast
import json
import re
from pathlib import Path

from common.testing.ac_proof import ac_proof

REPO = Path(__file__).resolve().parents[2]
VECTORS = json.loads((REPO / "common/audit/money/conformance/vectors.json").read_text())
SHARED_API = set(VECTORS["shared_api"])


def _backend_exports() -> set[str]:
    """Names in the backend money module's ``__all__``."""
    src = (REPO / "apps/backend/src/audit/money/__init__.py").read_text()
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "__all__" for t in node.targets
        ):
            return {el.value for el in node.value.elts if isinstance(el, ast.Constant)}
    return set()


def _frontend_exports() -> set[str]:
    """Identifiers re-exported from the frontend money module's index.ts."""
    src = (REPO / "apps/frontend/src/lib/audit/money/index.ts").read_text()
    # Collect names inside every `export { ... }` block (strip `type ` + aliases).
    names: set[str] = set()
    for block in re.findall(r"export\s*\{([^}]*)\}", src):
        for raw in block.split(","):
            name = raw.strip().removeprefix("type ").strip()
            if name:
                names.add(name)
    return names


@ac_proof(
    proof_id="test_money_shared_api_backend",
    ac_ids=["AC-audit.19.1"],
    ci_tier="pr_ci",
    issue="#1167",
)
def test_AC2_19_1_backend_exposes_shared_money_api():
    """AC-audit.19.1: the backend money module exports the full shared value-type surface."""
    missing = SHARED_API - _backend_exports()
    assert not missing, f"backend src.audit.money missing shared API: {sorted(missing)}"


@ac_proof(
    proof_id="test_money_shared_api_frontend",
    ac_ids=["AC-audit.19.1"],
    ci_tier="pr_ci",
    issue="#1167",
)
def test_AC2_19_1_frontend_exposes_shared_money_api():
    """AC-audit.19.1: the frontend money module exports the full shared value-type surface."""
    missing = SHARED_API - _frontend_exports()
    assert not missing, (
        f"frontend lib/audit/money missing shared API: {sorted(missing)}"
    )
