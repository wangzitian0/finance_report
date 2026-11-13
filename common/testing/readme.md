# `testing` — the cross-cutting CI-governance layer

Every domain package owns its own semantic contract and (long-term) its own
unit/integration tests — `runtime` is simply the package whose domain is
environments/dependencies/CD. `testing` is the one package that is **not** a
domain peer: it sits above the packages and governs how their guarantees are
*executed and proven* in CI. Guarantees themselves are organized via ACs
(EPIC → AC → test); orchestration is organized via SSOT; this package owns the
machinery connecting the two (EPIC-008, issues #1556/#1557/#1558).

## Governance charter

### Execution matrix

[`matrix.py`](./matrix.py) is the SSOT for **test placement and selection**:
path→stage classification (whose generated view is
`common/testing/data/test-execution-matrix.yaml`, drift-gated by
`tests/tooling/test_execution_matrix_contract.py`) and per-stage selection
(marker expression, explicit node sets, parallelism). Callers consume
selection at runtime via `python -m common.testing.test_selection --stage <stage> --run`
(hook steps) or `--shell` (bash callers) —
they never restate test lists (the whitelist retired by #1547
is the canonical counterexample). Every JUnit-emitting workflow pytest command,
including the tooling evidence producer, is registered in
`WORKFLOW_PYTEST_CONTRACTS`; the conformance gate fails closed on either an
unregistered live invocation or a registration with no live command.

Hook steps run under `sh -lc` (dash on the runner): use
`python -m common.testing.test_selection ... --run`, never `eval` or a bash array (#2912).
`--run` starts `python -m pytest` with the stage marker and forces
`STRICT_E2E_GATES=1`. The stage env (`STAGE_ENV` in `matrix.py`) sets each env
name that skips a critical test, so the market data test runs (#2914).
`tests/tooling/test_hook_manifest.py` enforces these rules. It also reads each step of the manifest, fails a step of an unknown form,
and runs `--help` of each `python -m <module>` and `python <script>.py` step: the target must exit 0 and print text,
because a module without an `if __name__ == "__main__"` block exits 0 and runs no test (AC-testing.hook-main.2, #3031).

[`backend_shard.py`](./backend_shard.py) (CLI: `tools/backend_shard_files.py`)
decides which backend test files each CI shard runs: a seeded, file-level
`least_duration` split over `apps/backend/ci/backend-test-durations.json`
(AC-testing.ci-structure.13). Every `tests/**/test_*.py` file lands in exactly
one shard, so a shard collects only its own files instead of importing the
whole suite under `--cov-branch` (#2050). It is stdlib-only because the shard
runs it before dependency installation. Tier-1 API E2E keeps pytest-split's
item-level split over `ci/backend-tier1-test-durations.json`
(AC-testing.ci-structure.14), because it collects only four files.

### Package declaration protocol

Each domain package declares its own unit/integration test roots in its
`contract.py`; the matrix aggregates those declarations (same pattern as
ACRecord roadmaps feeding the AC registry). Unit/integration rows are
package-owned and conflict-free by construction. Rollout: #1558.

### Vision proof projection

A package-roadmap AC that directly backs product direction declares
`vision_anchor` in its owning `contract.py`. The vision proof matrix combines
those declarations through `common.meta.ac_vision_index` with the EPIC-owned
anchor declarations and real test references. An anchor absent from `vision.md`
fails closed; there is no separate hand-maintained package-to-vision registry.

### E2E extension layer

Root E2E specs cross packages, so no single package can declare them: their
rows live directly here (`matrix.E2E_ROWS`), one **named row per spec file**
with its external needs (`llm_provider`, `market_data`, `deployed_env`,
`state_sensitive`) and audit status. The pre-merge in-runner set is derived
(audited AND no needs) — an unaudited or dependent spec defaults to the
post-merge ladder and can never silently creep into the merge-blocking path.

The testing architecture strictly separates accounting mathematical verification
from deployed user journeys (#2318, #2370):
1. **Bench V2**: Pure accounting mathematical assertions and multi-period invariant
   checks ($\Delta = 0.00$ SGD), driven by `common/meta/flows/thirty_flows_ssot.json`.
   Fixture SHA-256 pins live in `common/testing/fixtures/benchmarks/manifest.yaml`
   (synced via `tools/sync_benchmark_fixtures.py`). Synthetic CSV generators in
   `common/testing/benchmarks/statement_generators.py` keep a zero-orphan contract with
   `cases/case_1.py`..`case_6.py`, executed via `tools/run_financial_scenario_benchmark.py`.
   It runs no multi-step user journey. Its only browser step is the read-only route
   check of Pillars 2 and 3 (`case_ui`): each route must load, log no console error,
   and show no developer jargon (`AC-testing.benchmarks.3`).
2. **Core Journey**: Physical user journeys on deployed environments, driven by
   `common/testing/data/core-journey-checkpoints.json` (U1 to U14) and published to
   the Core Journey Board.
Hybrid UI test suites between these two tiers are prohibited.

#### Stage Breakdown & Live 3-Statement Verification (`runtime-hooks.manifest.json`)

- **Stage 1 (`local.advisory`) & Stage 2 (`github_ci.merge_authority`)**: Offline deterministic replay (`LLM_CASSETTE_MODE=replay`, zero live LLM calls) plus offline `test_pdf_corpus_oracle.py` manifest and mathematical checks.
- **Stage 3 (`staging.release_validation` / `staging_gate` and `staging.provider_regression` / `scheduled_audit`)**: Live-token execution against `$INFRA2_HOOK_APP_URL` (with `AI_API_KEY` / `glm-5.3-flash` Vault-injected on the Staging VPS container; the CI hook runner requires no local `AI_API_KEY`). `runtime-hooks.manifest.json` lists the checks of each slot; `scheduled_audit` adds the **20-PDF 7-Invariant 3-Statement Oracle** and the **30-Flow Financial Scenario Benchmark**.
- **Stage 4 (`prod.release_integrity` / `smoke`)**: Read-only smoke (the `smoke` slot of `runtime-hooks.manifest.json`).

The root browser context records every HTTP 429 response through
`e2e_rate_limit.py`. Its pytest report hook fails the owning journey with a
bounded method/path diagnostic during either the call or teardown phase, while
preserving any earlier assertion failure. Query strings are never included in
the evidence. This makes exhausted shared-IP capacity attributable instead of
misreporting it as an authentication, business, or locator regression.

When a browser-based E2E journey fails (`#2745`), `tests/e2e/conftest.py`
captures three diagnostic files into
`test-results/e2e-failures/<sanitized-nodeid>/` before the page closes:
`screenshot.png` (full-page PNG), `page-text.txt` (visible body text truncated
to 4 KB with authentication headers and cookies redacted), and
`page-errors.txt` (`console.error` and `pageerror` entries with secrets
redacted). For path-scoped PR and local verification (`#2670`),
`matrix.select_touched_e2e` and `tools/test_selection.py --touched-files` map
changed `tests/e2e/**` specs and `E2E_ROWS` `frontend_paths` to the affected
non-LLM `staging_core_e2e` journeys.

Every idempotent GET request of `tests/e2e/test_twelve_month_journey.py` goes
through `tests/e2e/transport_retry.py` (`AC-testing.e2e-poll-reconnect.2`,
`#2911`). That includes the lookups of `approve_statement_with_fixture_review`:
the journey passes it a getter through the `get` parameter, and a journey that
passes none keeps `client.get`. After a `ReadError` or `RemoteProtocolError`,
the helper retries on a new connection, at most 3 times in a row. It never
retries a timeout, a refused connection, an HTTP error status or a POST
request. The journey prints the total as
`twelve-month journey: GET reconnects = N`, also when it fails. After the
target handshake, the session start of `tests/e2e/conftest.py` opens 6 new
connections to the health URL and prints one path-quality line
(`AC-testing.e2e-path-quality.1`). A line that starts with `WARNING` means that
a connection failed or that the connections reached more than one edge
location (the `cf-ray` suffix). A transport error in that run probably comes
from the client network, and the session continues. A line without `WARNING`
states the facts and means that the samples show no instability. It makes no
claim about the next minute. Example:
`e2e path quality: 6 new connections, 0 failed, edge location SIN`.

`approve_statement_with_fixture_review` first polls `GET /statements/{id}/runs`
once per second until no run is `requested` or `running`, for at most 240 s,
and only then posts an approval (`AC-testing.e2e-runs-wait.1`, `#2994`).
Without the wait, the approval answers 409 with `active_run_id` while the classify
run of the statement is active (up to 180 s). The scripts with a synchronous client
(`ScenarioBenchmarkRunner.approve_statement` and the PDF corpus oracle) call
`wait_for_statement_runs_sync`, the blocking twin of the same helper.

The Ping An journey matches each extracted row to the fixture event with the same
balance after (not the date). It counts the rows whose description differs, prints
`description fidelity: 2 of 15 rows differ from the fixture (known 2): ...` after the parse,
and fails when the count is above `PINGAN_KNOWN_DESCRIPTION_MISREADS`
(`AC-testing.e2e-description-fidelity.1`, `#2932`, `tests/e2e/description_fidelity.py`).
The vision model reads the interest description `账户结息` as `账户信息`, so the
disposition table holds that key as a known misread. A new misread fails the journey;
a better model lowers the count. No other journey passes a known count.

### Fast interception

The matrix is SSOT'd in this package — not in prose, not in workflow YAML —
because its enforcement point must be pre-merge at lint speed: code is
import-checked and contract-tested on every PR, while any other home can only
be reconciled after the fact.

### Shared gate primitives

`jsonl_baseline.py` owns canonical line-oriented baseline serialization and
the raise-only per-record merge. The AC-score and cassette-eval modules keep
their existing public bindings, parameterizing only their identifier and
collection keys. `ac_scan.py` likewise owns AC test-file discovery, reference
classification, and the shared stats record used by coverage analysis and both
traceability consumers. This prevents gate-specific copies from drifting while
leaving each gate's policy in its own module.

`gate_cli.py` is the shared command boundary for policy gates: it owns
repository-root selection, escaped GitHub Actions annotations, stable
pass/fail summaries, and integer status codes. New gate entry points use the
composable `main(argv: Sequence[str] | None = None) -> int` contract; only the
`__main__` boundary raises `SystemExit(main())`.

Top-level `tools/*.py` files are command boundaries, not implementation homes.
`tool_shim_contract.py` rejects a new entry point over 40 lines, rejects
pass-through `import X as X` re-exports in `tools/*.py`, and requires
`data/fat-tool-baseline.json` to shrink whenever historical debt is re-homed.

### Package-governance observation adapter

Retired in #2934 Wave B: `package_governance_observations.py` and the package detectors it joined are gone; the product guarantees they pinned stay covered by the behavior tests of each boundary.

### Responsibility table

| Failure class | Owner |
|---|---|
| dependency missing / env wrong / config drift | `runtime` (its domain contract / check port) |
| test not selected / not executed / not reported | `testing` (this package) |
| assertion weak or wrong (covered but proves nothing) | the domain package's AC — `testing` only *exposes* it via ratchets |
| flaky test | `testing` (quarantine/retry policy), unless the runtime check is red |

---

# AC behavioral-evidence pipeline (spike)

A scenario-bound `@ac_proof` emits a canonical `TraceRecord` property when the
test executes and passes.

## The chain

```
scenario-bound @ac_proof
      --pytest call-phase PASS-------------------->  canonical trace_record property
      --one registered post-proof consumer-------->  canonical observation property
      --tools/check_pr_ci_evidence.py------------->  exact repo/commit/run proof gate
```

### CI wiring

- The dedicated `ac-behavioral-ratchet` job ran the ci_tier reconciliation on
  every test stage that emitted junit (`backend`, `backend-integration`,
  `frontend`): it downloaded their junit artifacts and ran
  `tools/check_pr_ci_evidence.py`. #2934 Wave A retired the job; Wave B
  re-homes the reconciliation onto `infra2-sdk`.
- The `finish` aggregation job required the job to succeed (via `needs:` and an
  explicit `result != "success"` failure check) on the PR test path.
- Fail-closed rule that survives the retirement: missing junit evidence is a
  failure — a lost or un-uploaded artifact can never pass vacuously.

## Scenario-bound execution proof

`common.testing.executed_proof_plugin` observes
pytest's real call-phase result and emits `PASS` only after the call passed. The
existing `check_pr_ci_evidence` JUnit gate then requires the exact repository,
checked-out commit, GitHub run, scenario, proof declaration digest, and
testing authority. The run attempt may be earlier than the checker's own
(AC-testing.capability-proof.4, #2049): a partial "re-run failed jobs" keeps the
passing jobs' attempt-1 JUnit while the checker runs as attempt 2. A different
run, or an attempt newer than the checker's, never matches; the newest matching
attempt is the canonical record. Several matching records in one attempt are
legitimate (one per case of a parametrized proof).

A scenario may register one post-proof consumer on its pytest item when another
package must compose evidence only after that real call result exists. The
consumer receives the exact canonical executed-proof `TraceRecord` and may
return one canonical `OBSERVATION`, which is attached to the same JUnit
testcase. `@ac_proof(required_observation_kind=...)` makes that output mandatory
for GitHub merge-authority execution and includes the requirement in the proof
declaration digest for every execution. Local advisory execution may omit the
consumer because it cannot produce exact CI coordinates; an explicitly
registered local consumer is still validated. The consumer is never called for
failure, skip, or xfail; missing CI or duplicate registration, consumer failure,
non-observation output, and the wrong assertion kind fail the test run. This is
a lifecycle seam, not another proof or status entity.
Setup/teardown success, failure, skip/xfail, a static declaration, or a workflow
conclusion cannot create or satisfy that record.

## <a id="journey-board"></a>Journey Board

The journey board shows the core user journey for each staging revision (#2370).
The owner direction is "heavy board, light gates": the board shows outcomes and
blocks nothing. The production approver reads it; no job or ruleset requires it.

- **Checkpoint map** — `data/core-journey-checkpoints.json` defines checkpoints
  U1–U14 and, for each proof test, the checkpoints it proves in execution order.
  A checkpoint with no proof shows `not-covered` with its gap issue.
- **Test marks** — a proof test calls `tests/e2e/journey_checkpoint.checkpoint()`
  right after the assertions that prove a checkpoint. The call writes a JUnit
  property. A guard keeps the calls and the map in the same order
  (AC-testing.journey-board.5).
- **Record** — `journey_board.py build-record` turns the artifact of one staging
  AI/OCR gate run into one record: tested SHA, lane, run link, per-test outcome
  and per-checkpoint status. A missing gate, artifact or JUnit file gives a
  `not-run` or `no-evidence` record; it is never hidden. Records hold no amounts
  and no failure text.
- **Lanes** — `canary` runs in every staging deploy and blocks it on red.
  `core_journey` (the proof tests of the checkpoint map, as `file::test` nodes) runs in
  `audit-replay.yml` after every staging deploy; the deploy does not wait and
  the lane opens no alert issue. `audit_replay` runs weekly. A failed lane run is
  red; only the canary has a dependent job (AC-testing.journey-board.7).
- **Publish** — `.github/workflows/journey-board.yml` runs on `workflow_run` of
  Deploy and AI/OCR Audit Replay (an hourly schedule reconciles any run of the
  last 7 days that has no record), writes the record under `board/records/<sha>/`
  on `gh-pages`, and regenerates `board/index.json` and `board/fragment.html`.
  It is the only board writer; the gate workflows stay read-only.
- **Read** — `docs/board/index.html` loads the fragment and adds data age. A
  failed load shows a red "unavailable" message.
- **Release** — the `journey-board` job of `release.yml` prints the board row of
  the exact release SHA before the production approval prompt
  (`journey_board.py release-row`). Its result never blocks or skips the deploy
  (AC-testing.journey-board.8).

## <a id="trusted-year-scenario"></a>TrustedYearScenario

`trusted_year.py` owns one deliberately small terminal scenario and its
independently authored `Decimal` oracle. The v0 entity contains one reviewed
bank statement with income, expense, and investment-purchase movements; one
brokerage position and selected market price; and one reviewed manual
valuation. It is test truth, not a second product capability registry or a new
transaction taxonomy.

One `pr_ci` behavioral proof binds the scenario to one independent oracle
through explicit `scenario_id` and `oracle_kind` metadata. After its real pytest
call passes, the testing plugin emits one canonical `TraceRecord` observation;
the JUnit reconciliation gate rejects missing or stale execution coordinates.
The integration path uses existing authority boundaries: LLM-led classification
for supported P&L categories, a reviewed deterministic rule with explicit intent
for the asset movement, immutable extraction results, ledger decisions,
valuation decisions, and the frozen report-package lifecycle. Source-matrix
expansion, deployed replay, operator evidence, and broader proof-format deletion
remain outside v0.

---

## <a id="pdf-fixtures"></a>PDF Fixtures

> **SSOT Key**: `pdf_fixtures` (internalized here from the retired
> `docs/ssot/pdf-fixtures.md` per the package-migration standard
> ([`../meta/migration-standard.md`](../meta/migration-standard.md), step 3
> "SSOT internalized") — the `testing` package now owns the fixture code and
> the committed synthetic PDFs.)
> **Source of Truth** for synthetic PDF fixture commands, local-only real-PDF
> handling, committed template policy, and font fallback.

PDF fixture tooling generates synthetic bank and brokerage statements for
parsing, reconciliation, portfolio, report-package, and E2E tests. Real
statements are local inputs only; committed files contain code, fictional data,
and format metadata.

### Tool Layout

| Path | Role |
|---|---|
| `tools/generate_pdf_fixtures.py` | Command wrapper for fixture generation |
| `tools/analyze_pdf_fixture.py` | Command wrapper for local real-PDF analysis |
| `common/testing/fixtures/pdf/generate_pdf_fixtures.py` | Shared generation implementation |
| `common/testing/fixtures/pdf/analyzers/` | PDF format analysis and sanitized template extraction |
| `common/testing/fixtures/pdf/generators/` | Source-specific PDF generators |
| `common/testing/fixtures/pdf/templates/*.yaml` | Committed format templates |
| `common/testing/fixtures/pdf/data/fake_data.py` | Fictional transaction data |
| `common/testing/fixtures/pdf/input/` | Local real PDFs; gitignored |
| `common/testing/fixtures/pdf/output/` | Generated PDFs; gitignored |
| `common/testing/fixtures/pdf/generated/` | Committed generated PDF + expected-JSON pairs |

### Generate Test PDFs

```bash
python tools/generate_pdf_fixtures.py --source all
python tools/generate_pdf_fixtures.py --source dbs
python tools/generate_pdf_fixtures.py --source cmb
python tools/generate_pdf_fixtures.py --source mari
python tools/generate_pdf_fixtures.py --source moomoo
python tools/generate_pdf_fixtures.py --source futu
python tools/generate_pdf_fixtures.py --source pingan
python tools/generate_pdf_fixtures.py --source dbs --output /path/to/output/
```

Default output is
`common/testing/fixtures/pdf/output/{source}/test_{source}_{period}.pdf`.

### Analyze Real PDFs

Real bank or brokerage PDFs may contain sensitive data. Keep them under
`common/testing/fixtures/pdf/input/`, which is gitignored and local only.

```bash
python tools/analyze_pdf_fixture.py \
  --input common/testing/fixtures/pdf/input/real_dbs_statement.pdf \
  --output common/testing/fixtures/pdf/templates/dbs_template.yaml \
  --source dbs
```

Review generated YAML before committing. Templates may include page size,
margins, font metadata, table columns, column widths, alignment, and text
element positions. Templates must not include account numbers, customer names,
real transaction payloads, or real balances.

Templates also carry a `real_format_contract` block. This block is sanitized
format metadata only: source ID, tolerances, table column names and widths,
source-specific date regex, currency marker, and required key phrases. It is
the committed stand-in for real PDFs in CI. CI generates the DBS statement and
checks the PDF against its block (page size, headers, date and currency
markers, key phrases, minimum rows); the other blocks are checked only against
their own template columns. Real statements remain local and gitignored; if
local analysis finds a layout drift, update the sanitized contract and
generator together.

### Commit Policy

Can be committed:

- `common/testing/fixtures/pdf/templates/*.yaml`
- analyzer, generator, fake-data, and wrapper code
- thin local README files that point here

Cannot be committed:

- real PDFs under `input/`
- generated PDFs under `output/`, unless a future AC explicitly changes that
  policy
- copied sensitive values from real statements

### Font Fallback

`common/testing/fixtures/pdf/generators/font_utils.py` owns non-English font
handling:

- `register_chinese_fonts()` detects and registers available CJK fonts.
- `get_safe_font()` falls back to Helvetica when a requested font is missing.

Known search paths include macOS system CJK fonts, Linux WQY/AR LLM-ONLY fonts, and
Windows SimSun/SimHei fonts. CMB and Pingan generators use Chinese headers when
supported and fall back to English text when no suitable font is available.
Fictional transaction descriptions stay English to keep generated PDFs portable.

Quick check:

```bash
python -c "from common.testing.fixtures.pdf.generators.font_utils import register_chinese_fonts; print(register_chinese_fonts())"
```

The command prints a registered font name such as `ChineseFont`, or `None` when
the platform must use fallback text.

### Proof

| Contract | Proof owner |
|---|---|
| AC definitions | [`common/testing/contract.py`](../../common/testing/contract.py) roadmap groups 1-8 (was EPIC-009; the EPIC file was deleted by #1719) |
| Analyzer, sanitizer, templates, generator registration, gitignore, and docs | `tests/tooling/test_pdf_fixture_epic009_behavior.py` |
| Source-specific generated PDFs, dates, and balances | `tests/tooling/test_pdf_fixture_parseable.py` |
| Sanitized real-format contracts; the generated DBS PDF against its contract | `tests/tooling/test_pdf_fixture_real_format_contract.py` |
| CLI branches and analyzer behavior | `tests/tooling/test_pdf_fixture_tooling_coverage.py` |
| E2E consumers | `tests/e2e/test_statement_full_journey.py`, `tests/e2e/test_brokerage_upload_to_portfolio_value.py`, `tests/e2e/test_four_asset_net_worth_golden_path.py`, `tests/e2e/test_personal_financial_report_package.py` |
