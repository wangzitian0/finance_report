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

import json
import re
from functools import lru_cache
from pathlib import Path

from common.testing.ac_proof import ac_proof

REPO = Path(__file__).resolve().parents[2]
FRONTEND_SRC = REPO / "apps" / "frontend" / "src"
LIB_DIR = FRONTEND_SRC / "lib"
GENERATED_API_TYPES = LIB_DIR / "api-types.ts"
HTTP_CLIENT_BOUNDARY = LIB_DIR / "api.ts"
OPENAPI_SPEC = REPO / "apps" / "frontend" / "openapi.json"

# Matches `interface FooResponse` or `interface FooRequest`, ignoring generic `interface ListResponse<T>`.
_WIRE_INTERFACE_DEF = re.compile(
    r"^\s*(?:export\s+)?interface\s+(\w*(?:Response|Request))\b(?!\s*<T>)", re.MULTILINE
)

# Matches any interface definition, ignoring generic `interface ListResponse<T>`.
_ALL_INTERFACE_DEF = re.compile(
    r"^\s*(?:export\s+)?interface\s+(\w+)\b(?!\s*<T>)", re.MULTILINE
)

# Matches exported `type FooResponse = ...` or `type FooRequest = ...`.
_SHADOW_WIRE_ALIAS_DEF = re.compile(
    r"^\s*export\s+type\s+(\w+(?:Response|Request))\b\s*=\s*([^;]+);", re.MULTILINE
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


@lru_cache(maxsize=1)
def _openapi_schemas() -> frozenset[str]:
    if not OPENAPI_SPEC.exists():
        return frozenset()
    data = json.loads(OPENAPI_SPEC.read_text(encoding="utf-8"))
    return frozenset(data.get("components", {}).get("schemas", {}).keys())


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
            violations.append(f"{path.relative_to(REPO)} interfaces: {matches}")

        for name, rhs in _SHADOW_WIRE_ALIAS_DEF.findall(content):
            if "ViewModel" in rhs:
                violations.append(
                    f"{path.relative_to(REPO)} alias to ViewModel: {name} = {rhs.strip()}"
                )

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
    lib_files = [
        path
        for path in _frontend_source_files(include_lib=True)
        if (LIB_DIR in path.parents or path.parent == LIB_DIR)
    ]
    all_view_models: dict[str, Path] = {}
    all_normalizers: set[str] = set()

    for path in lib_files:
        content = path.read_text(encoding="utf-8")
        for vm in _VIEW_MODEL_DEF.findall(content):
            all_view_models[vm] = path
        for norm in _NORMALIZER_FUNC_DEF.findall(content):
            all_normalizers.add(norm)

    assert all_view_models, "At least one ViewModel must be declared under lib/"
    assert all_normalizers, (
        "At least one normalizer function must be declared under lib/"
    )

    for vm, path in all_view_models.items():
        base_name = vm.removesuffix("ViewModel")
        allowed = {
            f"to{vm}",
            f"to{base_name}",
            f"to{base_name}ViewModel",
            f"normalize{base_name}",
            f"normalize{vm}",
        }
        if vm == "BankStatementTransactionViewModel":
            allowed.add("toTransactionViewModel")
        if "PersonalReportPackage" in vm:
            allowed.add("normalizePersonalReportPackageDocument")
            allowed.add("normalizePersonalReportPackageSnapshot")

        has_paired_mapper = any(n in allowed for n in all_normalizers)
        assert has_paired_mapper, (
            f"ViewModel '{vm}' in {path.relative_to(REPO)} has no paired typed normalizer function in "
            f"lib/ (found normalizers: {sorted(all_normalizers)})"
        )


@ac_proof(
    proof_id="test_fe_wire_type_ssot_no_hand_declared_entity_schemas_in_src",
    ac_ids=["AC-meta.fe-contract-types.3"],
    ci_tier="pr_ci",
)
def test_AC_fe_wire_ssot_4_no_hand_declared_entity_schemas_in_src():
    """No hand-declared interfaces in FE matching OpenAPI schema names (#2127).

    Generated `lib/api-types.ts` is the single source of truth. Declaring
    `interface Foo` where `Foo` or `FooResponse` is in OpenAPI schemas
    creates shadow types that drift silently from the wire contract.
    Such types must be `Schemas["..."]` aliases or explicit `*ViewModel`s.
    """
    schemas = _openapi_schemas()
    assert schemas, f"OpenAPI schema definitions must exist at {OPENAPI_SPEC}"

    violations: list[str] = []
    for path in _frontend_source_files(include_lib=True):
        content = path.read_text(encoding="utf-8")
        for name in _ALL_INTERFACE_DEF.findall(content):
            if name.endswith("ViewModel") or name.endswith("Props"):
                continue
            if name in schemas or f"{name}Response" in schemas:
                violations.append(
                    f"{path.relative_to(REPO)}: interface {name} shadows OpenAPI schema"
                )

    assert not violations, (
        "Hand-declared interfaces shadow OpenAPI schemas. "
        'Converge them to Schemas["..."] aliases in lib/types.ts or rename to *ViewModel: '
        f"{violations}"
    )


@ac_proof(
    proof_id="test_fe_wire_type_ssot_core_entities_are_schema_aliases",
    ac_ids=["AC-meta.fe-contract-types.3"],
    ci_tier="pr_ci",
)
def test_AC_fe_wire_ssot_5_core_entities_are_schema_aliases():
    """Core domain entities and enums in lib/types.ts must be pure Schemas[...] aliases (#2127)."""
    types_file = LIB_DIR / "types.ts"
    assert types_file.exists(), f"Expected {types_file} to exist"
    content = types_file.read_text(encoding="utf-8")

    core_aliases = [
        "Account",
        "JournalLine",
        "BankTransactionSummary",
        "BalanceValidationResult",
        "WorkflowPrimaryState",
        "WorkflowNextActionType",
        "WorkflowReportReadinessState",
        "WorkflowEventFamily",
        "WorkflowEventSeverity",
        "WorkflowEventStatus",
        "WorkflowReportImpact",
        "WorkflowSessionStatus",
        "ManualValuationComponentType",
        "ManualValuationLiquidityClass",
        "ManualValuationBasis",
        "AiSuggestion",
        "PingStateResponse",
    ]

    missing_aliases: list[str] = []
    for alias in core_aliases:
        # Matches: `export type <alias> = Schemas["..."]`
        pattern = rf'^\s*export\s+type\s+{alias}\b\s*=\s*Schemas\["[^"]+"\];'
        if not re.search(pattern, content, re.MULTILINE):
            missing_aliases.append(alias)

    assert not missing_aliases, (
        f"Core domain entities/enums in lib/types.ts must be Schemas[...] aliases: {missing_aliases}"
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

    # Counterfactual 4: Type alias Response pointing to ViewModel is caught
    shadow_alias = "export type CustomReportResponse = CustomReportViewModel;"
    shadow_matches = [
        name
        for name, rhs in _SHADOW_WIRE_ALIAS_DEF.findall(shadow_alias)
        if "ViewModel" in rhs
    ]
    assert shadow_matches == ["CustomReportResponse"]

    # Counterfactual 5: Hand-written interface Account is caught by entity schema check
    bad_account_interface = "export interface Account { id: string; name: string; }"
    account_matches = [
        name
        for name in _ALL_INTERFACE_DEF.findall(bad_account_interface)
        if name in {"Account", "AccountResponse"}
        or f"{name}Response" in {"AccountResponse"}
    ]
    assert "Account" in account_matches

    # Counterfactual 6: Hand-written BalanceValidationResult is caught by entity schema check
    bad_balance_interface = (
        "export interface BalanceValidationResult { opening_balance: string; }"
    )
    balance_matches = [
        name
        for name in _ALL_INTERFACE_DEF.findall(bad_balance_interface)
        if name in {"BalanceValidationResult"}
        or f"{name}Response" in {"BalanceValidationResultResponse"}
    ]
    assert "BalanceValidationResult" in balance_matches

    # Counterfactual 7: Hand-written enum union fails core alias check
    fake_types_content = "export type WorkflowPrimaryState = 'open' | 'closed';"
    pattern = r'^\s*export\s+type\s+WorkflowPrimaryState\b\s*=\s*Schemas\["[^"]+"\];'
    assert re.search(pattern, fake_types_content, re.MULTILINE) is None
