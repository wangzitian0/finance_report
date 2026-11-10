'AC-meta.fe-contract-types.3'; from __future__ import annotations; import json; import re; from functools import lru_cache; from pathlib import Path; from common.testing.ac_proof import ac_proof; REPO = Path(__file__).resolve().parents[2]; FRONTEND_SRC = REPO / 'apps' / 'frontend' / 'src'; LIB_DIR = FRONTEND_SRC / 'lib'; GENERATED_API_TYPES = LIB_DIR / 'api-types.ts'; HTTP_CLIENT_BOUNDARY = LIB_DIR / 'api.ts'; OPENAPI_SPEC = REPO / 'apps' / 'frontend' / 'openapi.json'; _WIRE_INTERFACE_DEF = re.compile('^\\s*(?:export\\s+)?interface\\s+(\\w*(?:Response|Request))\\b(?!\\s*<T>)', re.MULTILINE); _ALL_INTERFACE_DEF = re.compile('^\\s*(?:export\\s+)?interface\\s+(\\w+)\\b(?!\\s*<T>)', re.MULTILINE); _SHADOW_WIRE_ALIAS_DEF = re.compile('^\\s*export\\s+type\\s+(\\w+(?:Response|Request))\\b\\s*=\\s*([^;]+);', re.MULTILINE); _VIEW_MODEL_DEF = re.compile('^\\s*export\\s+interface\\s+(\\w+ViewModel)\\b', re.MULTILINE); _NORMALIZER_FUNC_DEF = re.compile('^\\s*export\\s+function\\s+(to\\w+|normalize\\w+)\\b', re.MULTILINE)
def _frontend_source_files(*, include_lib: bool=True) -> list[Path]:
    files: list[Path] = []
    for pattern in ('*.ts', '*.tsx'):
        for path in FRONTEND_SRC.rglob(pattern):
            if 'node_modules' in path.parts or '__tests__' in path.parts: continue
            if path.name.endswith(('.test.ts', '.test.tsx', '.spec.ts', '.spec.tsx')): continue
            if path.resolve() == GENERATED_API_TYPES.resolve(): continue
            if not include_lib and LIB_DIR in path.parents: continue
            files.append(path)
    return files
@lru_cache(maxsize=1)
def _openapi_schemas() -> frozenset[str]:
    if not OPENAPI_SPEC.exists(): return frozenset()
    data = json.loads(OPENAPI_SPEC.read_text(encoding='utf-8')); return frozenset(data.get('components', {}).get('schemas', {}).keys())
@ac_proof(proof_id='test_fe_wire_type_ssot_no_hand_declared_interfaces_outside_lib', ac_ids=['AC-meta.fe-contract-types.3'], ci_tier='pr_ci')
def test_AC_fe_wire_ssot_1_no_hand_declared_response_request_outside_lib(): 'AC-meta.fe-contract-types.3'; offenders = [str(path.relative_to(REPO)) for path in _frontend_source_files(include_lib=False) if _WIRE_INTERFACE_DEF.search(path.read_text(encoding='utf-8'))]; assert not offenders, f'component-local Response/Request interfaces shadow the generated lib/api-types.ts contract; move the type into lib/ as a Schemas["..."] alias (see lib/api-schema.ts) or a justified hand type: {offenders}'
@ac_proof(proof_id='test_fe_wire_type_ssot_no_hand_declared_wire_interfaces_in_lib', ac_ids=['AC-meta.fe-contract-types.3'], ci_tier='pr_ci')
def test_AC_fe_wire_ssot_2_no_hand_declared_wire_interfaces_in_lib():
    lib_files = [path for path in _frontend_source_files(include_lib=True) if (LIB_DIR in path.parents or path.parent == LIB_DIR) and path.resolve() != HTTP_CLIENT_BOUNDARY.resolve()]; violations: list[str] = []
    for path in lib_files: content = path.read_text(encoding='utf-8'); matches = _WIRE_INTERFACE_DEF.findall(content); violations.append(f'{path.relative_to(REPO)} interfaces: {matches}') if matches else None; [violations.append(f'{path.relative_to(REPO)} alias to ViewModel: {name} = {rhs.strip()}') if 'ViewModel' in rhs else None for name, rhs in _SHADOW_WIRE_ALIAS_DEF.findall(content)]
    assert not violations, f'Wire-shaped Response/Request interfaces under lib/ must resolve to generated Schemas["..."] aliases or be renamed to *ViewModel with an explicit normalizer: {violations}'
@ac_proof(proof_id='test_fe_wire_type_ssot_view_models_have_typed_normalizers', ac_ids=['AC-meta.fe-contract-types.3'], ci_tier='pr_ci')
def test_AC_fe_wire_ssot_3_view_models_have_typed_normalizers():
    lib_files = [path for path in _frontend_source_files(include_lib=True) if LIB_DIR in path.parents or path.parent == LIB_DIR]; all_view_models: dict[str, Path] = {}; all_normalizers: set[str] = set()
    for path in lib_files:
        content = path.read_text(encoding='utf-8')
        for vm in _VIEW_MODEL_DEF.findall(content): all_view_models[vm] = path
        [all_normalizers.add(norm) for norm in _NORMALIZER_FUNC_DEF.findall(content)]
    assert all_view_models, 'At least one ViewModel must be declared under lib/'; assert all_normalizers, 'At least one normalizer function must be declared under lib/'
    for (vm, path) in all_view_models.items():
        base_name = vm.removesuffix('ViewModel'); allowed = {f'to{vm}', f'to{base_name}', f'to{base_name}ViewModel', f'normalize{base_name}', f'normalize{vm}'}; allowed.add('toTransactionViewModel') if vm == 'BankStatementTransactionViewModel' else None
        if 'PersonalReportPackage' in vm: allowed.add('normalizePersonalReportPackageDocument'); allowed.add('normalizePersonalReportPackageSnapshot')
        has_paired_mapper = any((n in allowed for n in all_normalizers)); assert has_paired_mapper, f"ViewModel '{vm}' in {path.relative_to(REPO)} has no paired typed normalizer function in lib/ (found normalizers: {sorted(all_normalizers)})"
