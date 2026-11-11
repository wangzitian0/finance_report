"""Test execution matrix as code — the SSOT for test placement and selection."""

from __future__ import annotations

import importlib
import shlex
from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class PathRule:
    """One path-prefix -> execution-stage classification rule."""

    path: str
    stage: str
    ci_required: bool


PATH_RULES: tuple[PathRule, ...] = (
    PathRule("apps/backend/tests/integration/", "backend_integration", True),
    PathRule("apps/backend/tests/", "backend_ci", True),
    PathRule("apps/frontend/playwright/", "frontend_playwright_ci", True),
    PathRule("apps/frontend/src/", "frontend_vitest", True),
    PathRule("tests/tooling/", "tooling_ci", True),
    PathRule("tools/tier2_http_e2e.py", "deployment_tier2_http_e2e", False),
    PathRule("tests/e2e/", "deployment_e2e", True),
)


def classify_stage(path: str) -> str | None:
    """Return the execution stage for a repo-relative test path (first match)."""
    return next((rule.stage for rule in PATH_RULES if path.startswith(rule.path)), None)


PACKAGE_TEST_DECLARATIONS: tuple[str, ...] = ("runtime", "ledger", "testing")


def package_test_ownership() -> dict[str, str]:
    """Aggregate declared test roots -> owning package."""
    ownership: dict[str, str] = {}
    for pkg in PACKAGE_TEST_DECLARATIONS:
        contract = importlib.import_module(f"common.{pkg}.contract")
        roots = getattr(contract, "TEST_ROOTS", None)
        if not roots:
            raise ValueError(
                f"package {pkg!r} is in PACKAGE_TEST_DECLARATIONS but its "
                "contract.py declares no TEST_ROOTS"
            )
        if isinstance(roots, str):
            raise ValueError(
                f"package {pkg!r}: TEST_ROOTS must be a tuple of paths, not a bare string"
            )
        for root in roots:
            other = ownership.get(root)
            if other is not None:
                raise ValueError(
                    f"test root {root!r} declared by both {other!r} and {pkg!r}"
                )
            ownership[root] = pkg
    return ownership


GENERATED_MATRIX_HEADER = (
    "# GENERATED from common/testing/matrix.py — do not hand-edit.\n"
    "# Regenerate: python tools/test_selection.py --emit-matrix\n"
    "# Drift gate: tests/tooling/test_execution_matrix_contract.py (AC8.22.1)\n"
)


def emit_execution_matrix_yaml() -> str:
    """Render common/testing/data/test-execution-matrix.yaml without PyYAML."""
    lines = [GENERATED_MATRIX_HEADER + "version: 1", "rules:"]
    for rule in PATH_RULES:
        lines.extend(
            (
                f"  - path: {rule.path}",
                f"    stage: {rule.stage}",
                f"    ci_required: {'true' if rule.ci_required else 'false'}",
            )
        )
    lines.append("ownership:")
    for root, pkg in sorted(package_test_ownership().items()):
        lines.extend((f"  - path: {root}", f"    package: {pkg}"))
    return "\n".join(lines) + "\n"


NEEDS_LLM_PROVIDER = "llm_provider"
NEEDS_MARKET_DATA = "market_data"
NEEDS_DEPLOYED_ENV = "deployed_env"
NEEDS_STATE_SENSITIVE = "state_sensitive"

CORE_JOURNEY_ONLY_FILES: frozenset[str] = frozenset(
    {
        "tests/e2e/test_transfer_processing_journey.py",
        "tests/e2e/test_opening_balance_browser_journey.py",
        "tests/e2e/test_twelve_month_journey.py",
        "tests/e2e/test_confidence_metrics_journey.py",
    }
)


@dataclass(frozen=True)
class E2ERow:
    """Named ownership row for one root E2E spec file."""

    file: str
    needs: tuple[str, ...]
    audited: bool
    reason: str
    nodes: tuple[str, ...] = ()
    frontend_paths: tuple[str, ...] = ()

    @property
    def staging_core_e2e(self) -> bool:
        return (
            self.audited
            and NEEDS_LLM_PROVIDER not in self.needs
            and self.file not in CORE_JOURNEY_ONLY_FILES
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "file": self.file,
            "needs": list(self.needs),
            "audited": self.audited,
            "reason": self.reason,
            "nodes": list(self.nodes),
            "frontend_paths": list(self.frontend_paths),
            "staging_core_e2e": self.staging_core_e2e,
        }


