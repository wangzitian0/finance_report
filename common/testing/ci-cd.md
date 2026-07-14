# CI/CD and Test Optimization SSOT — Test-Pipeline Half

> **SSOT Key**: `ci-cd`
> **Source of Truth** for CI job structure, test optimization modes, and the
> test-pipeline performance metrics. Split at #1822 (SSOT dissolution):
> this half owns the merge-time CI pipeline (job structure, coverage/no-regression
> gates, test optimization). The deploy half —
> [common/runtime/ci-cd.md](../runtime/ci-cd.md) — owns post-merge staging/production
> deploy workflows, smoke tests, and deploy E2E gates. Section integrity is
> preserved across the split; no content was dropped.

*Extracted from [development.md](../meta/development.md) — see that file for Moon commands and local setup.*

---

## CI Job Structure

The GitHub Actions workflow (`.github/workflows/ci.yml`) follows this job dependency order:

```
standalone: lint ─────────────────────────────────────────────────────────────────────┐
standalone: ac-traceability ─────────────────────────────────────────────────────────┤
changes (Classify Changes) ──→ backend shards ───────┬→ ac-behavioral-ratchet ───────┤
                         ├────→ backend-integration ─┤                               │
                         ├────→ backend-e2e-tier1 ───┤                               │
                         ├────→ frontend-vitest ─────┴→ unified-coverage ────────────┤→ finish
                         ├────→ tooling-coverage ─────→ unified-coverage ────────────┤
                         ├────→ schema-migrations ───────────────────────────────────┤
                         ├────→ frontend-build ──────────────────────────────────────┤
                         ├────→ frontend-playwright ─────────────────────────────────┤
                         ├────→ frontend-telemetry-e2e ──────────────────────────────┤
                         └────→ container-images ────────────────────────────────────┘
main-only: unified-coverage ─→ unified-coverage-baseline-pr (not required by finish)
```

### Job Details

