"""Test execution matrix as code — the SSOT for test placement and selection.

This module is the single owner of two orthogonal facts (EPIC-008 AC8.22,
issue #1556):

1. **Path → stage classification** (``PATH_RULES``): which execution stage a
   test path belongs to and whether that stage is CI-required. The checked-in
   ``common/testing/data/test-execution-matrix.yaml`` is a *generated view* of these
   rules (``emit_execution_matrix_yaml``); a tooling contract test fails when
   the two drift. Consumers (``common/testing/check_ac_traceability.py``) keep
   reading the generated YAML, so AC-traceability behavior is unchanged.

2. **E2E ownership rows** (``E2E_ROWS``): every root E2E spec gets a named row
   declaring what it *needs* beyond the ephemeral stack and whether it has been
   explicitly audited. The Staging Batch non-LLM core E2E selection is
   **derived** from these rows instead of a hand-maintained list (issue #1547):
   a row enters the staging core set only when it is audited, does not require
   a live LLM provider, and is not exclusive to the core journey lane. An
   unaudited or dependent row defaults to the specialized gates.

Workflows consume the selection at runtime through
``tools/test_selection.py --stage staging_core_e2e --shell`` (same pattern as
``tools/staging_ai_ocr_gate_contract.py --shell``), so the workflow never
restates the list. Charter: ``common/testing/readme.md``.
"""

from __future__ import annotations

import shlex
from dataclasses import dataclass

# ---------------------------------------------------------------------------
# Path → stage classification (source of common/testing/data/test-execution-matrix.yaml)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PathRule:
    """One path-prefix → execution-stage classification rule."""

    path: str
    stage: str
    ci_required: bool


# Order matters: the first (most specific) match wins, mirroring the
# longest-prefix semantics in common/testing/check_ac_traceability.py.
PATH_RULES: tuple[PathRule, ...] = (
    PathRule(
        "apps/backend/tests/e2e/test_statement_corpus_journeys.py",
        "backend_integration",
        True,
    ),
    PathRule(
        "apps/backend/tests/e2e/test_epic025_dry_ssot_e2e.py",
        "backend_integration",
        True,
    ),
    PathRule("apps/backend/tests/", "backend_ci", True),
    PathRule("apps/frontend/playwright/", "frontend_playwright_ci", True),
    PathRule("apps/frontend/src/", "frontend_vitest", True),
    PathRule("tests/tooling/", "tooling_ci", True),
    PathRule("tools/tier2_http_e2e.py", "deployment_tier2_http_e2e", False),
    PathRule("tests/e2e/", "deployment_e2e", True),
)


def classify_stage(path: str) -> str | None:
    """Return the execution stage for a repo-relative test path (first match)."""
    for rule in PATH_RULES:
        if path.startswith(rule.path):
            return rule.stage
    return None


# ---------------------------------------------------------------------------
# Package test-root declarations (issue #1558): each domain package declares
# the test roots it owns via a module-level TEST_ROOTS tuple in its
# contract.py; the matrix aggregates them into the generated YAML's
# `ownership:` section. Removing a declaration changes the generated view and
# fails the --check-matrix drift gate. Seed rollout: three packages.
# ---------------------------------------------------------------------------

PACKAGE_TEST_DECLARATIONS: tuple[str, ...] = ("runtime", "ledger", "testing")


def package_test_ownership() -> dict[str, str]:
    """Aggregate declared test roots → owning package (lazy imports so the
    runtime selection path stays stdlib-only)."""
    import importlib

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
                f"package {pkg!r}: TEST_ROOTS must be a tuple of paths, "
                "not a bare string"
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
    """Render the generated common/testing/data/test-execution-matrix.yaml content.

    Built by hand (no PyYAML) so the output is byte-deterministic and the
    runtime selection path stays stdlib-only.
    """
    lines = [GENERATED_MATRIX_HEADER + "version: 1", "rules:"]
    for rule in PATH_RULES:
        lines.append(f"  - path: {rule.path}")
        lines.append(f"    stage: {rule.stage}")
        lines.append(f"    ci_required: {'true' if rule.ci_required else 'false'}")
    # Package-declared test ownership (issue #1558). Consumers of `rules:`
    # (AC traceability) ignore this section; it exists so a dropped or
    # duplicated declaration is a visible generated-view change.
    lines.append("ownership:")
    for root, pkg in sorted(package_test_ownership().items()):
        lines.append(f"  - path: {root}")
        lines.append(f"    package: {pkg}")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# E2E ownership rows (testing extension layer)
# ---------------------------------------------------------------------------

