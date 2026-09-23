"""No hand-declared wire types outside generated schema (AC-meta.fe-contract-types.3, #1868 S5, #1985).

The generated `apps/frontend/src/lib/api-types.ts` (OpenAPI-derived, staleness-gated
by `tools/generate_openapi_spec.py --check`) is the single source of truth for
backend wire shapes; `lib/api-schema.ts` re-exports it as `Schemas["..."]` aliases
for exactly this purpose.

Issue #1985 bifurcates frontend types into:
1. Pure wire contracts: must resolve to `Schemas["..."]` aliases (0 hand-written
   `interface *Response` or `interface *Request` under `src/`, including `lib/types.ts`,
   with only generic envelopes or transport wrappers permitted).
2. Presentation ViewModels: explicit `*ViewModel` naming with paired typed
   normalizers in `lib/normalizers.ts`.
"""

from __future__ import annotations

import re
from pathlib import Path

from common.testing.ac_proof import ac_proof

REPO = Path(__file__).resolve().parents[2]
FRONTEND_SRC = REPO / "apps" / "frontend" / "src"
LIB_DIR = FRONTEND_SRC / "lib"
GENERATED_API_TYPES = LIB_DIR / "api-types.ts"
HTTP_CLIENT_BOUNDARY = LIB_DIR / "api.ts"

# Matches `interface FooResponse` or `interface FooRequest`, ignoring generic `interface ListResponse<T>`.
_WIRE_INTERFACE_DEF = re.compile(
    r"^\s*(?:export\s+)?interface\s+(\w*(?:Response|Request))\b(?!\s*<T>)", re.MULTILINE
)

# Matches exported `*ViewModel` declarations.
_VIEW_MODEL_DEF = re.compile(r"^\s*export\s+interface\s+(\w+ViewModel)\b", re.MULTILINE)

# Matches normalizer functions: `toFooViewModel`, `toFoo`, or `normalizeFoo`.
_NORMALIZER_FUNC_DEF = re.compile(
    r"^\s*export\s+function\s+(to\w+|normalize\w+)\b", re.MULTILINE
)


def _frontend_source_files(*, include_lib: bool = True) -> list[Path]:
    files: list[Path] = []
    for pattern in ("*.ts", "*.tsx"):
        for path in FRONTEND_SRC.rglob(pattern):
            if "node_modules" in path.parts or "__tests__" in path.parts:
                continue
            if path.name.endswith((".test.ts", ".test.tsx", ".spec.ts", ".spec.tsx")):
                continue
            if path.resolve() == GENERATED_API_TYPES.resolve():
                continue
            if not include_lib and LIB_DIR in path.parents:
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
        for path in _frontend_source_files(include_lib=False)
        if _WIRE_INTERFACE_DEF.search(path.read_text(encoding="utf-8"))
    ]
    assert not offenders, (
        "component-local Response/Request interfaces shadow the generated "
        "lib/api-types.ts contract; move the type into lib/ as a "
        'Schemas["..."] alias (see lib/api-schema.ts) or a justified hand '
        f"type: {offenders}"
    )


@ac_proof(
    proof_id="test_fe_wire_type_ssot_no_hand_declared_wire_interfaces_in_lib",
    ac_ids=["AC-meta.fe-contract-types.3"],
    ci_tier="pr_ci",
)
def test_AC_fe_wire_ssot_2_no_hand_declared_wire_interfaces_in_lib():
    """#1985 G-one-wire-owner: wire-shaped interfaces in lib/ must be Schemas[...] aliases."""
    lib_files = [
        path
        for path in _frontend_source_files(include_lib=True)
        if (LIB_DIR in path.parents or path.parent == LIB_DIR)
        and path.resolve() != HTTP_CLIENT_BOUNDARY.resolve()
    ]
    violations: list[str] = []
    for path in lib_files:
        content = path.read_text(encoding="utf-8")
        matches = _WIRE_INTERFACE_DEF.findall(content)
        if matches:
            violations.append(f"{path.relative_to(REPO)}: {matches}")

    assert not violations, (
        "Wire-shaped Response/Request interfaces under lib/ must resolve to generated "
        'Schemas["..."] aliases or be renamed to *ViewModel with an explicit normalizer: '
        f"{violations}"
    )


@ac_proof(
    proof_id="test_fe_wire_type_ssot_view_models_have_typed_normalizers",
    ac_ids=["AC-meta.fe-contract-types.3"],
    ci_tier="pr_ci",
)
def test_AC_fe_wire_ssot_3_view_models_have_typed_normalizers():
    """#1985 G-explicit-view-models: frontend view models require paired normalizer functions."""
    normalizers_path = LIB_DIR / "normalizers.ts"
    assert normalizers_path.exists(), "apps/frontend/src/lib/normalizers.ts must exist"

    content = normalizers_path.read_text(encoding="utf-8")
    view_models = _VIEW_MODEL_DEF.findall(content)
    normalizers = _NORMALIZER_FUNC_DEF.findall(content)

    assert view_models, "At least one ViewModel must be declared in normalizers.ts"
    assert normalizers, (
        "At least one normalizer function must be declared in normalizers.ts"
    )

    # Every ViewModel must have a corresponding mapper/normalizer function.
    for vm in view_models:
        base_name = vm.removesuffix("ViewModel")
        allowed = {
            f"to{vm}",
            f"to{base_name}",
            f"to{base_name}ViewModel",
            f"normalize{base_name}",
        }
        if vm == "BankStatementTransactionViewModel":
            allowed.add("toTransactionViewModel")

        has_paired_mapper = any(n in allowed for n in normalizers)
        assert has_paired_mapper, (
            f"ViewModel '{vm}' has no paired typed normalizer function in "
            f"apps/frontend/src/lib/normalizers.ts (found normalizers: {normalizers})"
        )


def test_AC_fe_wire_ssot_counterfactual_catches_shadow_wire_and_orphan_view_model():
    """Antagonist proof: verify that shadow wire interface and orphan view model trigger failures."""
    # Counterfactual 1: Hand-written FooResponse fails pattern check
    bad_code_wire = "export interface CustomReportResponse { data: string; }"
    assert _WIRE_INTERFACE_DEF.search(bad_code_wire) is not None

    # Counterfactual 2: Generic ListResponse<T> is permitted
    generic_list = "export interface ListResponse<T> { items: T[]; total: number; }"
    assert _WIRE_INTERFACE_DEF.search(generic_list) is None

    # Counterfactual 3: Orphan ViewModel without paired mapper fails assertion
    orphan_vm = "UnpairedWidgetViewModel"
    normalizers = ["toTransactionViewModel", "toJournalEntryViewModel"]
    base_name = orphan_vm.removesuffix("ViewModel")
    allowed = {
        f"to{orphan_vm}",
        f"to{base_name}",
        f"to{base_name}ViewModel",
        f"normalize{base_name}",
    }
    if orphan_vm == "BankStatementTransactionViewModel":
        allowed.add("toTransactionViewModel")

    has_paired_mapper = any(n in allowed for n in normalizers)
    assert not has_paired_mapper