def _e2e(
    name: str,
    needs: tuple[str, ...] = (),
    reason: str = "Real AI/OCR provider (llm marker); audit-replay corpus.",
    *,
    frontend_paths: tuple[str, ...] = (),
) -> E2ERow:
    return E2ERow(
        f"tests/e2e/{name}",
        needs=needs,
        audited=True,
        reason=reason,
        frontend_paths=frontend_paths,
    )


E2E_ROWS: tuple[E2ERow, ...] = (
    _e2e(
        "test_epic022_ia_shell.py",
        reason="EPIC-022 everyday-user shell proof; authenticated browser + frontend shell only.",
        frontend_paths=(
            "apps/frontend/src/app/(main)/layout.tsx",
            "apps/frontend/src/app/(main)/page.tsx",
            "apps/frontend/src/components/AppShell.tsx",
            "apps/frontend/src/components/AppNav.tsx",
            "apps/frontend/src/components/navigation.ts",
            "apps/frontend/src/components/shell/",
            "apps/frontend/src/components/workflow/",
        ),
    ),
    _e2e(
        "test_vision_upload_to_dashboard_hard_gate.py",
        reason="#1547 non-provider upload-to-dashboard hard gate.",
        frontend_paths=(
            "apps/frontend/src/app/(main)/upload/",
            "apps/frontend/src/app/(main)/statements/",
            "apps/frontend/src/components/statements/",
            "apps/frontend/src/components/review/",
        ),
    ),
    _e2e(
        "test_brokerage_upload_to_portfolio_value.py",
        (NEEDS_LLM_PROVIDER,),
        "Real AI/OCR provider (llm marker); staging canary corpus.",
    ),
    _e2e(
        "test_transfer_processing_journey.py",
        (NEEDS_DEPLOYED_ENV,),
        "Core-journey board proof U7 (#2384): post-deploy core_journey lane (#2370).",
    ),
    _e2e("test_four_asset_net_worth_golden_path.py", (NEEDS_LLM_PROVIDER,)),
    _e2e("test_personal_financial_report_package.py", (NEEDS_LLM_PROVIDER,)),
    _e2e("test_statement_full_journey.py", (NEEDS_LLM_PROVIDER,)),
    _e2e(
        "test_statement_upload_e2e.py",
        (NEEDS_LLM_PROVIDER,),
        "Real AI/OCR provider (llm marker); supplemental staging corpus.",
    ),
    _e2e(
        "test_gxs_browser_journey.py",
        (NEEDS_LLM_PROVIDER,),
        "Real provider fresh-user browser upload/review/saved-package proof; audit replay only.",
    ),
    _e2e(
        "test_opening_balance_browser_journey.py",
        (NEEDS_DEPLOYED_ENV,),
        "Core-journey board proof U5 (#2383): post-deploy core_journey lane (#2370).",
    ),
    _e2e(
        "test_twelve_month_journey.py",
        (NEEDS_DEPLOYED_ENV,),
        "Core-journey board proof U9 (#2370): post-deploy core_journey lane.",
    ),
    _e2e(
        "test_confidence_metrics_journey.py",
        (NEEDS_DEPLOYED_ENV,),
        "Core-journey board proof U13 (#2370): post-deploy core_journey lane.",
    ),
    _e2e(
        "test_stage1_routing_journey.py",
        (NEEDS_LLM_PROVIDER,),
        "Real provider Stage 1 routing proof U3 (#2392); audit replay and core-journey lane.",
    ),
    _e2e(
        "test_zero_click_statement_journey.py",
        (NEEDS_LLM_PROVIDER,),
        "Real provider zero-click proof (#2405): upload posts rows and statements tie.",
    ),
    _e2e(
        "test_assistant_chat_journey.py",
        (NEEDS_LLM_PROVIDER,),
        "Core-journey proof U14 (#2461): live assistant answers with report amounts.",
    ),
    _e2e(
        "test_institution_statement_journeys.py",
        (NEEDS_LLM_PROVIDER,),
        "Real AI/OCR provider (llm marker); per-institution statement shapes (#1613).",
    ),
    _e2e(
        "test_ai_provider_connectivity.py",
        (NEEDS_LLM_PROVIDER,),
        "Real provider connectivity probe (llm marker); staging provider gate.",
    ),
    _e2e(
        "test_market_data_price_paths.py",
        (NEEDS_MARKET_DATA,),
        "Calls the real market-data provider; staging responsibility.",
        frontend_paths=(
            "apps/frontend/src/app/(main)/portfolio/",
            "apps/frontend/src/components/portfolio/",
        ),
    ),
    _e2e(
        "test_production_readonly_smoke.py",
        (NEEDS_DEPLOYED_ENV,),
        "prod_safe read-only probe of a persistent deployed environment.",
        frontend_paths=(
            "apps/frontend/src/app/login/",
            "apps/frontend/src/app/(main)/page.tsx",
        ),
    ),
    _e2e(
        "test_frontend_observability_epic024.py",
        (NEEDS_DEPLOYED_ENV,),
        "Probes deployed telemetry wiring (prod_safe smoke).",
        frontend_paths=(
            "apps/frontend/src/components/FrontendTelemetry.tsx",
            "apps/frontend/src/components/RootClients.tsx",
            "apps/frontend/src/app/layout.tsx",
        ),
    ),
    _e2e(
        "test_auth_flows.py",
        (NEEDS_STATE_SENSITIVE,),
        "Registration/auth state-sensitive workflow; staging responsibility.",
        frontend_paths=(
            "apps/frontend/src/app/login/",
            "apps/frontend/src/app/frontend-version.json/",
        ),
    ),
    _e2e(
        "test_version_check.py",
        reason="API-only GET /api/health comparing git_sha with EXPECTED_SHA (#1547).",
        frontend_paths=("apps/frontend/src/app/frontend-version.json/",),
    ),
    _e2e(
        "test_journal_ui_journey.py",
        (NEEDS_STATE_SENSITIVE,),
        "Journal entry interactive browser UI journey (#2158).",
        frontend_paths=(
            "apps/frontend/src/app/(main)/journal/",
            "apps/frontend/src/components/journal/",
        ),
    ),
    _e2e(
        "test_reconciliation_ui_journey.py",
        (NEEDS_STATE_SENSITIVE,),
        "Reconciliation workbench and unmatched studio interactive journey (#2158, #2171).",
        frontend_paths=(
            "apps/frontend/src/app/(main)/reconciliation/",
            "apps/frontend/src/components/reconciliation/",
            "apps/frontend/src/components/review/Stage2ReviewQueue.tsx",
        ),
    ),
    _e2e(
        "test_accounts_and_statements_ui_journey.py",
        (NEEDS_STATE_SENSITIVE,),
        "Accounts and statements interactive browser UI journey (#2171).",
        frontend_paths=(
            "apps/frontend/src/app/(main)/settings/",
            "apps/frontend/src/app/(main)/statements/",
            "apps/frontend/src/components/settings/",
            "apps/frontend/src/components/accounts/",
            "apps/frontend/src/components/statements/",
            "apps/frontend/src/components/review/StatementReview.tsx",
        ),
    ),
)

