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
(marker expression, explicit node sets, parallelism). Workflows consume
selection at runtime via `tools/test_selection.py --stage <stage> --shell` —
they never restate test lists (the `preview.yml` whitelist retired by #1547
is the canonical counterexample).

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
`__main__` boundary raises `SystemExit(main())`. `gate_main_contract.py` is an
allowlist-free AST gate: every module-level `main` under `common/` and `tools/`
must use that exact contract, every common `check_*` command must call the
shared runner, malformed Python fails closed, and no historical debt baseline
can conceal a violation.

Baseline mutation is explicit and machine-checked by
`baseline_update_contract.py`. The `--update` / `--update-*` monotonic mutation
family (including specialized flags such as `--update-floor`) is reserved for
`raise-only` or `shrink-only` mutation. A command that can replace an entire
baseline must declare `BASELINE_UPDATE_MODE = "rewrite"` and expose the
deliberately louder `--rewrite-baseline` flag. The updater census recognizes both
`argparse` declarations and manual argument-membership checks, resolving simple
module-level string constants in both forms. Every `(module, mutation flag)`
command must map to a live test node that uses
`assert_regression_debt_refused` with non-vacuous debt and baseline-state
observers. The debt observer must depend on state beyond the baseline path, and
the baseline observer must read persisted contents (or a captured writer sink),
not merely check that the path exists. The proof invokes that updater's `main`
with the exact flag and proves the baseline remains unchanged. A new mutation
command therefore cannot be covered by a declaration, another flag's proof, an
unrelated test name, constant callbacks, or a happy-path call.

Top-level `tools/*.py` files are command boundaries, not implementation homes.
`tool_shim_contract.py` rejects a new entry point over 40 lines and requires
`data/fat-tool-baseline.json` to shrink whenever historical debt is re-homed.
The staging AI-OCR implementation now lives in
`staging_ai_ocr_gate_contract.py`, with replay-count data in
`data/staging-ai-ocr-replay-counters.json`; its workflow-facing tools file is a
thin compatibility shim. Local developer commands likewise share runtime and
container selection through `tools/_lib/dev/toolchain.py`, including consistent
`CONTAINER_RUNTIME` handling.

### Responsibility table

| Failure class | Owner |
|---|---|
| dependency missing / env wrong / config drift | `runtime` (its domain contract / check port) |
| test not selected / not executed / not reported | `testing` (this package) |
| assertion weak or wrong (covered but proves nothing) | the domain package's AC — `testing` only *exposes* it via ratchets |
| flaky test | `testing` (quarantine/retry policy), unless the runtime check is red |

---

# AC behavioral-evidence pipeline (spike)

A bare `pass` carries ~0 bits of information — it only says "no exception was
raised". Today an AC is counted "covered" if its id string appears in a
CI-executed file that contains *any* assertion token; this proves **presence**,
not **behavior**. This package adds a second, measured signal so a test can say
*how well* it pursued an AC, not just *that it ran*.

## The record

Each `(test, AC)` pair emits a five-field record:

| field        | axis | meaning |
|--------------|------|---------|
| `code`       | L2   | binary outcome (`pass`/`fail`/`skip`/`error`) — hard gate |
| `score`      | L3   | graded signal in `[0,1]` — ratcheted, never regressed |
| `metric`     | —    | **names the yardstick** the score was measured against |
| `provenance` | —    | where the number came from (`deterministic` / `golden_fixture@<ref>` / `live_llm`) |
| `comment`    | —    | human/agent-readable rationale (doubles as an eval record) |

`metric` + `provenance` are the **honesty anchor**: a score must be
`compare(actual, golden)`, not a hand-assigned grade. A self-assigned score is
just `assert True` moved up one level.

## The chain

```
test  --record_ac_evidence(record_property, ...)-->  junit-xml <property>
      --package-contract resolver----------------->  canonical trace_record property
      --tools/aggregate_ac_evidence.py-->            per-AC aggregate JSON
      --tools/check_ac_score_baseline.py-->          L2 + L3 ratchet gate
```

