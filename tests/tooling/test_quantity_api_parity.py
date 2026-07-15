"""Cross-language quantity API-parity guard (EPIC-012 AC12.30)."""

import ast
import json
import re
from pathlib import Path

from common.testing.ac_proof import ac_proof

REPO = Path(__file__).resolve().parents[2]
SHARED_API = set(
    json.loads((REPO / "common/audit/quantity/conformance/vectors.json").read_text())[
        "shared_api"
    ]
)


def _backend_exports() -> set[str]:
    src = (REPO / "apps/backend/src/audit/quantity/__init__.py").read_text()
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "__all__" for t in node.targets
        ):
            return {el.value for el in node.value.elts if isinstance(el, ast.Constant)}
    return set()


def _frontend_exports() -> set[str]:
    src = (REPO / "apps/frontend/src/lib/audit/quantity/index.ts").read_text()
    names: set[str] = set()
    for block in re.findall(r"export\s*\{([^}]*)\}", src):
        for raw in block.split(","):
            name = raw.strip().removeprefix("type ").strip()
            if " as " in name:
                name = name.split(" as ")[-1].strip()
            if name:
                names.add(name)
    return names


@ac_proof(
    proof_id="test_quantity_shared_api_backend",
    ac_ids=["AC-audit.30.2"],
    ci_tier="pr_ci",
)
def test_AC12_30_2_backend_exposes_shared_quantity_api():
    """AC-audit.30.2: the backend quantity module exports the full shared surface."""
    missing = SHARED_API - _backend_exports()
    assert not missing, (
        f"backend src.audit.quantity missing shared API: {sorted(missing)}"
    )


@ac_proof(
    proof_id="test_quantity_shared_api_frontend",
    ac_ids=["AC-audit.30.2"],
    ci_tier="pr_ci",
)
def test_AC12_30_2_frontend_exposes_shared_quantity_api():
    """AC-audit.30.2: the frontend quantity module exports the full shared surface."""
    missing = SHARED_API - _frontend_exports()
    assert not missing, (
        f"frontend lib/audit/quantity missing shared API: {sorted(missing)}"
    )