STAGING_CORE_E2E_STAGE = "staging_core_e2e"
STAGING_CORE_E2E_MARKER = "(smoke or e2e) and not llm"
STAGING_CORE_E2E_PARALLELISM = 4

PREVIEW_MINIMUM_E2E_STAGE = "preview_minimum_e2e"
PREVIEW_MINIMUM_E2E_MARKER = STAGING_CORE_E2E_MARKER

STAGING_AI_OCR_STAGE = "staging_ai_ocr"

_CORE_E2E_ENV = {
    "RUN_MARKET_DATA_PROVIDER_E2E": "true",
    "MARKET_DATA_E2E_DATE": "2024-06-03",
}
STAGE_ENV: dict[str, dict[str, str]] = {
    PREVIEW_MINIMUM_E2E_STAGE: _CORE_E2E_ENV,
    STAGING_CORE_E2E_STAGE: _CORE_E2E_ENV,
    STAGING_AI_OCR_STAGE: {},
}


def stage_env(stage: str) -> dict[str, str]:
    """Return a copy of the env defaults of a selection stage."""
    return dict(STAGE_ENV[stage])


def staging_core_e2e_selection() -> tuple[str, ...]:
    """Derive the Staging Batch non-LLM E2E set from E2E_ROWS."""
    return tuple(
        node
        for row in E2E_ROWS
        if row.staging_core_e2e
        for node in (row.nodes or (row.file,))
    )


def preview_minimum_e2e_selection() -> tuple[str, ...]:
    """Derive the Preview minimum non-LLM E2E set from E2E_ROWS."""
    return staging_core_e2e_selection()


def _matches_frontend_path(changed_path: str, rule_path: str) -> bool:
    norm_rule = rule_path.rstrip("/")
    return changed_path == norm_rule or changed_path.startswith(f"{norm_rule}/")


