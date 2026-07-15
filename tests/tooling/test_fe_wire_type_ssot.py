"""No hand-declared wire types outside lib/ (AC-meta.fe-contract-types.3, #1868 S5).

The generated `apps/frontend/src/lib/api-types.ts` (OpenAPI-derived, staleness-gated
by `tools/generate_openapi_spec.py --check`) is the single source of truth for
backend wire shapes; `lib/api-schema.ts` re-exports it as `Schemas["..."]` aliases
for exactly this purpose. The 2026-07-15 signature review found 7 component-local
`interface FooResponse { ... }`/`interface FooRequest { ... }` declarations across
6 files that silently duplicated (and in one case, drifted from — `filters_applied`
was never actually sent by the backend) the generated shapes. This gate keeps that
class of drift from coming back: every wire-shaped interface must live in `lib/`,
where it is either a `Schemas["..."]` alias or a deliberately-justified hand type
(e.g. `FxWarning`, documented inline for why it diverges from the generated field).
"""

from __future__ import annotations

import re
from pathlib import Path

from common.testing.ac_proof import ac_proof

REPO = Path(__file__).resolve().parents[2]
FRONTEND_SRC = REPO / "apps" / "frontend" / "src"
LIB_DIR = FRONTEND_SRC / "lib"

# Line-anchored (not a raw substring scan) so a comment or string mentioning
# "interface FooResponse" can't false-positive, mirroring the async-aware
# lesson from tests/tooling/test_safe_error_message_ssot.py (#1864 S1, PR #1871
# Copilot review). `export`/visibility is optional — both `interface Foo` and
# `export interface Foo` are wire-shaped declarations that must live in lib/.
_WIRE_INTERFACE_DEF = re.compile(
    r"^\s*(?:export\s+)?interface\s+\w*(?:Response|Request)\b", re.MULTILINE
)


def _frontend_source_files() -> list[Path]:
    files: list[Path] = []
    for pattern in ("*.ts", "*.tsx"):
        for path in FRONTEND_SRC.rglob(pattern):
            if "node_modules" in path.parts or "__tests__" in path.parts:
                continue
            if path.name.endswith((".test.ts", ".test.tsx", ".spec.ts", ".spec.tsx")):
                continue
            if LIB_DIR in path.parents:
                continue
            files.append(path)
    return files


@ac_proof(
    proof_id="test_fe_wire_type_ssot_no_hand_declared_interfaces_outside_lib",
    ac_ids=["AC-meta.fe-contract-types.3"],
    ci_tier="pr_ci",
)
def test_AC_fe_wire_ssot_1_no_hand_declared_response_request_outside_lib():
    """AC-meta.fe-contract-types.3: wire-shaped interfaces live only in lib/."""
    offenders = [
        str(path.relative_to(REPO))
        for path in _frontend_source_files()
        if _WIRE_INTERFACE_DEF.search(path.read_text(encoding="utf-8"))
    ]
    assert not offenders, (
        "component-local Response/Request interfaces shadow the generated "
        "lib/api-types.ts contract; move the type into lib/ as a "
        'Schemas["..."] alias (see lib/api-schema.ts) or a justified hand '
        f"type: {offenders}"
    )