# Dependency classes an E2E spec may need beyond the ephemeral in-runner
# stack. These are the *real* exclusion criteria already stated in
# common/runtime/ci-cd.md (provider quota, staging-only secrets/providers,
# state-sensitivity) — not a hand-picked file list.
NEEDS_LLM_PROVIDER = "llm_provider"  # spends real AI/OCR quota (llm marker)
NEEDS_MARKET_DATA = "market_data"  # calls a real market-data provider
NEEDS_DEPLOYED_ENV = "deployed_env"  # probes a persistent deployed environment
NEEDS_STATE_SENSITIVE = "state_sensitive"  # mutates registration/auth state

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
    """Named ownership row for one root E2E spec file.

    ``audited=True`` means the file was explicitly reviewed as safe for the
    staging core stack; ``needs`` lists external dependencies. Selection
    requires audited AND no LLM provider AND not in CORE_JOURNEY_ONLY_FILES.
    ``nodes`` optionally narrows selection to explicit pytest node ids.
    """

    file: str
    needs: tuple[str, ...]
    audited: bool
    reason: str
    nodes: tuple[str, ...] = ()

    @property
    def staging_core_e2e(self) -> bool:
        """Selected by the Staging Batch non-LLM core E2E gate."""
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
            "staging_core_e2e": self.staging_core_e2e,
        }


E2E_ROWS: tuple[E2ERow, ...] = (
    E2ERow(
        "tests/e2e/test_epic022_ia_shell.py",
        needs=(),
        audited=True,
        reason=(
            "EPIC-022 everyday-user shell proof, relocated from the dead "
            "apps/backend/tests/e2e copy (backend_ci marker deselected it); "
            "authenticated browser + frontend shell only, no provider."
        ),
    ),
    E2ERow(
        "tests/e2e/test_vision_upload_to_dashboard_hard_gate.py",
        needs=(),
        audited=True,
        reason=(
            "#1547 lineage: no provider/market/Vault dependency. Two in-runner "
            "stack bugs were flushed out on the way in: the double-/api "
            "NEXT_PUBLIC_API_URL 404 (PR #1587) and the #1589 click timeout — "
            "the app-wide FirstRunModal ('Set up your AI provider') opened on "
            "every full navigation because the stack had no provider wiring, "
            "intercepting pointer events over the upload button; fixed with "
            "placeholder provider wiring + an unroutable AI_BASE_URL "
            "(validates wiring, cannot spend quota)."
        ),
    ),
    E2ERow(
        "tests/e2e/test_brokerage_upload_to_portfolio_value.py",
        needs=(NEEDS_LLM_PROVIDER,),
        audited=True,
        reason="Real AI/OCR provider (llm marker); staging canary corpus.",
    ),
    E2ERow(
        "tests/e2e/test_transfer_processing_journey.py",
        needs=(NEEDS_DEPLOYED_ENV,),
        audited=True,
        reason=(
            "Core-journey board proof U7 (#2384): runs only in the post-deploy "
            "core_journey lane against a pinned staging revision (#2370)."
        ),
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
        "tests/e2e/test_gxs_browser_journey.py",
        needs=(NEEDS_LLM_PROVIDER,),
        audited=True,
        reason="Real provider fresh-user browser upload/review/saved-package proof; audit replay only.",
    ),
    E2ERow(
        "tests/e2e/test_opening_balance_browser_journey.py",
        needs=(NEEDS_DEPLOYED_ENV,),
        audited=True,
        reason=(
            "Core-journey board proof U5 (#2383): runs only in the post-deploy "
            "core_journey lane against a pinned staging revision (#2370)."
        ),
    ),
    E2ERow(
        "tests/e2e/test_twelve_month_journey.py",
        needs=(NEEDS_DEPLOYED_ENV,),
        audited=True,
        reason=(
            "Core-journey board proof U9 (#2370): runs only in the post-deploy "
            "core_journey lane against a pinned staging revision."
        ),
    ),
    E2ERow(
        "tests/e2e/test_confidence_metrics_journey.py",
        needs=(NEEDS_DEPLOYED_ENV,),
        audited=True,
        reason=(
            "Core-journey board proof U13 (#2370): runs only in the post-deploy "
            "core_journey lane against a pinned staging revision."
        ),
    ),
    E2ERow(
        "tests/e2e/test_stage1_routing_journey.py",
        needs=(NEEDS_LLM_PROVIDER,),
        audited=True,
        reason="Real provider Stage 1 routing proof U3 (#2392); audit replay and core-journey lane.",
    ),
    E2ERow(
        "tests/e2e/test_zero_click_statement_journey.py",
        needs=(NEEDS_LLM_PROVIDER,),
        audited=True,
        reason="Real provider zero-click proof (#2405): an upload alone posts every row and the three statements tie.",
    ),
    E2ERow(
        "tests/e2e/test_assistant_chat_journey.py",
        needs=(NEEDS_LLM_PROVIDER,),
        audited=True,
        reason=(
            "Core-journey proof U14 (#2461): the live assistant answers with the report amounts; "
            "audit replay and core-journey lane."
        ),
    ),
    E2ERow(
        "tests/e2e/test_institution_statement_journeys.py",
        needs=(NEEDS_LLM_PROVIDER,),
        audited=True,
        reason=(
            "Real AI/OCR provider (llm marker); per-institution statement "
            "shapes (cmb/mari/pingan/gxs) in the audit-replay corpus (#1613)."
        ),
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
        audited=True,
        reason=(
            "Audited (#1547 follow-up): API-only GET /api/health comparing git_sha "
            "with EXPECTED_SHA — both provided by the in-runner stack (GIT_COMMIT_SHA "
            "baked into images, EXPECTED_SHA set by the preview job)."
        ),
    ),
    E2ERow(
        "tests/e2e/test_journal_ui_journey.py",
        needs=(NEEDS_STATE_SENSITIVE,),
        audited=True,
        reason=(
            "Audited (#2158): Journal entry interactive browser UI journey; "
            "verifies form validation, debit/credit balance, and immediate posting."
        ),
    ),
    E2ERow(
        "tests/e2e/test_reconciliation_ui_journey.py",
        needs=(NEEDS_STATE_SENSITIVE,),
        audited=True,
        reason=(
            "Audited (#2158, #2171): Reconciliation workbench and unmatched studio interactive journey; "
            "verifies workbench KPI surface, unmatched studio, and interactive disposition drawer posting."
        ),
    ),
    E2ERow(
        "tests/e2e/test_accounts_and_statements_ui_journey.py",
        needs=(NEEDS_STATE_SENSITIVE,),
        audited=True,
        reason=(
            "Audited (#2171): Accounts and statements interactive browser UI journey; "
            "verifies account list, filter tabs, statement details, and review surface."
        ),
    ),
)


