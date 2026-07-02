"""Test execution matrix as code — the SSOT for test placement and selection.

This module is the single owner of two orthogonal facts (EPIC-008 AC8.22,
issue #1556):

1. **Path → stage classification** (``PATH_RULES``): which execution stage a
   test path belongs to and whether that stage is CI-required. The checked-in
   ``docs/ssot/test-execution-matrix.yaml`` is a *generated view* of these
   rules (``emit_execution_matrix_yaml``); a tooling contract test fails when
   the two drift. Consumers (``common/ssot/check_ac_traceability.py``) keep
   reading the generated YAML, so AC-traceability behavior is unchanged.

2. **E2E ownership rows** (``E2E_ROWS``): every root E2E spec gets a named row
   declaring what it *needs* beyond the ephemeral in-runner preview stack and
   whether it has been explicitly audited as safe to run pre-merge. The PR
   preview in-runner selection is **derived** from these rows instead of a
   hand-maintained whitelist in ``preview.yml`` (issue #1547): a row enters
   the pre-merge set only when it is audited AND needs nothing the in-runner
   stack cannot provide. An unaudited or dependent row defaults to the
   post-merge staging ladder — new heavy specs can never silently creep into
   the merge-blocking path (same property as the AI/OCR canary rule,
   AC8.13.159).

Workflows consume the selection at runtime through
``tools/test_selection.py --stage pr_preview_e2e --shell`` (same pattern as
``tools/staging_ai_ocr_gate_contract.py --shell``), so the workflow never
restates the list. Charter: ``common/testing/README.md``.
"""

from __future__ import annotations

import shlex
from dataclasses import dataclass

# ---------------------------------------------------------------------------
# Path → stage classification (source of docs/ssot/test-execution-matrix.yaml)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PathRule:
    """One path-prefix → execution-stage classification rule."""

    path: str
    stage: str
    ci_required: bool


# Order matters: the first (most specific) match wins, mirroring the
# longest-prefix semantics in common/ssot/check_ac_traceability.py.
PATH_RULES: tuple[PathRule, ...] = (
    PathRule(
        "apps/backend/tests/e2e/test_auth_flows.py", "backend_ui_e2e_local", False
    ),
    PathRule("apps/backend/tests/e2e/test_e2e_flows.py", "backend_ui_e2e_local", False),
    PathRule(
        "apps/backend/tests/e2e/test_core_journeys.py", "backend_tier1_api_e2e", True
    ),
    PathRule("apps/backend/tests/", "backend_ci", True),
    PathRule(
        "apps/frontend/playwright/inline-edit-happy-path.spec.ts",
        "frontend_playwright_env_gated",
        False,
    ),
    PathRule("apps/frontend/playwright/", "frontend_playwright_ci", True),
    PathRule("apps/frontend/src/", "frontend_vitest", True),
    PathRule("tests/tooling/", "tooling_ci", True),
    PathRule("tools/tier2_http_e2e.py", "deployment_tier2_http_e2e", False),
    PathRule("tests/e2e/", "deployment_e2e", True),
)

GENERATED_MATRIX_HEADER = (
    "# GENERATED from common/testing/matrix.py — do not hand-edit.\n"
    "# Regenerate: python tools/test_selection.py --emit-matrix\n"
    "# Drift gate: tests/tooling/test_execution_matrix_contract.py (AC8.22.1)\n"
)


def emit_execution_matrix_yaml() -> str:
    """Render the generated docs/ssot/test-execution-matrix.yaml content.

    Built by hand (no PyYAML) so the output is byte-deterministic and the
    runtime selection path stays stdlib-only.
    """
    lines = [GENERATED_MATRIX_HEADER + "version: 1", "rules:"]
    for rule in PATH_RULES:
        lines.append(f"  - path: {rule.path}")
        lines.append(f"    stage: {rule.stage}")
        lines.append(f"    ci_required: {'true' if rule.ci_required else 'false'}")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# E2E ownership rows (testing extension layer)
# ---------------------------------------------------------------------------

# Dependency classes an E2E spec may need beyond the ephemeral in-runner
# stack. These are the *real* exclusion criteria already stated in
# docs/ssot/ci-cd.md (provider quota, staging-only secrets/providers,
# state-sensitivity) — not a hand-picked file list.
NEEDS_LLM_PROVIDER = "llm_provider"  # spends real AI/OCR quota (llm marker)
NEEDS_MARKET_DATA = "market_data"  # calls a real market-data provider
NEEDS_DEPLOYED_ENV = "deployed_env"  # probes a persistent deployed environment
NEEDS_STATE_SENSITIVE = "state_sensitive"  # mutates registration/auth state


@dataclass(frozen=True)
class E2ERow:
    """Named ownership row for one root E2E spec file.

    ``audited=True`` means the file was explicitly reviewed as safe for the
    in-runner preview stack; ``needs`` lists external dependencies the
    in-runner stack cannot provide. Selection requires audited AND no needs.
    ``nodes`` optionally narrows selection to explicit pytest node ids.
    """

    file: str
    needs: tuple[str, ...]
    audited: bool
    reason: str
    nodes: tuple[str, ...] = ()