During Audit PR-A (#1906), package-scoped AC ids also shadow-emit the canonical
`TraceRecord` property. Tier and proof kind are resolved from the owning package
contract; callers provide only the measurement and cannot self-declare authority.
The TraceRecord assertion identity is the package-owned AC proof declaration,
not the caller's free-form metric label; the full metric remains hashed into the
evidence manifest.
Legacy EPIC ids remain without TraceRecord authority rather than being guessed
into the package graph.

- **L2 (always hard):** every baselined AC must show `code == pass` this run.
- **L3 (ratchet):** current score ≥ baseline; the baseline only moves up via
  `--update` (mirrors the existing `unified-coverage.json` line-coverage ratchet).
- **New ACs** are informational until adopted — each AC matures from soft to
  enforced on its own schedule. No big-bang migration of the ~1200 ACs.

### CI wiring (blocking, not a follow-up)

The ratchet is a **hard, only-goes-up CI gate** today, not a deferred spike:

- The dedicated `ac-behavioral-ratchet` job in `.github/workflows/ci.yml` waits
  on every test stage that emits junit (`backend`, `backend-integration`,
  `backend-e2e-tier1`, `frontend`), downloads their junit artifacts, runs
  `tools/aggregate_ac_evidence.py` to reduce them per AC, then runs
  `tools/check_ac_score_baseline.py` against the checked-in
  `common/testing/data/ac-score-baseline.jsonl`. It is a **separate** job — not part of
  `ac-traceability`.
- The `finish` aggregation job **requires** `ac-behavioral-ratchet` to succeed
  (both via `needs:` and an explicit `result != "success"` failure check) on the
  PR test path, so a baselined AC that regresses below its score, goes missing,
  or reports a non-`pass` `code` blocks the merge gate — exactly like the
  line-coverage ratchet.
- If no junit evidence reaches the job, the aggregate is empty and every
  baselined AC is reported as `missing`, which fails the gate: a lost or
  un-uploaded artifact cannot pass vacuously.

## Two consumers, one emission

The same emitted record feeds both a deterministic PR gate (stable subset) and a
post-merge eval dashboard (full score distribution, LLM noise tolerated) — the
split already modelled by `trust_mode` on the co-located `@ac_proof`
declarations and the derived critical-proof matrix rendered on demand from the
AC graph.
This is why a separate evaluation engine is unnecessary: the test harness *is*
the eval emitter.

## Anchored ACs (real end-to-end)

Each AC below emits a deterministic, measured score that the blocking ratchet
enforces:

- **AC4.1.4** (reconciliation description similarity) emits its measured
  similarity in `apps/backend/tests/reconciliation/test_reconciliation_scoring.py`.
- **AC8.16.1** (augmentation seam excludes superseded valuations) emits the
  corrected-only net-worth match in
  `apps/backend/tests/integration/test_augmentation_seam_e2e.py`.
- **AC-ledger.6.4** (double-entry posting balances debits == credits) emits the
  measured debit/credit imbalance of a multi-line salary entry posted through the
  real `post_journal_entry` path in
  `apps/backend/tests/ledger/test_accounting_equation.py`. This is the
  reference pattern for anchoring a flagship money journey to L2 + L3.

Seeded baseline: `common/testing/data/ac-score-baseline.jsonl` (sorted, line-oriented JSONL
with `merge=union` so independent ACs auto-merge — one AC per line — instead of
all ACs colliding in one central JSON object). Hermetic proof of the whole chain:
`tests/tooling/test_ac_evidence_pipeline.py`.

## Deliberately **out of scope** (follow-ups)

1. Deriving `code` from the actual test report via a `pytest_runtest_makereport`
   hook instead of trusting the in-body default.
2. A periodic mutation / golden-swap audit that verifies scores actually drop
   when behavior breaks (the real L3 proof).
3. Migrating additional ACs and front-end (vitest) emission.

## <a id="trusted-year-scenario"></a>TrustedYearScenario

`trusted_year.py` owns one deliberately small terminal scenario and its
independently authored `Decimal` oracle. The v0 entity contains one reviewed
bank statement with income, expense, and investment-purchase movements; one
brokerage position and selected market price; and one reviewed manual
valuation. It is test truth, not a second product capability registry or a new
transaction taxonomy.

One `pr_ci` behavioral proof must bind the scenario to one independent oracle
through explicit `scenario_id` and `oracle_kind` metadata. The integration path
uses existing authority boundaries: LLM-led classification for supported P&L
categories, a reviewed deterministic rule with explicit intent for the asset
movement, immutable extraction results, ledger decisions, valuation decisions,
and the frozen report-package lifecycle. Source-matrix expansion, deployed
replay, operator evidence, and broader proof-format deletion remain outside v0.

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
| `common/testing/fixtures/pdf/validators/pdf_validator.py` | Local structure validation |
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
the committed substitute for real PDFs in CI. Real statements remain local and
gitignored; if local analysis finds a layout drift, update the sanitized
contract and generator together.

### Commit Policy

Can be committed:

- `common/testing/fixtures/pdf/templates/*.yaml`
- analyzer, generator, validator, fake-data, and wrapper code
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
- `can_display_chinese()` checks whether registered fonts can render CJK text.

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
| Sanitized real-format contracts and generated-PDF parity checks | `tests/tooling/test_pdf_fixture_real_format_contract.py` |
| CLI branches and validator behavior | `tests/tooling/test_pdf_fixture_tooling_coverage.py` |
| E2E consumers | `tests/e2e/test_statement_full_journey.py`, `tests/e2e/test_brokerage_upload_to_portfolio_value.py`, `tests/e2e/test_four_asset_net_worth_golden_path.py`, `tests/e2e/test_personal_financial_report_package.py` |