| Job | Purpose | Dependencies |
|-----|---------|--------------|
| **changes** | Detect whether changed paths require heavy backend/frontend/coverage jobs | None |
| **lint** | Static analysis (backend `src tests` ruff check + format check, frontend lint) + content-level secret scan (gitleaks, mirrors the pre-commit hook) + manifest/doc/CI metrics contract checks | None (first job) |
| **schema-migrations** | Run Alembic `upgrade head` followed by `alembic check` against an ephemeral Postgres service before merge | `needs: [changes]` |
| **backend** (Shards 1-5) | Backend fast-path tests only: `-m "not slow and not e2e and not integration"` | `needs: [changes]` |
| **backend-integration** | Backend integration stage (`-m "integration"`), deterministic service-backed behavior checks | `needs: [changes]` |
| **backend-e2e-tier1** | Backend Tier-1 API E2E stage: the exact file set is generated, not hand-listed here — see the `backend_tier1_api_e2e` rows in [`common/testing/data/test-execution-matrix.yaml`](data/test-execution-matrix.yaml) (the SSOT view of `common/testing/matrix.py#PATH_RULES`; includes the extraction-corpus journeys, `AC-llm.11`, registered in `common/llm/contract.py`) — with `-m "e2e and not slow and not integration and not perf"`. PR runs stay fail-fast; push/main runs report the full Tier-1 failure set. | `needs: [changes]` |
| **frontend-build** | Frontend TypeScript typecheck + production build when heavy CI is required | `needs: [changes]` |
| **frontend-vitest** | Frontend Vitest coverage and JUnit evidence when heavy CI is required | `needs: [changes]` |
| **frontend-playwright** | Provider-free frontend browser UI proof when heavy CI is required | `needs: [changes]` |
| **frontend-telemetry-e2e** | Hermetic browser telemetry-emission proof when heavy CI is required | `needs: [changes]` |
| **container-images** | Fail-closed gitleaks secret scan over each component's Docker build context (`apps/<component>`) before the build, then build backend and frontend staging images without pushing on PRs; push SHA-tagged images only on `main`. Right-moved: runs only when the build context changed (`image_build_required`), see Key CI Property 20 | `needs: [changes]` |
| **verify-sha-image-published** | Independently re-inspect the registry for the just-built `:<sha>` image on `main` push, so a build step that reports success without actually publishing is caught at commit time. Right-moved: only runs on `main` push, see Key CI Property 20a | `needs: [container-images]` |
| **tooling-coverage** | Run root tooling tests with common/tools coverage and upload LCOV inputs | `needs: [changes]` |
| **unified-coverage** | Merge backend, frontend Vitest, common, and tools LCOV inputs, run the PR-blocking diff coverage gate (`tools/check_diff_coverage.py`, #1810), audit source-tree/LCOV policy, calculate unified coverage and compare to baseline (blocking on `main` pushes, report-only on PRs), upload the coverage context artifact, and update Coveralls on `main` when heavy CI is required | `needs: [changes, backend, frontend-vitest, tooling-coverage]` |
| **unified-coverage-baseline-pr** | Main-only automation that downloads `unified-coverage-context`, commits a changed `unified-coverage.json` to `automation/unified-coverage-baseline`, and opens or updates the reviewed baseline PR. This job owns write-scoped GitHub token permissions; PR coverage calculation remains read-only. | `needs: [changes, unified-coverage]` |
| **ac-traceability** | Verify generated AC registries, E2E EPIC ownership, the uploaded AC traceability audit, and the reconciliation audit for all PR/main changes, including docs-only changes | None |
| **ac-behavioral-ratchet** | Aggregate JUnit AC evidence from backend and frontend Vitest stages and enforce the persisted per-AC behavioral score floor | `needs: [changes, backend, backend-integration, backend-e2e-tier1, frontend-vitest]` |
| **finish** | Aggregate all required and skipped job results | `needs: [changes, schema-migrations, backend, backend-integration, backend-e2e-tier1, frontend-build, frontend-vitest, frontend-playwright, frontend-telemetry-e2e, container-images, verify-sha-image-published, lint, tooling-coverage, unified-coverage, ac-traceability, ac-behavioral-ratchet]` |

### Key CI Properties

1. **Standalone Lint Job**: Runs independently; lint failures surface in ~1 min (not after 10 min backend shard).
2. **Change Classification**: Lightweight documentation, issue-template, markdown, and `.github/workflows/docs.yml` changes skip backend, frontend, and unified coverage. Runtime, test, tooling, CI, dependency, and coverage-policy changes run the full heavy path.
3. **Stable Required Checks**: Heavy jobs are skipped through job-level conditions rather than removing the workflow, so required check names remain visible and mergeable.
4. **AC Traceability Always Runs**: AC traceability is separate from unified coverage so docs-only AC/EPIC changes still get traceability validation. The CI-stage traceability gate and the core critical-proof matrix gate are no longer separate standalone steps: their contracts are FOLDED into the single AC-index gate (`tools/check_ac_index.py`, which runs once in the `lint` job and calls `check_ac_traceability` + `check_critical_proof_matrix` as libraries), so no protection was lost. The `ac-traceability` job first runs `tools/generate_ac_registry.py --check` to ensure generated registry indexes can be materialized from EPIC docs plus explicit overrides, then runs `tools/check_e2e_epic_traceability.py` to ensure product E2E root test functions carry function-level EPIC IDs, every project EPIC has product E2E ownership, the README EPIC map matches project EPIC files, and unclassified E2E-like assets outside declared roots fail CI, then generates `AC-TEST-TRACEABILITY-AUDIT.md` into `$RUNNER_TEMP`; the audit is uploaded as a CI artifact. The job also runs `tools/reconciliation_audit.py` through the backend uv environment as a hard gate and uploads reconciliation audit JSON/Markdown with the same artifact. The folded AC-index gate distinguishes CI-executed real test references from `_ac_stubs`, trivial placeholder assertions, pure `pass`, pure skipped tests, and real references that live only in non-required execution stages. `common/testing/data/test-execution-matrix.yaml` owns the path-to-stage mapping. CI fails on mandatory AC coverage that is missing, placeholder-only, stub-only, or real-only outside CI-required stages; full-strikethrough deprecated ACs are excluded from the mandatory gate. The folded macro gate fails README/matrix/owner-EPIC drift, E2E/EPIC ownership drift, duplicate critical proof IDs, and broad/reference-only critical proof anchors. The generated audit is uploaded as a CI artifact; checked-in archive copies were retired to reduce merge conflicts.
4a. **AC Behavioral Score Ratchet Is Separate by Artifact Dependency**: The per-AC behavioral score floor is enforced by the `ac-behavioral-ratchet` job, not by `ac-traceability`, because it must wait for JUnit XML from backend shards, backend integration, backend Tier-1 E2E, and frontend Vitest. Frontend Playwright and telemetry E2E are merge-authority behavior gates through `finish`, but they do not emit JUnit evidence for the ratchet. The job downloads only those JUnit-producing test-context artifacts, then runs `tools/aggregate_ac_evidence.py` followed by `tools/check_ac_score_baseline.py` against `common/testing/data/ac-score-baseline.jsonl`; `finish` requires it explicitly.
5. **Schema migrations are PR merge authority**: `schema-migrations` starts after change classification for heavy PR/main changes and runs `uv run alembic upgrade head` followed by `uv run alembic check` against real ephemeral Postgres. This is the authoritative pre-merge proof that Alembic can build the production schema and that SQLAlchemy model changes do not drift from migrations. Preview and staging prove deployed runtime health only; they must not be the first place schema DDL correctness is discovered. The job uploads `schema-migration-test-context` with the migration log and repository/run metadata.
6. **Generated API reference is code-owned**: Static API reference docs are generated from FastAPI OpenAPI by `tools/generate_api_reference.py`. PR CI runs `python ../../tools/generate_api_reference.py --check` inside the backend uv environment after dependencies are installed, so endpoint paths, parameters, request schemas, response schemas, and enum values cannot drift into hand-written Markdown.
7. **Generated DB schema reference is code-owned**: Static DB schema docs are generated from SQLAlchemy model metadata by `tools/generate_db_schema_reference.py`. The generated page is intentionally gitignored and is materialized by the MkDocs build hook in `docs/hooks.py`. PR CI generates it inside the backend uv environment and then runs `python ../../tools/generate_db_schema_reference.py --check`, so table, column, enum, index, constraint, and foreign-key inventory stays code-owned instead of duplicated in prose.
8. **Backend and frontend stages are explicit and split**: Backend fast-path remains shard stage (`backend`) with workflow job name `Backend Tests (Shard ${{ matrix.shard }}/5)`, 5-way `pytest-split`, `--splitting-algorithm=least_duration`, and the committed backend duration seed at `apps/backend/ci/backend-test-durations.json`. The backend job fails before pytest when the seed is missing or unexpectedly small, so CI cannot silently fall back to unseeded even splitting. Frontend PR CI is split into `frontend-build`, `frontend-vitest`, `frontend-playwright`, and `frontend-telemetry-e2e`, each starting after change classification instead of waiting on one another. Standalone gates start immediately: `lint` and `ac-traceability` have no `needs` dependency and run in parallel with change classification. Deterministic test, schema migration, browser, telemetry, and image jobs start after change classification and do not wait for lint, AC traceability, or behavior-only backend gates. Behavior-only backend gates run in parallel as explicit `backend-integration` and `backend-e2e-tier1` stages, and finish remains the authoritative aggregate gate for lint, AC traceability, AC behavioral score ratchet, schema migrations, tests, image validation, coverage, and skipped heavy-job semantics.
9. **Coverage Debug Context Is Always Uploaded**: The `tooling-coverage` job uploads `coverage-tooling` with `coverage/common.lcov` and `coverage/tools.lcov`; the read-only `unified-coverage` job downloads that artifact and uploads `unified-coverage-context` on success and failure. The unified artifact contains `coverage/backend.lcov`, `coverage/frontend.lcov`, `coverage/common.lcov`, `coverage/tools.lcov`, the current `unified-coverage.json`, and `coverage/coverage-context.txt` with raw line-count inputs, commit/event/run metadata, toolchain versions, and input hashes. Coverage regressions must be diagnosed from these artifacts before treating a percentage delta as nondeterminism. On `push` to `main`, the separate `unified-coverage-baseline-pr` job is the only CI job with `contents: write` / `pull-requests: write` for automatic baseline PR updates; PR coverage calculation does not receive write-scoped token permissions.
10. **CI Observability Artifacts Are Failure-Path Owned**: Backend shard, backend integration, backend Tier-1 E2E, frontend Vitest, frontend Playwright, frontend telemetry E2E, schema migrations, tooling/common coverage, AC traceability, PR preview, staging, manual AI/OCR, production release, and scheduled cleanup gates publish CI observability artifacts with `if: always()`. These artifacts include JUnit XML where pytest or Vitest can produce it, raw coverage/report inputs where relevant, and a small context file with repository/event/ref/SHA/run metadata plus target environment/version fields. Step summaries remain human-readable status pages; artifacts are the replayable evidence for both success and failure.
11. **Coveralls Is Main-Only Reporting**: Pull requests do not call Coveralls and therefore do not publish external Coveralls status contexts. CI pass/fail is decided by local gates (`tools/check_ci_metrics_contract.py`, `tools/check_coverage_policy.py`, `tools/check_diff_coverage.py` on PRs, `tools/calculate_unified_coverage.py`) aggregated by `finish`. Main pushes upload only the unified line-only LCOV report to Coveralls for badge and trend reporting after the local coverage gate passes. Backend/frontend per-flag Coveralls uploads are intentionally absent so a single commit has one reporting denominator.
12. **Single CI Metrics Contract**: `tools/check_ci_metrics_contract.py` is the single CI metrics contract. It runs in `lint` and validates that source-root discovery, `common/meta/extension/coverage/policy.py`, workflow gates, and AC traceability semantics stay aligned before coverage jobs finish.
13. **Toolchain Contract**: `tools/check_toolchain_contract.py` runs in lint and fails when Python, Node.js, uv, Docker base images, Compose service images, or frontend engine constraints drift from `toolchain.toml`.
13a. **Workflow Contract**: `tools/check_workflow_contract.py` runs in lint and is the mechanical guard against CI/deploy prose drift (#531). It parses `.github/workflows/*.yml` and fails when the documented job ids (e.g. the classifier job id `changes`, `lint`, `unified-coverage`, `finish`) or trigger events drift from this SSOT, when `deploy.yml` gains a branch `push`/`pull_request` path for staging (release-image tag push is allowed), or when an issue template uses a label outside the live repository taxonomy (e.g. the stale `infra`/`feature` instead of `infrastructure`/`enhancement`). It checks live job ids/triggers/labels, not mutable run status (run ids, timing, conclusions), which stay in CI artifacts.
13b. **Gate Inventory During Simplification**: `common/meta/data/ci-gate-inventory.yaml` is a transitional workflow-job inventory for cleanup. Every workflow job has exactly one proof `stage` and one `task_category`; these fields are placement metadata, not AC coverage keys. The top-level stage/category vocabulary is shared with `common/testing/ac_proof_execution.py`, so runtime proof metadata and inventory contracts cannot drift independently. `finish` remains the only branch-required status context, and resolved duplicate cleanups stay recorded after deletion. `tests/tooling/test_ci_gate_inventory.py` validates that the inventory matches live workflow jobs and `finish.needs`, so a cleanup PR cannot add a replacement entrance while leaving the old one untracked.

13c. **Deploy/Release Workflow Decomposition** (#1354): The deploy/release workflows are split for single-responsibility, not for new protection — the gate set is unchanged. (AC8.13.153) The staging AI/OCR corpus gate body lives once in the reusable `staging-ai-ocr-gate.yml` (`workflow_call`); both the inline staging chain (`deploy.yml#ai-ocr-gate`, record-only) and the manual recovery entry point (`deploy.yml#manual-ai-ocr-gate`, fail-fast) are `uses:` callers that differ only by a `blocking` input, so the two entrances cannot drift. The inline caller stays non-blocking through `blocking: false` (a `uses:` caller cannot set `continue-on-error`), and `post-merge-delivery` still reads its `ai_ocr_status` output. (AC8.13.154) The production release line (`dry-run`, `deploy`) moved out of `deploy.yml` into a manual-dispatch-only `release.yml` with a `production-release-<version_ref>` concurrency group (`cancel-in-progress: false`) so two production releases never run concurrently; `deploy.yml` keeps staging deploy and tag-push promote, and `verify_release_evidence.py` still verifies the `deploy.yml` promote run as the release-images proof. (AC8.13.155) PR-preview reclaim is owned by infra2: `preview.yml#cleanup` dispatches a vendor-neutral `preview-teardown` signal to infra2 on PR close (infra2's `preview-teardown.yml` performs the 1:1 teardown via `deploy_v2 --down`; the hourly `preview-leak-check` is the detection fallback), and `maintenance.yml#cleanup` is GHCR-image pruning only — the former app-side `keep_separate` reclaim split is retired.
14. **PR Image Build Validation**: PR CI dry-runs staging image builds before merge with the same Dockerfiles, contexts, and build arguments used by `main`, **when the build context changed** (Key CI Property 20). Main push CI is the only path that pushes SHA-tagged images to GHCR.
15. **Coverage Policy Audit**: `tools/check_coverage_policy.py` fails CI if backend, frontend, common, or tools source files drift from their LCOV report.
16. **No-regression gate**: Zero-tolerance; if ANY component is below baseline, CI fails immediately.
17. **Deny-list coverage scope**: Coverage scope is deny-list based within each governed source root. CI recursively expects every eligible source file in backend, frontend, common, and tools LCOV unless `common/meta/extension/coverage/policy.py` explicitly excludes it. New source roots fail the metrics contract until added to the policy and report pipeline.
18. **Contract checks run in both `lint` and `tooling-coverage` by design**: Each SSOT/contract script the `lint` job runs (`check_manifest`, `check_workflow_contract`, `check_governance_exceptions`, `generate_api_reference --check`, `check_ci_metrics_contract`, `check_ac_index`, `audit_router_contracts`, `lint_doc_consistency`, `generate_epic_status`, etc.) is **also** asserted by a `tests/tooling/` test executed in the `tooling-coverage` job (e.g. `test_check_manifest.py`, `test_workflow_contract.py`), several of which assert that the real repository passes. The two jobs serve different masters and are not redundant: `lint` is the standalone fast-fail lane (no test environment, surfaces in ~1 min, Key CI Property 1), while `tooling-coverage` executes those contracts as tests so `common/`+`tools/` get line coverage. The consequence is intentional but worth knowing: **a single contract drift fails both `lint` and `tooling-coverage`** — fix the one source, not each job. The `pre-push` tier (see [Local Guardrail Tiers](#local-guardrail-tiers-and-latency-budget)) mirrors the cheapest of these so the drift is usually caught before either CI job runs.
19. **`finish` reporting is non-gating**: The `finish` job's merge authority is its `Check job status` step alone. Its three step-summary writers (coverage-effect table, CI timing, coverage-gate narrative) are reporting only and all carry `continue-on-error`, so a summary write can never decide merge.
20. **`container-images` — narrow on PR, always builds the immutable `:<sha>` on main**: The classifier (`common/testing/change_classifier.py`) emits `image_build_required`, true only when a Docker build input changed — Dockerfiles, `.dockerignore` (changes what is sent in the build context), dependency manifests/locks (`uv.lock`, `package-lock.json`, `pyproject.toml`, `package.json`), build config (`next.config.mjs`, `tsconfig.json`, `postcss`/`tailwind` config), or the backend entrypoint/build scripts (`apps/backend/scripts/`). **On a PR** that signal narrows the dry-run: a pure app-source change is validated by `frontend-build` (`tsc --noEmit` + `next build`) and the backend test jobs, so the PR does **not** also dry-run a fresh image build (no push happens on PRs anyway). **On a `main`/`release` push (and manual dispatch) `container-images` ALWAYS builds and pushes the `:<sha>` image regardless of `image_build_required`** — the Dockerfiles `COPY` app source into the image, so every commit's image content differs, and promote-not-rebuild (the `deploy_v2` release path) requires an immutable `:<sha>` artifact for *any* releasable commit; gating the main build on build-context alone would leave source-only / submodule-only commits with no `:<sha>` to promote. `container-images` therefore gates on `(push to main|release) || workflow_dispatch || (pr_required && image_build_required)`; `finish` treats a skipped `container-images` (PR-only) as a pass (not a gap). An unknown diff fails closed and rebuilds. This keeps PRs fast while guaranteeing every main commit is releasable.

20a. **`verify-sha-image-published` — independently re-checks the `:<sha>` actually landed** (#1759, W4 of #1435): Property 20 guarantees every main commit *attempts* to build and push a `:<sha>` image, but a `docker/build-push-action` step reporting success does not, by itself, prove the image is pullable from the registry (a silent push failure or registry propagation gap would only surface later, at promote time — the #1411 failure mode). `verify-sha-image-published` runs after `container-images` on `main` push only (`needs: [container-images]`, `if: github.event_name == 'push' && github.ref == 'refs/heads/main'`) and calls the existing `tools/verify_release_images.py` (`common/runtime/release_images.py`) with `--version-ref <short_sha>` — the same digest-inspection primitive `release.yml`'s dry-run already uses for release tags, reused here for the per-commit tag instead of a new mechanism. `finish` treats a skipped run (PR / non-main push, per this job's own `if:`) as a pass, mirroring the `container-images` skip-is-a-pass clause above; a failed inspection fails `finish`.

### Env x Stage Contract

This SSOT separates environment taxonomy, pipeline stages, and GitHub Actions jobs.
Environment taxonomy names the runtime contexts in [environments.md](../runtime/environments.md).
Pipeline stages are quality gates such as changed UT, lint/static checks, full UT,
integration, regression/E2E, image validation, deploy smoke, provider gates, and
release integrity. GitHub Actions jobs are implementation lanes for selected
environment/stage cells.

Local runs are fast advisory gates. PR CI is the deterministic merge authority.
PR Preview, staging, and production are deployed-environment proof gates. The model
is an Env x Stage Execution Matrix: not every environment runs every pipeline stage,
and environment names must not be counted as pipeline stages.

#### Environment Axis

| Environment | Meaning |
|---|---|
| `local` | Developer machine and local CI commands |
| `pr` | GitHub PR/main CI runner proof before merge or staging consumption |
| `pr-preview` | Per-PR deployed Docker environment |
| `staging` | Shared post-merge deployed environment for successful `main` SHAs |
| `prd` | Production release environment |

#### Pipeline Stage Axis

| Pipeline stage | Purpose |
|---|---|
| Changed/Affected UT | Fast local or focused unit feedback for touched/affected code |
| Lint/Static | Syntax, formatting, static contracts, SSOT and traceability checks |
| Full UT | Deterministic unit coverage over governed app/tooling source trees |
| Integration | Service-backed deterministic tests that do not require deployed routing |
| Regression/E2E | Deterministic API/browser/user-journey proof |
| Image Build | Dockerfile, build context, and build-argument proof |
| Deploy Smoke | Runtime health, routing, version, and deploy integrity proof |
| Provider Gate | Provider-backed OCR/LLM proof with real external credentials |
| Release Integrity | Manual production release prerequisite and image/deploy proof |

#### Env x Stage Execution Matrix

| Env \ Stage | Changed/Affected UT | Lint/Static | Full UT | Integration | Regression/E2E | Image Build | Deploy Smoke | Provider Gate | Release Integrity |
|---|---|---|---|---|---|---|---|---|---|
| `local` | default | focused/static contracts | risk-triggered only | risk-triggered only | not default | no | no | no | no |
| `pr` | covered by full gates | required | required for heavy changes | required for heavy changes | Tier-1/provider-free required for heavy changes | dry-run required for heavy changes | no | no | no |
| `pr-preview` | no | no | no | no | runtime/UI/API preview-relevant subset after successful PR CI | no PR images | runner `/api/health` + smoke/E2E | no | no |
| `staging` | no | no | no | no | merged-SHA non-LLM regression plus provider-backed regression when required | reuse or build missing SHA images | required | runs when real provider proof is required | no |
| `prd` | no | no | no | no | prod-safe smoke only | release image proof | required | no first-time proof | required |

Production release proof is intentionally narrow: production validates release
integrity and availability, not first-time deterministic business behavior.

#### AC Proof Execution Model

The AC id remains the only coverage key. Execution placement is metadata on a
proof edge:

```text
AC -> proof(name, stage, task_category)
```

`stage` answers where the proof runs and how strong that protection is.
`task_category` answers which execution family/job lane performs it. Neither
field is an identity key, and neither competes with the AC id for ownership. This
execution-placement metadata also does not replace authority tier or proof_kind:
authority tier says who owns the behavior's decision, and `proof_kind` says what
shape of proof is valid for that authority tier.

Valid proof execution stages:

| Stage | Meaning |
|---|---|
| `local.advisory` | Developer-local feedback that helps iteration but does not block merge. |
| `github_ci.merge_authority` | GitHub CI proof required before code can merge. |
| `preview.runtime` | PR preview runtime proof outside the merge-authority CI job set. |
| `staging.release_validation` | Staging validation for a selected merged SHA or release coordinate. |
| `staging.provider_regression` | Staging proof that needs real provider credentials or provider spend. |
| `prod.release_integrity` | Production release integrity and prod-safe smoke proof. |
| `ops.scheduled_cleanup` | Scheduled operational cleanup or retention proof. |
| `manual.adjudication` | Manual evidence review that cannot be reduced to a deterministic runtime check. |

Valid proof task categories:

| Task category | Typical job family |
|---|---|
| `aggregate` | Final fan-in / status aggregation. |
| `classify` | Changed-path or dispatch-scope classification. |
| `static_contract` | Static lint, docs, SSOT, generated-reference, or workflow contract checks. |
| `ac_traceability` | AC registry, AC-index, and traceability audits. |
| `backend_unit` | Backend fast unit shards. |
| `backend_integration` | Backend service-backed integration tests. |
| `backend_api_e2e` | Backend Tier-1 API E2E tests. |
| `frontend_build` | Frontend typecheck and production build. |
| `frontend_unit` | Frontend unit/component coverage. |
| `frontend_browser_e2e` | Frontend browser E2E proof. |
| `image_build` | Docker image build or promotion validation. |
| `tooling_contract` | Tooling/common contract tests. |
| `coverage_fan_in` | Coverage input aggregation and regression checks. |
| `behavioral_ratchet` | AC behavioral evidence ratchet. |
| `deploy_smoke` | Deployed route, health, version, and smoke checks. |
| `provider_gate` | Provider-backed OCR/LLM/API connectivity or regression checks. |
| `release_integrity` | Release coordinate, immutable image, and prod-release checks. |
| `cleanup_retention` | Retention and stale-resource cleanup checks. |
| `critical_behavioral` | Co-located critical product proof edge. |
| `manual_evidence` | Manual gate evidence record. |

### Local Guardrail Tiers and Latency Budget

Pre-merge protection is layered by latency budget. Each tier is bounded so that it
stays fast enough that contributors never learn to bypass it, and the cheapest tier
that can catch a class of failure should also run it for the earliest feedback
(left-move). Cost rises with each tier. **The local tiers are advisory
(`local.advisory` proof stage); only CI is merge authority.**
`.pre-commit-config.yaml` is the source of truth for the two local tiers, but every
check a local tier runs is independently re-run by CI — the table's checks are a
strict *mirror subset* of CI, never a delegation of it.

| Tier | Trigger | Budget | Scope | Runs (all re-run by CI) | Must NOT do |
|---|---|---|---|---|---|
| `pre-commit` | every `git commit`, staged files | ≤ ~2s | file-scoped fast static + auto-fix | ruff lint/format, gitleaks (staged content), mypy (staged backend), env-key / Pydantic-schema sync, file hygiene | run repo-wide suites or import the app graph; auto-fixers stay commit-only (`stages: [pre-commit]`) so they never mutate the tree mid-push |
| `pre-push` | every `git push`, whole repo | ≤ ~10s | cheap repo-wide contract / drift gates mirroring the CI `lint` job | SSOT manifest, governance-exceptions registry, workflow contract, generated API-reference freshness — the drift classes behind most CI `lint` / `tooling-coverage` failures | run full pytest, backend shards, coverage, or browser tests (minutes-scale → CI only) |
| `CI` (`lint` + `changes` first) | PR / push on the GitHub runner | minutes; first gate ~1 min | full deterministic merge authority | everything in [Job Details](#job-details), re-run from a clean checkout with no assumption that any local tier ran | omit or weaken a check because a local tier also runs it |

Tier rules:

- **Local results are never trusted; they raise the hit rate, they do not gate
  merge.** A hook can be uninstalled, bypassed with `--no-verify`, skipped under a
  set `core.hooksPath`, or simply never have existed on the submitter's machine, so
  CI assumes nothing local ran and re-runs every check independently from a clean
  checkout. A check is therefore **never removed from or weakened in CI because a
  local tier also performs it** — `pre-push` is a strict mirror-subset of CI gates
  for early, cheap feedback, not an authority CI may lean on. The payoff of the
  local tiers is fewer wasted CI cycles and faster author feedback, not a smaller CI.
- **The budget is a contract, not a target.** A `pre-commit` hook that creeps past
  ~2s, or a `pre-push` gate past ~10s, trains `--no-verify`, which silently disables
  every gate behind it. When a check outgrows its budget, move it down a tier
  (commit → push, or push → CI) rather than letting the tier slow down.
- **CI parity is one-directional: local mirrors CI, not the reverse.** `pre-push`
  gate commands are copied verbatim from `.github/workflows/ci.yml` so a local pass
  predicts the CI result, but CI never shrinks to match local. The hosted
  pre-commit.ci runner has no `uv`/backend and `ci.skip`s those gates; GitHub
  Actions stays authoritative.
- **No coverage or behavior proof at push.** Coverage, the AC behavioral ratchet,
  and full test suites need artifacts and minutes; they stay in CI (see
  [Stage Matrix and Left-Move Guidance](#stage-matrix-and-left-move-guidance)).
  `pre-push` proves only cheap, deterministic contracts. A repo-wide pytest pre-push
  hook is explicitly out of budget and is not the project guardrail.
- **One install path.** `tools/bootstrap.sh` runs `pre-commit install`;
  `default_install_hook_types: [pre-commit, pre-push]` wires both stages with no
  extra step, so the two local tiers are managed by one framework rather than a
  hand-placed native hook.

### Path Risk to Local Gate Matrix

Default local verification starts with affected fast tests such as
`moon run :test -- --smart`, focused backend paths through
`moon run :test -- --fast tests/...`, focused Vitest/spec runs, or the smallest
relevant tooling contract. Direct backend `pytest tests/...` uses the backend
default coverage policy and is not the focused TDD path. Risk-triggered local
escalation applies when the changed path can affect behavior outside the touched
file.

| Changed path or concern | Default local gate | Escalation trigger |
|---|---|---|
| Ordinary backend source | `moon run :test -- --smart` or `moon run :test -- --fast tests/...` for a focused backend path | Escalate when the change crosses service boundaries or touches shared helpers |
| accounting, posting, reconciliation, money, balance | Focused domain pytest suite plus changed-file tests | Always include invariant tests beyond the touched file |
| schema, migrations | `cd apps/backend && uv run alembic upgrade head && uv run alembic check`, plus focused DB-backed tests | Required for any Alembic, SQLAlchemy model, enum, or persistence contract change |
| API contract, OpenAPI | Backend API tests plus affected frontend API consumer tests; `tools/preflight.py` runs the `api-reference` and `router-contract` gates so `docs/reference/api.md` and `docs/reference/router-contract-maturity.md` are verified locally, matching the CI Lint and Tooling gates | Required for route, schema, generated API reference, or response-shape changes |
| Frontend component or route | Focused Vitest/spec, then affected Playwright when browser behavior changes | Escalate for navigation, responsive layout, workflow, or API-bound behavior |
| shared common/tooling | Focused tooling tests plus affected downstream contracts | Escalate when a common package feeds CI, coverage, SSOT, or command wrappers |
| Docker, workflow, environment, deploy | Static/tooling contract checks locally; PR CI and deployed gates own runtime proof | Required image/deploy proof stays in PR CI, PR Preview, staging, or production |
| docs-only | SSOT/doc/traceability checks only | Escalate only when docs change workflow, registry, AC, or proof semantics |

### Stage Matrix and Left-Move Guidance

| Stage | Current execution | Scope in CI | Coverage effect | Left-move action |
|---|---|---|---|---|
| Schema migrations | `schema-migrations` job after change classification | Alembic `upgrade head` and `check` against ephemeral Postgres | No line coverage effect | Keep as PR merge authority; preview/staging must only prove deployed runtime health |
| Unit (fast/shard) | `backend` job, 5 seeded shards immediately after change classification | `-m "not slow and not e2e and not integration"` | Feeds unified line coverage (backend component) | Keep as deterministic base and tune seed quality before increasing shard count |
| Integration (backend marker) | `backend-integration` job (`-m "integration"`) | `apps/backend/tests/**/*` marker-scoped integration suites with service-backed env | Not part of unified line baseline yet | Add sharding when count growth justifies it; keep explicit marker gate in CI |
| Tooling/common contracts | `tooling-coverage` job | `tests/tooling/` with `--cov=common --cov=tools` | Feeds unified line coverage (common/tools components) | Keep parallel to app tests so tooling failures and LCOV inputs are independently visible |
| Tier 1 API E2E | `backend-e2e-tier1` job (the `backend_tier1_api_e2e` file set from `common/testing/matrix.py#WORKFLOW_PYTEST_CONTRACTS` with `-m "e2e"`) | Serial backend contract/HTTP/DB/S3 API behavioral paths with Postgres and MinIO bucket readiness, including the extraction-corpus journeys (`AC-llm.11`, see `common/llm/readme.md#extraction-corpus-e2e`); PR runs use `--maxfail=1`, while push/main Tier-1 E2E runs without `--maxfail=1` so one JUnit artifact reports all failing journeys | Behavioral proof only; AC traceability-backed | Stabilize a deterministic API subset first, then scale by marker or folder |
| Tier 2 HTTP E2E | `tools/tier2_http_e2e.py` against deployed PR/staging/prod URLs | Not in unified coverage baseline | Behavioral proof only; reports carry `proof_tier=tier2_http` | Keep the command strict in deployed gates; advisory/env-gated not-run reports are never proof eligible |
| Frontend build/typecheck | `frontend-build` job | TypeScript `tsc --noEmit` and Next production build | Behavioral/build proof only; not in unified line coverage | Keep separate from browser tests so build/type errors surface without waiting for Playwright |
| Frontend Vitest | `frontend-vitest` job | Frontend unit/component coverage with Vitest JUnit output | Feeds unified line coverage (frontend component) and AC behavioral ratchet | Keep as the only frontend source-coverage producer until browser tests emit ratchet-ready evidence |
| Frontend Playwright | `frontend-playwright` job | Provider-free browser UI specs under `apps/frontend/playwright`; the job builds before `npm run start` because CI Playwright config starts an already-built app | Behavioral proof only; not in unified line coverage | Env-gated specs stay non-required until their env is provided in CI |
| Frontend telemetry E2E | `frontend-telemetry-e2e` job | Hermetic browser telemetry-emission spec with fake same-origin telemetry endpoints; the job builds before `npm run start -- --port` because the telemetry CI config starts an already-built app | Behavioral proof only; not in unified line coverage | Keep isolated from provider-free UI specs because it injects telemetry env via its own Playwright config |
| Tier 3 Browser E2E | Staging/PR preview/prod smoke jobs | Playwright/HTTP deployment suites (`smoke`, `e2e`, `llm` split) | Behavioral/prod-risk proof only | Keep provider-dependent `llm` in post-merge; split provider-free subset for PR preview |

#### Pytest marker taxonomy (#1682)

Three pytest rootdirs (`pytest.ini` at repo root, `apps/backend/pyproject.toml`,
`tests/e2e/pytest.ini`) register markers independently — this table is the one
place that reconciles them, so a marker's *live* selection role doesn't have to
be reverse-engineered from `.github/workflows/ci.yml` on every audit.

| Marker | Registered in | Live CI-selection expression | Role |
|---|---|---|---|
| `smoke` | root `pytest.ini`, `tests/e2e/pytest.ini` | `(smoke or e2e) and not llm` (PR preview) | Selector |
| `e2e` | root `pytest.ini`, `apps/backend/pyproject.toml`, `tests/e2e/pytest.ini` | `e2e and not slow and not integration and not perf` (backend-tier1); `(smoke or e2e) and not llm` (PR preview) | Selector |
| `llm` | root `pytest.ini`, `tests/e2e/pytest.ini` (not registered in `apps/backend/pyproject.toml`) | staging AI/OCR gate marker; excluded everywhere else (`and not llm`) | Selector |
| `prod_safe` | root `pytest.ini`, `tests/e2e/pytest.ini` | production read-only smoke marker | Selector |
| `slow` | `apps/backend/pyproject.toml` | excluded from `backend` and `backend-e2e-tier1` (`not slow`) | Selector (exclusion) |
| `integration` | `apps/backend/pyproject.toml` | `backend-integration` job (`-m integration`) | Selector |
| `perf` | `apps/backend/pyproject.toml` | excluded from `backend-e2e-tier1` (`not perf`) | Selector (exclusion) |
| `critical` | root `pytest.ini`, `tests/e2e/pytest.ini` | read by a `pytest_runtest_makereport` hook in `tests/e2e/conftest.py`, not a `-m` expression | Hook-consumed |
| `allow_browser_errors` | root `pytest.ini` | read by a conftest hook that permits expected CSP/JS errors | Hook-consumed |
| `no_db` | `apps/backend/pyproject.toml` | read by a fixture (skips the autouse DB setup) | Hook-consumed |
| `needs_real_cassette` | `apps/backend/pyproject.toml` | read locally to skip until a cassette is recorded | Hook-consumed |
| `api` | root `pytest.ini`, `tests/e2e/pytest.ini` | none | Tag-only (documentation grouping) |
| `tier3` | `tests/e2e/pytest.ini` | none | Tag-only (post-merge/staging grouping) |

`api` and `tier3` are intentionally tag-only — they group tests for humans
reading a file, not for a `-m` selection expression. A marker is only worth
retiring if it appears in **no** registration, no test, and no CI expression;
none currently meet that bar.

#### Seeded no-LLM statement fixture (provider-free journeys in the merge tier)

Journeys that depend on a parsed statement (review -> reconcile -> report) must
not require a real provider to run in the merge-blocking tier. The reusable
pattern is the `seeded_parsed_statement` fixture in
`apps/backend/tests/e2e/conftest.py`: it injects an already-parsed statement —
ODS `UploadedDocument`, DWD `StatementSummary` (`status=PARSED`), and Layer-2
`AtomicTransaction` rows joined via `source_documents[*].doc_id` — directly into
the test database via `tests/factories.py`, bypassing the extraction/LLM seam
(`ExtractionService.parse_document` -> `stream_ai_json`) entirely. A test using
it carries only `@pytest.mark.e2e` (never `@pytest.mark.llm`), so it runs under
`-m "(smoke or e2e) and not llm"`. **Tag discipline**: only a test that actually
calls the extraction service carries `@pytest.mark.llm`; everything provider-free
seeds its parsed input through this fixture and stays in the merge gate. New
statement journeys reuse `seed_parsed_statement(...)` rather than uploading a
real document and waiting on a provider parse.

### PR vs Main CI Responsibilities

Pull requests run the same heavy CI path as `main` when runtime, tests, tooling,
CI, dependency, or coverage-policy files change. This keeps branch protection
strict before merge.

Pushes to `main` still run heavy CI for runtime changes even though the merged PR
already ran required checks. The retained post-merge run provides two signals
that PR checks cannot fully replace: validation of the exact merge commit and a
final local gate before post-merge staging/AI workflows consume the new commit.
Coverage regression detection is enforced locally against
`unified-coverage.json`; Coveralls remains main-only reporting and does not
decide CI pass/fail.

CI concurrency is deliberately different for PRs and `main`. Pull request runs
share a PR ref-scoped concurrency group and cancel superseded in-progress runs
to keep author feedback current. Pushes to `main` use a SHA-scoped concurrency
group, so rapid consecutive merges do not cancel or replace a pending main CI
run for an earlier merge commit. `workflow_dispatch` uses the run ID to keep
manual validations independent.

Lightweight changes do not repeat the heavy path on either PRs or `main`.
Lightweight means all changed files are limited to documentation, markdown,
issue templates, or `.github/workflows/docs.yml`. Other workflow changes are not
skipped because they may affect CI, deploy, or release behavior and must exercise
the full gate.

### Proof Placement Policy

The test system separates proof by where the failure can be acted on:

| Proof type | Runs where | Purpose |
|---|---|---|
| Behavioral tests | PR CI before merge | Prove deterministic product behavior, accounting invariants, API contracts, frontend flows, and tooling contracts before code enters `main`. |
| Schema migration contract | PR CI before merge | Prove Alembic can build the production schema from empty Postgres and that model definitions do not drift from generated migrations. |
| Migration risk contract | PR CI lint and production dry-run | Prove each Alembic revision has a right-sized risk classification. High and critical migrations must carry staging, production preflight, and rollback/expand-contract notes; this does not guarantee production data safety. |
| Environment gates | Post-merge deploy workflows | Prove the exact merged SHA can run in staging/production-like environments with real routing, Vault/Dokploy/GHCR/the observability backend wiring, deployed images, and provider-backed OCR/LLM credentials. |
| Reference traceability | PR and `main` CI | Prove every mandatory AC has a real non-placeholder test reference in a CI-required execution stage from `common/testing/data/test-execution-matrix.yaml`; this is not line coverage. |
| E2E EPIC traceability | PR and `main` CI | Prove every product E2E root `test_*` function has a function-level EPIC ID, every project EPIC has at least one product E2E owner test, the README EPIC map matches project EPIC files, and E2E-like assets are declared as product or non-product. |
| Critical proof matrix | PR and `main` CI | Prove README -> EPIC -> E2E macro closure and selected core proof paths instead of broad AC string references. |

Behavioral tests should move left into PR CI whenever they can be deterministic
without external singleton state or provider spend. Environment-dependent checks
belong in post-merge staging/production workflows because they validate the
deployed merge commit and shared infrastructure. A post-merge environment gate
must not be the first proof for deterministic business behavior.
Schema DDL correctness is deterministic and belongs in PR CI through
`schema-migrations`; preview and staging may catch environment-specific
deployment wiring, but they are not substitutes for migration proof.
Production data migration safety is not fully provable before production. The
migration risk contract classifies the risk and required evidence so staging is
used for the issues it can realistically catch, while production residual risk
is handled through preflight, backup, feature-flag, idempotency, and
post-deploy controls.

### Tier 2 HTTP E2E Command

Tier 2 deployed HTTP proof runs through:

```bash
python3 tools/tier2_http_e2e.py \
  --base-url "$APP_URL" \
  --expected-sha "$EXPECTED_SHA" \
  --mode staging \
  --json-report test-results/staging-tier2-http.json \
  --junit-xml test-results/staging-tier2-http.xml
```

The staging deploy workflow runs this command after `tools/smoke_test.sh` and
before the broader `pytest tests/e2e` deployed suite. Missing `--base-url` or
`--expected-sha` is a hard command failure in deployed gates. Local advisory
usage may opt into `--advisory-if-missing`, but that report is explicitly
`proof_eligible=false` and cannot satisfy AC proof. The JSON and JUnit reports
carry `proof_tier=tier2_http` so dashboards can distinguish unit, integration,
Tier 1, Tier 2, and Tier 3 evidence.


---

## PR Review Thread Merge Gate

`tools/check_pr_review_threads.py` (logic in
`common/testing/check_pr_review_threads.py`) is a merge-time gate that blocks a PR
while a high-severity review thread is still open. It runs as a step in the
`lint` job of `.github/workflows/ci.yml` on `pull_request` events, reading the
PR's review threads through the GitHub GraphQL API (`gh api graphql`). It is
bootstrap-safe and skips cleanly (exit 0) on non-PR events (no PR number).

### Severity classification rule

For each review thread the gate inspects the **first comment**:

- A thread is **blocking (P0/P1)** when either:
  - the first comment body matches the marker regex `\b(P0|P1)\b`
    (case-insensitive), OR
  - the first comment is **Copilot-authored** (`author.login` in
    `copilot`, `github-copilot[bot]`,
    `copilot-pull-request-reviewer` — the actual login the GraphQL API
    returns today, no `[bot]` suffix — or `copilot-pull-request-reviewer[bot]`)
    AND the body is **not** explicitly marked a lower severity (it does not
    contain `P2`, `P3`, or `nit`).
- Every other thread is **lower severity**.

### Decision

- The gate **exits 1** (blocks merge) when any thread is **unresolved** AND
  classified **blocking**.
- **Resolved** and **outdated** threads never block, regardless of severity.
- **Lower-severity unresolved** threads (e.g. `P2`/`P3`/`nit`) do **not** block;
  they are printed in the summary so reviewers can still see them.

The gate prints a summary with the thread counts and, when it blocks, the URLs
of the offending threads. Resolve or mark the thread resolved on GitHub to clear
the gate.


---

## No-Regression Coverage Gate

The CI workflow enforces a **no-regression policy** for test coverage as the
**main-push water-line**. On pull requests the blocking coverage verdict is
the **diff coverage gate** (`tools/check_diff_coverage.py`, #1810): the PR's
changed/added lines in governed source trees must be covered at or above the
threshold (default 85%), with uncovered `file: line-range`s named in the
output; the no-regression comparison still runs on PRs but is **report-only**
(`COVERAGE_RATCHET_MODE=report`). Semantics detail:
[coverage.md](./coverage.md#coverage-gate).

### How It Works

1. **Baseline Storage**: `unified-coverage.json` at repo root.
   - CI reads the committed file as the no-regression floor (blocking on `main` pushes; report-only on PRs).
   - Main CI writes the current measured file inside the read-only `unified-coverage` job artifact. A separate main-only `unified-coverage-baseline-pr` job downloads that artifact and opens or updates an automatic baseline PR when that file differs.
   - CI never pushes directly to `main`; branch protection still requires the reviewed baseline PR to merge.

2. **Comparison Logic**:
   - Reads `unified-coverage.json` before calculating final coverage
   - Compares current vs baseline for **all components**: unified, backend, frontend, common, tools
   - Uses `round(x, 2)` for floating-point comparison
   - **Zero tolerance in block mode** (main pushes): `current < baseline` (beyond the ±0.05% jitter epsilon) → CI fails immediately; in report mode (PRs) the same regression is printed but does not fail the run
   - If baseline file missing: falls through to `COVERAGE_THRESHOLD` check (safety net)
3. **Source-tree/LCOV Logic**:
   - `common/meta/extension/coverage/policy.py` defines the single component policy used by coverage calculation and audit checks
   - `tools/check_ci_metrics_contract.py` first discovers source roots and fails CI when a new `apps/*/src`, `packages/*/src`, or root shared source root is not represented in `common/meta/extension/coverage/policy.py`
   - `tools/check_coverage_policy.py` compares eligible source files with LCOV `SF:` entries
   - `tools/build_unified_lcov.py` rewrites component-relative LCOV paths to repository-root-relative paths for Coveralls
   - New source modules are automatically required to appear in LCOV unless explicitly excluded by policy
   - New `apps/*/src`, `packages/*/src`, or root shared source roots fail CI until they are added to the coverage policy and report pipeline

4. **Metric Semantics**:
   - Line coverage is the only numeric source coverage metric enforced by the no-regression gate
   - AC traceability is a reference metric, not behavioral coverage
   - CI fails on mandatory AC coverage that is missing, placeholder-only, or stub-only; mandatory AC proof must also come from a CI-required execution stage in `common/testing/data/test-execution-matrix.yaml`
   - E2E EPIC traceability fails E2E-root test functions missing function-level EPIC IDs, project EPICs without product E2E owner tests, README EPIC map drift, and unclassified E2E-like assets outside declared roots
   - The critical proof matrix protects only selected core proof paths from broad/reference-only AC strings
   - The source coverage matrix treats `required_source_classes` and per-source `proof_levels` as strict lists; scalar YAML values fail directly instead of being iterated character-by-character
   - Critical proof IDs are unique; duplicate IDs fail before mirror proof resolution can silently overwrite an earlier proof
   - Behavioral product coverage must be proven by Tier 1+ tests and explicit product E2E gates, not by an AC string appearing in a test file
   - Stub and placeholder assertions cannot count as proof; the CI gate runs before the traceability audit artifact is generated

5. **Environment Variables**:
   - `BASELINE_FILE`: Path to baseline JSON (default: `unified-coverage.json`)
   - `COVERAGE_THRESHOLD`: Safety net threshold (default: `0`; applies in both ratchet modes)
   - `COVERAGE_RATCHET_MODE`: `block` (default; main pushes) fails on a baseline regression, `report` (PR lane) prints it report-only (#1810)
   - `DIFF_COVERAGE_THRESHOLD` / `DIFF_COVERAGE_BASE`: diff coverage gate overrides (defaults: `85`, `origin/main`)

### Baseline Reset / Raise

```bash
# Option 1: Prefer the automatic baseline PR opened by main CI after coverage rises.

# Option 2: Update baseline to current state manually when repairing automation
git pull origin main
# Make your changes, then:
git add unified-coverage.json && git commit -m "chore: manually reset coverage baseline" && git push

# Option 3: Remove baseline temporarily
git rm unified-coverage.json && git commit -m "chore: remove coverage baseline for testing" && git push
```

---

---

## Test Optimization

### Test Modes

| Mode | Command | Speed | Coverage | Use Case |
|------|---------|-------|----------|----------|
| Smart | `backend:test-smart` | ~40% | Changed files 99% | Daily dev (recommended) |
| Ultra-fast | `backend:test-no-cov` | ~30% | None | TDD red-green |
| Full | `backend:test` | 100% | All files 94% | CI/pre-commit |

### Implementation

**Tooling**:
- `tools/test_lifecycle.py --smart` — Runs backend tests with coverage on changed Python modules only
- `tools/test_lifecycle.py --fast` — Runs backend tests without coverage
- `tools/test_lifecycle.py` — DB lifecycle and namespace isolation for backend tests
**CI Optimization** (`.github/workflows/ci.yml`):
- Change classification is implemented in `tools/ci_change_classifier.py` and skips backend/frontend/unified coverage for lightweight docs and docs workflow changes.
- The classifier's contract is structured Env x Stage JSON outputs over the complete environment axis (`local`, `pr`, `pr-preview`, `staging`, `prd`): `env_stage_required`, `env_stage_reasons`, `env_stage_stages`, `env_stage_files`, and provider-gate JSON outputs, alongside the top-level `heavy_required` and `reason` scalars. GitHub Actions consumers normalize gates from the structured matrix. The legacy per-env scalar outputs (`pr_preview_required`, `staging_required`, `staging_ai_ocr_required`) have been **retired**: every workflow consumer (`ci.yml`, `preview.yml`) now derives its own scalar from the structured matrix, so the classifier no longer emits the per-env compatibility shims. The same per-env values remain only in the human-readable job summary.
- Workflow YAML remains explicit; it is not generated from SSOT or the classifier at runtime. The consumer contract is that changed-path classification stays owned by the classifier step, while downstream jobs consume normalized Env x Stage-derived outputs instead of reimplementing ad hoc path logic.
- PR preview environments deploy only for runtime app, compose, root E2E, dependency, Dockerfile/config, or preview-action changes. Preview-action changes include `.github/workflows/preview.yml`, `.github/workflows/maintenance.yml`, `.github/actions/setup-e2e-tests/action.yml`, `tools/pr_preview_lifecycle.py`, and `tools/_lib/dev/pr_preview_lifecycle.py`. App test-only and app Markdown changes still run CI and AC gates without consuming a Dokploy preview slot.
- Staging deploy is manual (`workflow_dispatch`) only; a manual dispatch always deploys staging, runs release-critical smoke/non-LLM E2E, and records the provider-backed AI/OCR regression against the dispatched release `version_ref`. The diff-based change classifier no longer scopes the staging deploy by changed paths — it remains the scoping mechanism for CI/PR gates. Normal staging deploys still run staging smoke and non-LLM E2E against the exact dispatched `version_ref`.
- Markdown outside the documented lightweight trees is treated as heavy; this prevents runtime-adjacent README or tooling documentation changes from being hidden by a global `*.md` skip.
- Standalone lint and AC traceability start immediately with change classification. Deterministic test and image jobs start after change classification, then backend shards, frontend build/typecheck, frontend Vitest coverage, frontend Playwright, frontend telemetry E2E, image build validation, tooling coverage, integration, and Tier-1 API E2E run in parallel. The `ac-behavioral-ratchet` job starts after the JUnit-emitting backend/frontend Vitest stages and feeds the same `finish` aggregate as the other merge gates. The `finish` job aggregates lint, AC traceability, the AC behavioral score ratchet, deterministic tests, image validation, coverage, and skipped heavy-job semantics so earlier job starts improve wall-clock throughput without weakening merge authority.
- 5-way parallel test sharding via `pytest-split`
- Each shard: `pytest --splits 5 --group N --splitting-algorithm=least_duration --durations-path ci/backend-test-durations.json`
- The committed duration seed lives at `apps/backend/ci/backend-test-durations.json`; each CI shard validates that it is present and non-trivial before pytest starts.
- Duration seed updates are reviewed repository changes, not runner-local cache writes or uploaded artifact side effects.
- Tooling/common coverage runs in parallel as `tooling-coverage`; `unified-coverage` downloads `coverage-tooling` and merges backend, frontend Vitest, common, and tools LCOV inputs post-run.
- `unified-coverage` and `ac-behavioral-ratchet` use the pinned Python runtime directly for repo-local stdlib scripts; the ratchet downloads only backend shard, backend integration, backend Tier-1, and frontend Vitest test-context artifacts.
- Coverage policy audited after backend, frontend, common, and tools LCOV reports exist
- Main-only Coveralls unified upload uses repository-root-relative backend + frontend + common + tools LCOV, matching the local unified calculation.
- Coveralls upload files strip branch records before upload so Coveralls reports the same line-only percentage as the deterministic unified coverage gate.
- PR CI does not call Coveralls and therefore cannot publish an external Coveralls status that disagrees with the local gate. Main push Coveralls upload is reporting-only and runs after local coverage gates pass.
- CI calls `tools/check_toolchain_contract.py` in lint before dependency installation and `tools/check_ci_metrics_contract.py` in lint before coverage jobs finish. Runtime versions and base images are owned by `toolchain.toml`, mirrored to local tool-manager files, and used by GitHub Actions, Dockerfiles, and `docker-compose.yml`.
- PR CI avoids Moon bootstrap in heavy runner jobs that execute direct `pytest` and `npm` commands. Backend shards, backend integration, Tier-1 API E2E, and the split frontend jobs use task-native commands directly so GitHub release CDN failures for optional Moon installation cannot mask deterministic code failures. Moon CLI availability and project graph coverage are static contracts over `.moon/toolchain.yml`, `moon.yml`, and app-level `moon.yml` files; runtime execution of Moon remains a local contributor responsibility and is not a PR merge gate unless a future workflow explicitly needs Moon semantics.
- PR CI dry-runs staging image builds before merge. The `container-images` job uses `docker/build-push-action` for both backend and frontend images with `push: false` on pull requests, then `finish` fails if that validation job fails.
- Image publication hygiene (#1277): the `container-images` job runs a fail-closed gitleaks scan over each component's Docker build context (`apps/<component>`, `--no-git --redact --exit-code 1`) BEFORE `docker/build-push-action`, so a secret that entered the build context cannot be baked into a published `:<sha>` image; the redacted finding stays visible in the job logs. The scheduled `GHCR SHA Retention` workflow then prunes only backend/frontend `:<sha>` package versions older than 28 days, never prunes `vX.Y.Z` release tags, preserves live staging/production deploy SHAs resolved from health `git_sha`/`version`, and fails closed before deletion if no live SHA exemption is available.
- Main and release-branch push CI, plus on-demand `workflow_dispatch`, publish SHA-tagged images (P1a, #879). Registry login and image push are guarded by `(github.event_name == 'push' && (github.ref == 'refs/heads/main' || startsWith(github.ref, 'refs/heads/release/'))) || github.event_name == 'workflow_dispatch'`; registry availability and authorization remain post-merge external-service risks, but Dockerfile, build-context, and build-argument errors are caught before merge.
- Frontend dependency installation uses `actions/setup-node@v6` with npm cache and deterministic `npm ci`. The lint job runs `npm run audit:prod` after install so production frontend dependency advisories fail before merge; the former duplicate audit in the frontend runtime job is removed, and dev-only advisories remain outside this production gate.
- GitHub JavaScript action runtime debt is closed: workflows use Node 24-native or composite external actions and no longer set `FORCE_JAVASCRIPT_ACTIONS_TO_NODE24`. This does not change the application toolchain `NODE_VERSION`; it only means GitHub-hosted JavaScript actions no longer need the forced-runtime migration flag. `common/testing/data/github-action-runtime.yaml` inventories every external `uses:` action consumed by workflows or local composite actions and requires the forced Node 20 metadata exception count to stay at zero. The workflow contract fails when a new action is not inventoried, when a forced-Node20 metadata action lacks an exception, or when the forced-runtime env is reintroduced after exceptions are empty.
- `astral-sh/setup-uv` cache saves are single-writer in CI: the `lint` job may save the shared uv cache, while parallel CI jobs and deployed-environment helper workflows restore without saving (`save-cache: false`). This preserves cache reads but avoids concurrent jobs racing to reserve the same setup-uv cache key.
- Production release tag builds and dry-runs verify that the target SHA already
  has a successful `main` CI `finish` result and a successful post-merge `staging`
  deployment, then run release lint and image promotion/validation. They do not
  rebuild images from source or rerun the container-backed `moon run :test`
  lifecycle in the release lane, maintaining the promote-not-rebuild consistency ladder
  where the exact same staging-validated image digest is promoted to production.
- The `finish` job appends a GitHub Step Summary from `tools/github_workflow_timing_summary.py` with queue delay, execution window, run wall time, longest completed job, and per-job durations.
- The `finish` job appends a coverage gate summary so reviewers can identify the authoritative local coverage gate.
- The `tooling-coverage` job uploads `coverage-tooling`; the `unified-coverage` job downloads it and uploads the `unified-coverage-context` artifact so reviewers can inspect raw line-count inputs instead of inferring failures from rounded percentages.
- CI observability artifacts are uploaded on success and failure for required test/deploy gates. Backend shards upload shard JUnit and LCOV, schema migrations upload Alembic logs and run context, `frontend-vitest` uploads Vitest JUnit and LCOV, `frontend-playwright` uploads browser reports/test-results, `frontend-telemetry-e2e` uploads telemetry E2E reports/test-results, AC traceability uploads gate status context with audit outputs, and environment workflows upload target SHA/URL/model/version context with E2E JUnit where available.
- Coveralls uploads are main-only reporting and do not block CI pass/fail when local deterministic gates pass.
- The repository ruleset must require the `finish` check, which aggregates local deterministic gates, rather than external reporting contexts.

**AC traceability audit artifact**:
- The current audit is generated in CI and uploaded as the `ac-test-traceability-audit` artifact.
- The AC traceability gate and audit builder share their default scan surface from
  `common/testing/test_surface.py`; do not maintain parallel hard-coded test
  directory lists in individual tools.
- The same artifact includes `reconciliation-audit.json` and
  `reconciliation-audit.md` as hard-gated EPIC-004 accuracy evidence for the
  `>=95%` accuracy, `<0.5%` false-positive, `<2%` false-negative, and
  10,000-transaction runtime targets.
- Routine PRs must not commit generated snapshot reports solely because ACs or test references changed.
- The retired checked-in archive inventory is retained in [issue #548](https://github.com/wangzitian0/finance_report/issues/548), with full text recoverable from git history before commit `64aa58c`.

> **Deploy-implementation bullets** (post-merge staging deploy health, release
> gate reclassification, the AI/OCR canary/audit-replay split, the post-merge
> staging AI/OCR gate, PR preview E2E, and production release dry-run) live in
> the deploy half: [common/runtime/ci-cd.md](../runtime/ci-cd.md#deploy-implementation).

The remaining higher-risk CI and post-merge optimization candidates are tracked
in the delivery-engine recommendation note instead of being mixed into routine
SSOT edits: [DELIVERY_ENGINE_RECOMMENDATIONS.md](../../docs/project/DELIVERY_ENGINE_RECOMMENDATIONS.md).

> **Local vs GitHub CI Parallelism**
>
> | Environment | Parallelism | Test Scope | Resource Usage |
> |-------------|-------------|------------|----------------|
> | **GitHub CI** | `-n auto` + `--splits 5` | ~20% tests per shard | Medium (ephemeral runners) |
> | **Local CI** | `-n 4` (fixed) | 100% tests | Controlled (shared machine) |
>
> This is intentional design, not inconsistency.

---

## Coverage Requirements

- Backend default local/pre-push coverage: enforced by `apps/backend/pyproject.toml`.
- Frontend local coverage: enforced by `apps/frontend/vitest.config.ts`.
- PR/main unified coverage: **no regression from `unified-coverage.json`** across backend, frontend, common, and tools.
- CI backend shards set `--cov-fail-under=0`; per-shard percentages are artifacts, while the merged unified job is the stable source of truth.
- Branch coverage may be collected locally and by backend pytest, but the unified gate and Coveralls uploads are line-only.
- See [coverage.md](./coverage.md) and [tdd.md](./tdd.md) for details

---


---

## Current Performance Metrics

**CI Pipeline (2025-02-02 baseline):**
- Total duration: **6m 24s** (Backend: 5m 52s, Frontend: 1m 30s)
- Test execution: 893 tests in 4m 47s (**320ms avg**)
- Caching: UV ✅ (2.9s), Next.js ✅, venv ✅

**CI Pipeline (2026-05-19 observed baseline):**
- Full heavy CI on `main`: **~7m 39s** before 6-way backend sharding.
- Longest backend shard: **~6m 23s** before 6-way backend sharding.
- Frontend build and coverage test: **~2m 32s** before npm cache standardization.
- Unified coverage: **~28s**.
- Lightweight docs/docs-workflow changes skip backend, frontend, and unified coverage; lint, AC traceability, and finish still run.

**CI Pipeline (2026-05-20 after 6-way backend sharding):**
- Full heavy CI execution window on `main`: **~5m 48s** after jobs start; run wall time may be higher when GitHub queues the run.
- Longest backend shard: **~4m 48s**.
- Unified coverage: **~42s**, including tooling coverage and reporting-only Coveralls uploads before the tooling/common coverage split.
- The timing summary reports queue delay separately from execution time so future regressions can distinguish runner capacity from workflow critical-path changes.

**CI Pipeline (2026-06-20 after Phase 1 frontend split):**
- Three observed split runs completed in **~4m 39s-4m 49s**.
- Slowest frontend split gate was **~2m 31s-2m 37s**, down from the old single `Frontend Build & Test` gate at **~4m 25s-4m 40s**.
- The critical path moved to backend shards plus coverage/ratchet fan-in; the slowest backend shards were **~3m 48s-3m 51s**.
- The tradeoff is higher aggregate frontend runner minutes because Playwright and telemetry still build independently before `npm run start`.

**CI Pipeline (Phase 2 backend/fan-in trim, 2026-06-20 observed baseline):**
- The 8-shard Phase 2 run proved fan-in trimming but did not prove duration-aware balancing because CI had no restored duration seed and `pytest-split` fell back to unseeded even splitting.
- Phase 2b corrects the backend fast path to 5 seeded shards using `apps/backend/ci/backend-test-durations.json`. Main CI run `27896401849` after PR #1288 completed successfully in about 4m 46s; backend shards finished in the 3m 31s-3m 50s band, frontend split gates stayed below the backend tail, unified coverage took 27s, and AC behavioral ratchet took 25s.
- `unified-coverage` runs repo-local stdlib Python scripts directly, and `ac-behavioral-ratchet` downloads only JUnit-producing test-context artifacts.

**CI Pipeline (#1767 remediation, 2026-07-12/13 observed baseline):** organic growth (more tests,
wider coverage scope) regressed the 2026-06-20 ~4m 46s baseline to **~8.5 min** by 2026-07-12
(#1767 F6) before any single change was to blame. #1767 Phase 3 (#1774, merged) parallelized the
`tooling-coverage` job with `pytest-xdist`: that job alone dropped from ~451s to ~249s.
- 16 successful main-push runs sampled after #1774 merged: **mean 5.8 min, median 6.0 min**
  (range 2.7 min-7.3 min; the 2.7 min low end is the lightweight docs-only path that skips
  backend/frontend/coverage). Independently measured from `gh run list` timestamps, not just the
  single-run snapshot #1774's own PR cited.
- Every `ci.yml` job now carries an explicit `timeout-minutes` (#1773, Phase 2) — previously none
  did, so a hang would have run to GitHub's 6h default before failing.
- The nightly `AI/OCR Audit Replay` gate (`audit-replay.yml`) was red for 5 consecutive nights
  (2026-07-07 through 2026-07-11) with its own alerting destroyed by the same timeout that killed
  the run (#1767 F1-F4) — fixed in #1767 Phase 0/1; 3 consecutive green nights confirmed since the
  fix (runs `29181331505`, `29182352126`, `29202152047`).


> **Deploy performance metrics** (post-merge staging, release image promotion)
> live in the deploy half: [common/runtime/ci-cd.md](../runtime/ci-cd.md#current-performance-metrics-deploy).

**Backend Test Parallelization:**

```bash
# In pyproject.toml
[tool.pytest.ini_options]
addopts = "-n 2"  # 2 workers for parallel execution
```

Options:
1. **Increase worker count**: `pytest -n auto` or `pytest -n 4` (limited by CPU cores)
2. **Split CI jobs**: Separate unit vs integration in GitHub Actions (1-2 min savings)

---

---

## Related

- [development.md](../meta/development.md) — Moon commands and local setup
- [environments.md](../runtime/environments.md) — Six environment overview
- [coverage.md](./coverage.md) — Unified coverage system
- [tdd.md](./tdd.md) — TDD workflow and coverage goals
- [common/runtime/ci-cd.md](../runtime/ci-cd.md) — the deploy half (staging/production workflows, smoke tests, deploy E2E gates)
