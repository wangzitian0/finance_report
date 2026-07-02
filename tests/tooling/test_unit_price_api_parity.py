"""Cross-language unit-price API-parity guard (EPIC-012 AC12.32).

The shipped backend ``src.audit.unit_price`` must export the full shared surface so the
reference (``common/audit/unit_price``) and runtime stay identical. A TypeScript
frontend is a P2 follow-up (#1253); when it lands, add its export check here.
"""

import ast
import json
from pathlib import Path

from common.testing.ac_proof import ac_proof

REPO = Path(__file__).resolve().parents[2]
SHARED_API = set(
    json.loads((REPO / "common/audit/unit_price/conformance/vectors.json").read_text())[
        "shared_api"
    ]
)


def _exports(init_path: Path) -> set[str]:
    src = init_path.read_text()
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "__all__" for t in node.targets
        ):
            return {el.value for el in node.value.elts if isinstance(el, ast.Constant)}
    return set()


@ac_proof(
    proof_id="test_unit_price_shared_api_common",
    ac_ids=["AC-audit.32.2"],
    ci_tier="pr_ci",
)
def test_AC12_32_2_common_exposes_shared_unit_price_api():
    """AC-audit.32.2: the reference unit-price module exports the full shared surface."""
    missing = SHARED_API - _exports(REPO / "common/audit/unit_price/__init__.py")
    assert not missing, f"common.audit.unit_price missing shared API: {sorted(missing)}"


@ac_proof(
    proof_id="test_unit_price_shared_api_backend",
    ac_ids=["AC-audit.32.2"],
    ci_tier="pr_ci",
)
def test_AC12_32_2_backend_exposes_shared_unit_price_api():
    """AC-audit.32.2: the shipped backend unit-price module exports the full shared surface."""
    missing = SHARED_API - _exports(
        REPO / "apps/backend/src/audit/unit_price/__init__.py"
    )
    assert not missing, (
        f"backend src.audit.unit_price missing shared API: {sorted(missing)}"
    )
