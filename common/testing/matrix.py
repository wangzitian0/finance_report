"""Test execution matrix as code — the SSOT for test placement and selection."""

from __future__ import annotations

import json
import shlex
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


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
    PathRule("tests/e2e/", "deployment_e2e", True),
)


def classify_stage(path: str) -> str | None:
    """Return the execution stage for a repo-relative test path (first match)."""
    return next((rule.stage for rule in PATH_RULES if path.startswith(rule.path)), None)


GENERATED_MATRIX_HEADER = (
    "# GENERATED from common/testing/matrix.py — do not hand-edit.\n"
    "# Regenerate: python -m common.testing.test_selection --emit-matrix\n"
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
            "apps/frontend/src/components/pricing/PriceUpdateForm.tsx",
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
        reason="API-only GET /api/health comparing git_sha with APP_VERSION_REF (#1547).",
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
        ),
    ),
)

STAGING_CORE_E2E_STAGE = "staging_core_e2e"
STAGING_CORE_E2E_MARKER = "(smoke or e2e) and not llm"
STAGING_CORE_E2E_PARALLELISM = 4
"""pytest-xdist worker count of the core E2E stages; journeys share no data, and each worker has its own session user (#3241)."""

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


STAGE_PARALLELISM: dict[str, int] = {
    PREVIEW_MINIMUM_E2E_STAGE: STAGING_CORE_E2E_PARALLELISM,
    STAGING_CORE_E2E_STAGE: STAGING_CORE_E2E_PARALLELISM,
}


def stage_parallelism(stage: str) -> int:
    """Return the pytest-xdist worker count of a stage; 1 means one process."""
    return STAGE_PARALLELISM.get(stage, 1)


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


SUPPLEMENTAL_LLM_FILES = ["tests/e2e/test_statement_upload_e2e.py"]
CANARY_FILES = ["tests/e2e/test_brokerage_upload_to_portfolio_value.py"]
CORE_JOURNEY_MAP_PATH = REPO_ROOT / "common/testing/data/core-journey-checkpoints.json"
CORE_JOURNEY_LAST = ("tests/e2e/test_twelve_month_journey.py",)
_CONNECTIVITY_FILE = "tests/e2e/test_ai_provider_connectivity.py"


def gate_files() -> list[str]:
    """Return the derived Staging AI/OCR E2E file corpus."""
    proof_files = {
        row.file
        for row in E2E_ROWS
        if NEEDS_LLM_PROVIDER in row.needs and row.file != _CONNECTIVITY_FILE
    }
    return sorted(proof_files | set(SUPPLEMENTAL_LLM_FILES))


def canary_files() -> list[str]:
    """Return the minimal blocking-path AI/OCR canary corpus."""
    derived = set(gate_files())
    canary = sorted(CANARY_FILES)
    missing_from_corpus = [path for path in canary if path not in derived]
    if missing_from_corpus:
        raise SystemExit(
            "Canary files are not in the derived AI/OCR corpus: "
            + ", ".join(sorted(missing_from_corpus))
        )
    return canary


def audit_replay_files() -> list[str]:
    """Return the nightly/manual audit-replay corpus."""
    canary = set(canary_files())
    return [path for path in gate_files() if path not in canary]


def core_journey_tests() -> list[str]:
    """Return the non-LLM core-journey corpus, excluding audit-replay files."""
    data = json.loads(CORE_JOURNEY_MAP_PATH.read_text(encoding="utf-8"))
    replay = set(audit_replay_files())
    return sorted(
        (
            f"{proof['file']}::{proof['test'].split('::', 1)[1]}"
            for proof in data["proofs"]
            if proof["file"] not in replay
        ),
        key=lambda node: (node.split("::", 1)[0] in CORE_JOURNEY_LAST, node),
    )


def corpus_files(corpus: str) -> list[str]:
    selectors = {
        "all": gate_files,
        "canary": canary_files,
        "audit_replay": audit_replay_files,
        "core_journey": core_journey_tests,
    }
    if corpus not in selectors:
        raise SystemExit(
            f"Unknown corpus {corpus!r}; expected one of {sorted(selectors)}"
        )
    return selectors[corpus]()


def staging_ai_ocr_selection(corpus: str = "all") -> tuple[str, ...]:
    """Derive the Staging AI/OCR E2E set for ``corpus`` from the replay contract."""
    return tuple(corpus_files(corpus))


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
    return f"STAGING_AI_OCR_TESTS=({tests})\nSTAGING_AI_OCR_MARKER={quoted_marker}"


STAGING_AI_OCR_GATE_MARKER = "llm or journey"

PR_EVIDENCE_STAGES: frozenset[str] = frozenset(
    {"backend_ci", "backend_integration", "frontend_vitest"}
)