# ---------------------------------------------------------------------------
# Per-stage selection (consumed by workflows via tools/test_selection.py)
# ---------------------------------------------------------------------------

STAGING_CORE_E2E_STAGE = "staging_core_e2e"
STAGING_CORE_E2E_MARKER = "(smoke or e2e) and not llm"
STAGING_CORE_E2E_PARALLELISM = 4


def staging_core_e2e_selection() -> tuple[str, ...]:
    """Derive the Staging Batch non-LLM E2E set from E2E_ROWS."""
    nodes: list[str] = []
    for row in E2E_ROWS:
        if row.staging_core_e2e:
            nodes.extend(row.nodes or (row.file,))
    return tuple(nodes)


SELECTIONS = {
    STAGING_CORE_E2E_STAGE: staging_core_e2e_selection,
}


def emit_shell(stage: str) -> str:
    """Emit bash assignments for a stage's selection (eval'd by workflows)."""
    if stage == STAGING_CORE_E2E_STAGE:
        nodes = staging_core_e2e_selection()
        if not nodes:
            raise ValueError(f"selection stage {stage!r} produced an empty test tuple")
        tests = " ".join(shlex.quote(node) for node in nodes)
        return "\n".join(
            [
                f"STAGING_CORE_E2E_TESTS=({tests})",
                f"STAGING_CORE_E2E_MARKER={shlex.quote(STAGING_CORE_E2E_MARKER)}",
                f"STAGING_CORE_E2E_PARALLELISM={STAGING_CORE_E2E_PARALLELISM}",
            ]
        )
    known = ", ".join(sorted(SELECTIONS))
    raise ValueError(f"unknown selection stage {stage!r}; known: {known}")


# ---------------------------------------------------------------------------
# Workflow pytest contracts (issue #1557): every pytest invocation in
# .github/workflows/*.yml is registered here with its marker expression and
# explicit paths. tests/tooling/test_workflow_selection_conformance.py
# enforces this registry FAIL-CLOSED in both directions — an unregistered
# invocation in a workflow fails lint-tier CI, and a registered contract with
# no live invocation fails too (a gate cannot be dropped by editing only the
# workflow). Marker expressions live here ONCE; workflows keep the literal
# text and the conformance gate proves equality.
# ---------------------------------------------------------------------------

BACKEND_CI_MARKER = "not slow and not e2e and not integration"
BACKEND_INTEGRATION_MARKER = "integration"
BACKEND_TIER1_MARKER = "e2e and not slow and not integration and not perf"
STAGING_AI_OCR_MARKER = "llm"
# The AI/OCR gate also runs core-journey proofs that make no provider call
# (journey marker, #2370). The provider connectivity check stays "llm" only.
STAGING_AI_OCR_GATE_MARKER = "llm or journey"
STAGING_VERSION_CHECK_MARKER = "smoke"
PRODUCTION_READONLY_MARKER = "prod_safe"


