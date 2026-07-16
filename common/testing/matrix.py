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
        "apps/backend/tests/e2e/test_core_journeys.py", "backend_tier1_api_e2e", True
    ),
    PathRule(
        "apps/backend/tests/e2e/test_seeded_statement_journey.py",
        "backend_tier1_api_e2e",
        True,
    ),
    PathRule(
        "apps/backend/tests/e2e/test_statement_corpus_journeys.py",
        "backend_tier1_api_e2e",
        True,
    ),
    PathRule(
        "apps/backend/tests/e2e/test_epic025_dry_ssot_e2e.py",
        "backend_tier1_api_e2e",
        True,
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
            "#1547 lineage: no provider/market/Vault dependency. Two in-runner "
            "stack bugs were flushed out on the way in: the double-/api "
            "NEXT_PUBLIC_API_URL 404 (PR #1587) and the #1589 click timeout — "
            "the app-wide FirstRunModal ('Set up your AI provider') opened on "
            "every full navigation because the stack had no provider wiring, "
            "intercepting pointer events over the upload button; fixed with "
            "placeholder provider wiring + an unroutable AI_BASE_URL in "
            "docker-compose.ci-e2e.yml (validates wiring, cannot spend quota)."
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
        "tests/e2e/test_business_value_correctness_gate.py",
        needs=(),
        audited=True,
        reason=(
            "#1505: CSV-only journey (upload/approve/reconcile/opening-balance), "
            "no LLM/market-data/persistent-staging dependency — same audited shape "
            "as test_vision_upload_to_dashboard_hard_gate.py, just no provider call "
            "at all (CSV parsing is fully deterministic)."
        ),
    ),
    E2ERow(
        "tests/e2e/test_ac_authority_tiers_epic026.py",
        needs=(),
        audited=True,
        reason=(
            "Audited (#1547 follow-up): pure registry/ratchet validation over local "
            "files — no network, no fixtures, zero external dependencies."
        ),
    ),
    E2ERow(
        "tests/e2e/test_application_ai_advisor_epic021.py",
        needs=(),
        audited=True,
        reason=(
            "Audited (#1547 follow-up): despite the name, this validates EPIC/SSOT "
            "document contracts only — it never exercises the advisor runtime or "
            "any LLM path."
        ),
    ),
    E2ERow(
        "tests/e2e/test_llm_provider_abstraction_epic023.py",
        needs=(),
        audited=True,
        reason=(
            "Audited (#1547 follow-up): static definition/document validation of the "
            "provider-abstraction contract (types, scenes, rotation) — reads files, "
            "never invokes the LLM layer."
        ),
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
# Staging post-deploy core E2E intentionally shares the preview expression.
STAGING_CORE_E2E_MARKER = PR_PREVIEW_E2E_MARKER
STAGING_AI_OCR_MARKER = "llm"
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
        anchor="--splits 5",
    ),
    WorkflowPytestContract(
        stage="backend_integration",
        workflow=".github/workflows/ci.yml",
        marker=BACKEND_INTEGRATION_MARKER,
        anchor="--junit-xml=test-results/backend-integration.xml",
    ),
    WorkflowPytestContract(
        stage="backend_tier1_api_e2e",
        workflow=".github/workflows/ci.yml",
        marker=BACKEND_TIER1_MARKER,
        # Tier-1 file set: core API journeys + the provider-free seeded
        # statement journeys (AC8.21) + the extraction-corpus journeys
        # (AC-llm.11) + the EPIC-025 reporting-extraction API proof.
        # Browser-dependent specs need a frontend and stay out of this
        # API-only lane (the local-only backend copies of test_auth_flows /
        # test_e2e_flows were deleted, #1682 — the root tests/e2e/ versions
        # are the only ones left, running in the deployment_e2e stage).
        paths=(
            "tests/e2e/test_core_journeys.py",
            "tests/e2e/test_seeded_statement_journey.py",
            "tests/e2e/test_statement_corpus_journeys.py",
            "tests/e2e/test_epic025_dry_ssot_e2e.py",
        ),
        anchor="--junit-xml=test-results/backend-tier1-e2e.xml",
    ),
    WorkflowPytestContract(
        stage=PR_PREVIEW_E2E_STAGE,
        workflow=".github/workflows/preview.yml",
        marker=None,  # runtime-derived: eval tools/test_selection.py --shell
        paths=('"${PR_PREVIEW_E2E_TESTS[@]}"',),
        anchor='-m "$PR_PREVIEW_E2E_MARKER"',
        precondition="tools/smoke_test.sh",
    ),
    WorkflowPytestContract(
        stage="staging_core_e2e",
        workflow=".github/workflows/deploy.yml",
        marker=STAGING_CORE_E2E_MARKER,
        paths=("tests/e2e",),
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
        stage="staging_ai_ocr_version_check",
        workflow=".github/workflows/staging-ai-ocr-gate.yml",
        marker=STAGING_VERSION_CHECK_MARKER,
        paths=("tests/e2e/test_version_check.py",),
        anchor="--junit-xml=test-results/staging-ai-ocr-version.xml",
    ),
    WorkflowPytestContract(
        stage="staging_ai_ocr_gate",
        workflow=".github/workflows/staging-ai-ocr-gate.yml",
        marker=STAGING_AI_OCR_MARKER,
        # Corpus is derived from @ac_proof metadata by
        # tools/staging_ai_ocr_gate_contract.py --shell (a view over the same
        # AC graph); the invocation consumes the emitted array.
        paths=('"${STAGING_AI_OCR_TESTS[@]}"',),
        anchor="--junit-xml=test-results/staging-ai-ocr-gate.xml",
    ),
    WorkflowPytestContract(
        stage="staging_ai_ocr_transient_retry",
        workflow=".github/workflows/staging-ai-ocr-gate.yml",
        marker=STAGING_AI_OCR_MARKER,
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
    {"backend_ci", "backend_integration", "backend_tier1_api_e2e", "frontend_vitest"}
)