@ac_proof(proof_id='test_fe_wire_type_ssot_no_hand_declared_entity_schemas_in_src', ac_ids=['AC-meta.fe-contract-types.3'], ci_tier='pr_ci')
def test_AC_fe_wire_ssot_4_no_hand_declared_entity_schemas_in_src():
    schemas = _openapi_schemas(); assert schemas, f'OpenAPI schema definitions must exist at {OPENAPI_SPEC}'; violations: list[str] = []
    for path in _frontend_source_files(include_lib=True):
        content = path.read_text(encoding='utf-8')
        for name in _ALL_INTERFACE_DEF.findall(content):
            if name.endswith('ViewModel') or name.endswith('Props'): continue
            violations.append(f'{path.relative_to(REPO)}: interface {name} shadows OpenAPI schema') if name in schemas or f'{name}Response' in schemas else None
    assert not violations, f'Hand-declared interfaces shadow OpenAPI schemas. Converge them to Schemas["..."] aliases in lib/types.ts or rename to *ViewModel: {violations}'
@ac_proof(proof_id='test_fe_wire_type_ssot_core_entities_are_schema_aliases', ac_ids=['AC-meta.fe-contract-types.3'], ci_tier='pr_ci')
def test_AC_fe_wire_ssot_5_core_entities_are_schema_aliases():
    types_file = LIB_DIR / 'types.ts'; assert types_file.exists(), f'Expected {types_file} to exist'; content = types_file.read_text(encoding='utf-8'); core_aliases = ['Account', 'JournalLine', 'BankTransactionSummary', 'BalanceValidationResult', 'WorkflowPrimaryState', 'WorkflowNextActionType', 'WorkflowReportReadinessState', 'WorkflowEventFamily', 'WorkflowEventSeverity', 'WorkflowEventStatus', 'WorkflowReportImpact', 'WorkflowSessionStatus', 'ManualValuationComponentType', 'ManualValuationLiquidityClass', 'ManualValuationBasis', 'AiSuggestion', 'PingStateResponse']; missing_aliases: list[str] = []
    for alias in core_aliases: pattern = f'^\\s*export\\s+type\\s+{alias}\\b\\s*=\\s*Schemas\\["[^"]+"\\];'; missing_aliases.append(alias) if not re.search(pattern, content, re.MULTILINE) else None
    assert not missing_aliases, f'Core domain entities/enums in lib/types.ts must be Schemas[...] aliases: {missing_aliases}'
def test_AC_fe_wire_ssot_counterfactual_catches_shadow_wire_and_orphan_view_model(): bad_code_wire = 'export interface CustomReportResponse { data: string; }'; assert _WIRE_INTERFACE_DEF.search(bad_code_wire) is not None; generic_list = 'export interface ListResponse<T> { items: T[]; total: number; }'; assert _WIRE_INTERFACE_DEF.search(generic_list) is None; orphan_vm = 'UnpairedWidgetViewModel'; normalizers = ['toTransactionViewModel', 'toJournalEntryViewModel']; base_name = orphan_vm.removesuffix('ViewModel'); allowed = {f'to{orphan_vm}', f'to{base_name}', f'to{base_name}ViewModel', f'normalize{base_name}'}; allowed.add('toTransactionViewModel') if orphan_vm == 'BankStatementTransactionViewModel' else None; has_paired_mapper = any((n in allowed for n in normalizers)); assert not has_paired_mapper; shadow_alias = 'export type CustomReportResponse = CustomReportViewModel;'; shadow_matches = [name for name, rhs in _SHADOW_WIRE_ALIAS_DEF.findall(shadow_alias) if 'ViewModel' in rhs]; assert shadow_matches == ['CustomReportResponse']; bad_account_interface = 'export interface Account { id: string; name: string; }'; account_matches = [name for name in _ALL_INTERFACE_DEF.findall(bad_account_interface) if name in {'Account', 'AccountResponse'} or f'{name}Response' in {'AccountResponse'}]; assert 'Account' in account_matches; bad_balance_interface = 'export interface BalanceValidationResult { opening_balance: string; }'; balance_matches = [name for name in _ALL_INTERFACE_DEF.findall(bad_balance_interface) if name in {'BalanceValidationResult'} or f'{name}Response' in {'BalanceValidationResultResponse'}]; assert 'BalanceValidationResult' in balance_matches; fake_types_content = "export type WorkflowPrimaryState = 'open' | 'closed';"; pattern = '^\\s*export\\s+type\\s+WorkflowPrimaryState\\b\\s*=\\s*Schemas\\["[^"]+"\\];'; assert re.search(pattern, fake_types_content, re.MULTILINE) is None