def select_touched_e2e(changed_files: Sequence[str]) -> list[str]:
    """Map changed repo-relative paths to affected non-LLM staging_core_e2e journeys (#2670)."""
    eligible_rows = [row for row in E2E_ROWS if row.staging_core_e2e]
    eligible_by_file = {row.file: row for row in eligible_rows}
    all_e2e_spec_files = {row.file for row in E2E_ROWS}

    selected_files: set[str] = set()
    for raw_path in changed_files:
        path = raw_path.strip().replace("\\", "/").lstrip("./")
        if not path:
            continue
        if path in eligible_by_file:
            selected_files.add(path)
        elif path.startswith("tests/e2e/"):
            if path not in all_e2e_spec_files:
                return list(staging_core_e2e_selection())
        else:
            for row in eligible_rows:
                if any(_matches_frontend_path(path, fp) for fp in row.frontend_paths):
                    selected_files.add(row.file)

    return [
        node
        for row in eligible_rows
        if row.file in selected_files
        for node in (row.nodes or (row.file,))
    ]


def touched_e2e_selection(changed_files: Sequence[str]) -> tuple[tuple[str, ...], str]:
    """Return (nodes, marker) of the touched non-LLM E2E journeys (#2670)."""
    return tuple(select_touched_e2e(changed_files)), STAGING_CORE_E2E_MARKER


def emit_touched_e2e_shell(changed_files: Sequence[str]) -> str:
    """Emit bash assignments for touched non-LLM E2E journeys (#2670)."""
    nodes, marker = touched_e2e_selection(changed_files)
    tests = " ".join(shlex.quote(node) for node in nodes)
    return "\n".join(
        [
            f"TOUCHED_E2E_TESTS=({tests})",
            f"TOUCHED_E2E_MARKER={shlex.quote(marker)}",
            f"TOUCHED_E2E_COUNT={len(nodes)}",
        ]
    )


def staging_ai_ocr_selection(corpus: str = "all") -> tuple[str, ...]:
    """Derive the Staging AI/OCR E2E set for ``corpus`` from the replay contract."""
    from common.testing import staging_ai_ocr_gate_contract

    return tuple(staging_ai_ocr_gate_contract.corpus_files(corpus))


SELECTIONS = {
    PREVIEW_MINIMUM_E2E_STAGE: preview_minimum_e2e_selection,
    STAGING_CORE_E2E_STAGE: staging_core_e2e_selection,
    STAGING_AI_OCR_STAGE: staging_ai_ocr_selection,
}


def stage_selection(stage: str, *, corpus: str = "all") -> tuple[tuple[str, ...], str]:
    """Return (nodes, marker) for emit_shell and --run."""
    if stage == PREVIEW_MINIMUM_E2E_STAGE:
        nodes, marker = preview_minimum_e2e_selection(), PREVIEW_MINIMUM_E2E_MARKER
    elif stage == STAGING_CORE_E2E_STAGE:
        nodes, marker = staging_core_e2e_selection(), STAGING_CORE_E2E_MARKER
    elif stage == STAGING_AI_OCR_STAGE:
        nodes, marker = staging_ai_ocr_selection(corpus), STAGING_AI_OCR_GATE_MARKER
    else:
        raise ValueError(
            f"unknown selection stage {stage!r}; known: {', '.join(sorted(SELECTIONS))}"
        )
    if not nodes:
        raise ValueError(f"selection stage {stage!r} produced an empty test tuple")
    return tuple(nodes), marker


def emit_shell(stage: str, *, corpus: str = "all") -> str:
    """Emit bash assignments for a stage's selection."""
    nodes, marker = stage_selection(stage, corpus=corpus)
    tests = " ".join(shlex.quote(node) for node in nodes)
    quoted_marker = shlex.quote(marker)
    if stage == PREVIEW_MINIMUM_E2E_STAGE:
        return (
            f"PREVIEW_MINIMUM_E2E_TESTS=({tests})\n"
            f"PREVIEW_MINIMUM_E2E_MARKER={quoted_marker}"
        )
    if stage == STAGING_CORE_E2E_STAGE:
        return (
            f"STAGING_CORE_E2E_TESTS=({tests})\n"
            f"STAGING_CORE_E2E_MARKER={quoted_marker}\n"
            f"STAGING_CORE_E2E_PARALLELISM={STAGING_CORE_E2E_PARALLELISM}"
        )
    from common.testing import staging_ai_ocr_gate_contract

    return (
        f"{staging_ai_ocr_gate_contract.emit_shell(list(nodes))}\n"
        f"STAGING_AI_OCR_MARKER={quoted_marker}"
    )