@dataclass(frozen=True)
class WorkflowPytestContract:
    """One expected pytest invocation inside a GitHub workflow."""

    stage: str
    workflow: str
    # The exact `-m` expression the invocation must carry; None means the
    # marker is variable-driven (derived at runtime via tools/test_selection).
    marker: str | None
    # Explicit path/node arguments the invocation must carry (empty = none:
    # the job's cwd/addopts scope the run).
    paths: tuple[str, ...] = ()
    # Substring identifying this invocation's line uniquely in the workflow.
    anchor: str = ""
    # Environment precondition that must run BEFORE this invocation in the
    # same workflow (runtime package's domain: a red precondition is an
    # environment failure, not a test failure — issue #1558). Empty = none.
    precondition: str = ""


WORKFLOW_PYTEST_CONTRACTS: tuple[WorkflowPytestContract, ...] = (
    WorkflowPytestContract(
        stage="backend_ci",
        workflow=".github/workflows/ci.yml",
        marker=BACKEND_CI_MARKER,
        # Each shard runs exactly the files tools/backend_shard_files.py
        # assigns to it (a seeded file-level split, #2050), passed as one
        # shell array; the marker still deselects inside those files.
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
        # 2-way shard matrix (mirrors backend's `${{ matrix.shard }}` templating):
        # this literal source text (unexpanded by GitHub Actions) appears exactly
        # once in the one shard job block regardless of how many shards run.
        anchor="--junit-xml=coverage/tooling-junit-${{ matrix.shard }}.xml",
    ),
    WorkflowPytestContract(
        stage="staging_core_e2e",
        workflow=".github/workflows/deploy.yml",
        marker=None,  # runtime-derived: eval tools/test_selection.py --stage staging_core_e2e --shell
        paths=('"${STAGING_CORE_E2E_TESTS[@]}"',),
        anchor="--junit-xml=test-results/staging-core-e2e.xml",
        precondition="tools/smoke_test.sh",
    ),
    WorkflowPytestContract(
        stage="staging_provider_connectivity",
        workflow=".github/workflows/deploy.yml",
        marker=STAGING_AI_OCR_MARKER,
        paths=("tests/e2e/test_ai_provider_connectivity.py",),
        anchor="--junit-xml=test-results/staging-provider-connectivity.xml",
    ),
    WorkflowPytestContract(
        stage="staging_model_catalog_policy",
        workflow=".github/workflows/deploy.yml",
        marker=STAGING_AI_OCR_MARKER,
        paths=(
            "tests/e2e/test_ai_provider_connectivity.py::test_staging_catalog_serves_the_sdk_default_models",
        ),
        anchor="--junit-xml=test-results/staging-model-catalog-policy.xml",
    ),
    WorkflowPytestContract(
        stage="staging_ai_ocr_version_check",
        workflow=".github/workflows/staging-ai-ocr-gate.yml",
        marker=STAGING_VERSION_CHECK_MARKER,
        paths=("tests/e2e/test_version_check.py",),
        anchor="--junit-xml=test-results/staging-ai-ocr-version.xml",
    ),
    WorkflowPytestContract(
        stage="staging_ai_ocr_gate",
        workflow=".github/workflows/staging-ai-ocr-gate.yml",
        marker=STAGING_AI_OCR_GATE_MARKER,
        # Corpus is derived from @ac_proof metadata by
        # tools/staging_ai_ocr_gate_contract.py --shell (a view over the same
        # AC graph); the invocation consumes the emitted array.
        paths=('"${STAGING_AI_OCR_TESTS[@]}"',),
        anchor="--junit-xml=test-results/staging-ai-ocr-gate.xml",
    ),
    WorkflowPytestContract(
        stage="staging_ai_ocr_transient_retry",
        workflow=".github/workflows/staging-ai-ocr-gate.yml",
        marker=STAGING_AI_OCR_GATE_MARKER,
        # #1806/AC-testing.deploy-gates.38: the single bounded retry re-runs
        # only the transient-failed corpus files emitted by --classify-junit —
        # a subset of the same derived corpus under the same marker, never a
        # different selection.
        paths=('"${AI_OCR_RETRY_TESTS[@]}"',),
        anchor="--junit-xml=test-results/staging-ai-ocr-retry.xml",
    ),
    WorkflowPytestContract(
        stage="production_readonly_smoke",
        workflow=".github/workflows/release.yml",
        marker=PRODUCTION_READONLY_MARKER,
        paths=("tests/e2e/test_production_readonly_smoke.py",),
        anchor="--junit-xml=test-results/production-readonly-e2e.xml",
    ),
)

# Stages whose junit-xml is aggregated by the ac-behavioral-ratchet job on
# every PR. A behavioral @ac_proof declaring ci_tier="pr_ci" must surface in
# this evidence — enforced by common/testing/check_pr_ci_evidence.py.
PR_EVIDENCE_STAGES: frozenset[str] = frozenset(
    {"backend_ci", "backend_integration", "frontend_vitest"}
)