E2E_ROWS: tuple[E2ERow, ...] = (
    E2ERow(
        "tests/e2e/test_core_journeys.py",
        needs=(),
        audited=True,
        reason="Fixture-seeded core journeys; original in-runner preview set.",
    ),
    E2ERow(
        "tests/e2e/test_e2e_flows.py",
        needs=(),
        audited=True,
        nodes=("tests/e2e/test_e2e_flows.py::test_full_navigation",),
        reason="Only full-navigation is audited for in-runner; remaining nodes pending audit.",
    ),
    E2ERow(
        "tests/e2e/test_vision_upload_to_dashboard_hard_gate.py",
        needs=(),
        audited=True,
        reason=(
            "#1547: CSV-kind upload only — no AI/OCR provider call, no market-data, "
            "no Vault-only secret; uses the same authenticated_page_unique fixture "
            "as the core journeys."
        ),
    ),
    E2ERow(
        "tests/e2e/test_brokerage_upload_to_portfolio_value.py",
        needs=(NEEDS_LLM_PROVIDER,),
        audited=True,
        reason="Real AI/OCR provider (llm marker); staging canary corpus.",
    ),
    E2ERow(
        "tests/e2e/test_four_asset_net_worth_golden_path.py",
        needs=(NEEDS_LLM_PROVIDER,),
        audited=True,
        reason="Real AI/OCR provider (llm marker); audit-replay corpus.",
    ),
    E2ERow(
        "tests/e2e/test_personal_financial_report_package.py",
        needs=(NEEDS_LLM_PROVIDER,),
        audited=True,
        reason="Real AI/OCR provider (llm marker); audit-replay corpus.",
    ),
    E2ERow(
        "tests/e2e/test_statement_full_journey.py",
        needs=(NEEDS_LLM_PROVIDER,),
        audited=True,
        reason="Real AI/OCR provider (llm marker); audit-replay corpus.",
    ),
    E2ERow(
        "tests/e2e/test_statement_upload_e2e.py",
        needs=(NEEDS_LLM_PROVIDER,),
        audited=True,
        reason="Real AI/OCR provider (llm marker); supplemental staging corpus.",
    ),
    E2ERow(
        "tests/e2e/test_ai_provider_connectivity.py",
        needs=(NEEDS_LLM_PROVIDER,),
        audited=True,
        reason="Real provider connectivity probe (llm marker); staging provider gate.",
    ),
    E2ERow(
        "tests/e2e/test_market_data_price_paths.py",
        needs=(NEEDS_MARKET_DATA,),
        audited=True,
        reason="Calls the real market-data provider; staging responsibility.",
    ),
    E2ERow(
        "tests/e2e/test_production_readonly_smoke.py",
        needs=(NEEDS_DEPLOYED_ENV,),
        audited=True,
        reason="prod_safe read-only probe of a persistent deployed environment.",
    ),
    E2ERow(
        "tests/e2e/test_frontend_observability_epic024.py",
        needs=(NEEDS_DEPLOYED_ENV,),
        audited=True,
        reason="Probes deployed telemetry wiring (prod_safe smoke).",
    ),
    E2ERow(
        "tests/e2e/test_auth_flows.py",
        needs=(NEEDS_STATE_SENSITIVE,),
        audited=True,
        reason="Registration/auth state-sensitive workflow; staging responsibility per ci-cd.md.",
    ),
    E2ERow(
        "tests/e2e/test_version_check.py",
        needs=(),
        audited=False,
        reason="Pending audit (#1547 follow-up): asserts deployed sha vs expected release.",
    ),
    E2ERow(
        "tests/e2e/test_ac_authority_tiers_epic026.py",
        needs=(),
        audited=False,
        reason="Pending audit (#1547 follow-up).",
    ),
    E2ERow(
        "tests/e2e/test_application_ai_advisor_epic021.py",
        needs=(),
        audited=False,
        reason="Pending audit (#1547 follow-up): advisor flow may exercise a live LLM path.",
    ),
    E2ERow(
        "tests/e2e/test_llm_provider_abstraction_epic023.py",
        needs=(),
        audited=False,
        reason="Pending audit (#1547 follow-up).",
    ),
)


# ---------------------------------------------------------------------------
# Per-stage selection (consumed by workflows via tools/test_selection.py)
# ---------------------------------------------------------------------------

PR_PREVIEW_E2E_STAGE = "pr_preview_e2e"
PR_PREVIEW_E2E_MARKER = "(smoke or e2e) and not llm"
PR_PREVIEW_E2E_PARALLELISM = 4


def pr_preview_e2e_selection() -> tuple[str, ...]:
    """Derive the pre-merge in-runner E2E set from the ownership rows.

    A row is selected only when it is audited AND needs nothing beyond the
    in-runner stack. Everything else stays on the post-merge ladder.
    """
    nodes: list[str] = []
    for row in E2E_ROWS:
        if row.audited and not row.needs:
            nodes.extend(row.nodes or (row.file,))
    return tuple(nodes)


SELECTIONS = {
    PR_PREVIEW_E2E_STAGE: pr_preview_e2e_selection,
}


def emit_shell(stage: str) -> str:
    """Emit bash assignments for a stage's selection (eval'd by workflows)."""
    if stage != PR_PREVIEW_E2E_STAGE:
        known = ", ".join(sorted(SELECTIONS))
        raise ValueError(f"unknown selection stage {stage!r}; known: {known}")
    tests = " ".join(shlex.quote(node) for node in pr_preview_e2e_selection())
    return "\n".join(
        [
            f"PR_PREVIEW_E2E_TESTS=({tests})",
            f"PR_PREVIEW_E2E_MARKER={shlex.quote(PR_PREVIEW_E2E_MARKER)}",
            f"PR_PREVIEW_E2E_PARALLELISM={PR_PREVIEW_E2E_PARALLELISM}",
        ]
    )