BACKEND_CI_MARKER = "not slow and not e2e and not integration"
BACKEND_INTEGRATION_MARKER = "integration"
BACKEND_TIER1_MARKER = "e2e and not slow and not integration and not perf"
STAGING_AI_OCR_MARKER = "llm"
STAGING_AI_OCR_GATE_MARKER = "llm or journey"
STAGING_VERSION_CHECK_MARKER = "smoke"
PRODUCTION_READONLY_MARKER = "prod_safe"


@dataclass(frozen=True)
class WorkflowPytestContract:
    """One expected pytest invocation inside a GitHub workflow."""

    stage: str
    workflow: str
    marker: str | None
    paths: tuple[str, ...] = ()
    anchor: str = ""
    precondition: str = ""


WORKFLOW_PYTEST_CONTRACTS: tuple[WorkflowPytestContract, ...] = (
    WorkflowPytestContract(
        stage="backend_ci",
        workflow=".github/workflows/ci.yml",
        marker=BACKEND_CI_MARKER,
        paths=('"${BACKEND_SHARD_TESTS[@]}"',),
        anchor="--junit-xml=test-results/backend-shard-${{ matrix.shard }}.xml",
    ),
    WorkflowPytestContract(
        stage="backend_integration",
        workflow=".github/workflows/ci.yml",
        marker=BACKEND_INTEGRATION_MARKER,
        anchor="--junit-xml=test-results/backend-integration.xml",
    ),
    WorkflowPytestContract(
        stage="tooling_ci",
        workflow=".github/workflows/ci.yml",
        marker=None,
        paths=("tests/tooling/",),
        anchor="--junit-xml=coverage/tooling-junit-${{ matrix.shard }}.xml",
    ),
    WorkflowPytestContract(
        stage="preview_minimum_e2e",
        workflow="runtime-hooks.manifest.json",
        marker=PREVIEW_MINIMUM_E2E_MARKER,
        paths=("--stage preview_minimum_e2e",),
        anchor="tools/test_selection.py --stage preview_minimum_e2e --run",
    ),
    WorkflowPytestContract(
        stage="preview_touched_e2e",
        workflow="runtime-hooks.manifest.json",
        marker=STAGING_CORE_E2E_MARKER,
        paths=("--touched-files",),
        anchor="tools/test_selection.py --touched-files",
    ),
    WorkflowPytestContract(
        stage="staging_core_e2e",
        workflow="runtime-hooks.manifest.json",
        marker=STAGING_CORE_E2E_MARKER,
        paths=("--stage staging_core_e2e",),
        anchor="tools/test_selection.py --stage staging_core_e2e --run",
        precondition="tools/smoke_test.sh",
    ),
    WorkflowPytestContract(
        stage="staging_provider_connectivity",
        workflow="runtime-hooks.manifest.json",
        marker=None,
        paths=("tests/e2e/test_ai_provider_connectivity.py",),
        anchor="tests/e2e/test_ai_provider_connectivity.py",
    ),
    WorkflowPytestContract(
        stage="staging_ai_ocr_gate",
        workflow="runtime-hooks.manifest.json",
        marker=STAGING_AI_OCR_GATE_MARKER,
        paths=("--stage staging_ai_ocr", "--corpus canary"),
        anchor="tools/test_selection.py --stage staging_ai_ocr --corpus canary --run",
    ),
    WorkflowPytestContract(
        stage="scheduled_audit_ocr_gate",
        workflow="runtime-hooks.manifest.json",
        marker=STAGING_AI_OCR_GATE_MARKER,
        paths=("--stage staging_ai_ocr", "--corpus audit_replay"),
        anchor="tools/test_selection.py --stage staging_ai_ocr --corpus audit_replay --run",
    ),
    WorkflowPytestContract(
        stage="scheduled_audit_core_journey_gate",
        workflow="runtime-hooks.manifest.json",
        marker=STAGING_AI_OCR_GATE_MARKER,
        paths=("--stage staging_ai_ocr", "--corpus core_journey"),
        anchor="tools/test_selection.py --stage staging_ai_ocr --corpus core_journey --run",
    ),
)

PR_EVIDENCE_STAGES: frozenset[str] = frozenset(
    {"backend_ci", "backend_integration", "frontend_vitest"}
)
