"""Cross-language ratio API-parity guard (EPIC-012 AC12.9, #1167).

Mirrors the money parity guard: every name in ``vectors.json["shared_api"]`` MUST
be exported by BOTH the backend ratio module (``apps/backend/src/ratio/__init__.py``
``__all__``) and the frontend ratio module (``apps/frontend/src/lib/ratio/index.ts``),
so the two value-type APIs cannot silently drift.
"""

import ast
import json
import re
from pathlib import Path

from common.testing.ac_proof import ac_proof

REPO = Path(__file__).resolve().parents[2]
SHARED_API = set(json.loads((REPO / "common/ratio/conformance/vectors.json").read_text())["shared_api"])


def _backend_exports() -> set[str]:
    src = (REPO / "apps/backend/src/ratio/__init__.py").read_text()
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "__all__" for t in node.targets
        ):
            return {el.value for el in node.value.elts if isinstance(el, ast.Constant)}
    return set()


def _frontend_exports() -> set[str]:
    src = (REPO / "apps/frontend/src/lib/ratio/index.ts").read_text()
    names: set[str] = set()
    for block in re.findall(r"export\s*\{([^}]*)\}", src):
        for raw in block.split(","):
            name = raw.strip().removeprefix("type ").strip()
            if " as " in name:
                name = name.split(" as ")[-1].strip()
            if name:
                names.add(name)
    return names


@ac_proof(proof_id="test_ratio_shared_api_backend", ac_ids=["AC12.9.2"], ci_tier="pr_ci", issue="#1167")
def test_AC12_9_2_backend_exposes_shared_ratio_api():
    """AC12.9.2: the backend ratio module exports the full shared surface."""
    missing = SHARED_API - _backend_exports()
    assert not missing, f"backend src.ratio missing shared API: {sorted(missing)}"


@ac_proof(proof_id="test_ratio_shared_api_frontend", ac_ids=["AC12.9.2"], ci_tier="pr_ci", issue="#1167")
def test_AC12_9_2_frontend_exposes_shared_ratio_api():
    """AC12.9.2: the frontend ratio module exports the full shared surface."""
    missing = SHARED_API - _frontend_exports()
    assert not missing, f"frontend lib/ratio missing shared API: {sorted(missing)}"
