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
      --tools/aggregate_ac_evidence.py-->            per-AC aggregate JSON
      --tools/check_ac_score_baseline.py-->          L2 + L3 ratchet gate
```

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
  `docs/ssot/ac-score-baseline.jsonl`. It is a **separate** job — not part of
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

Seeded baseline: `docs/ssot/ac-score-baseline.jsonl` (sorted, line-oriented JSONL
with `merge=union` so independent ACs auto-merge — one AC per line — instead of
all ACs colliding in one central JSON object). Hermetic proof of the whole chain:
`tests/tooling/test_ac_evidence_pipeline.py`.

## Deliberately **out of scope** (follow-ups)

1. Deriving `code` from the actual test report via a `pytest_runtest_makereport`
   hook instead of trusting the in-body default.
2. A periodic mutation / golden-swap audit that verifies scores actually drop
   when behavior breaks (the real L3 proof).
3. Migrating additional ACs and front-end (vitest) emission.

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
| AC definitions | [EPIC-009](../../docs/project/EPIC-009.pdf-fixture-generation.md) |
| Analyzer, sanitizer, templates, generator registration, gitignore, and docs | `tests/tooling/test_pdf_fixture_epic009_behavior.py` |
| Source-specific generated PDFs, dates, and balances | `tests/tooling/test_pdf_fixture_parseable.py` |
| Sanitized real-format contracts and generated-PDF parity checks | `tests/tooling/test_pdf_fixture_real_format_contract.py` |
| CLI branches and validator behavior | `tests/tooling/test_pdf_fixture_tooling_coverage.py` |
| E2E consumers | `tests/e2e/test_statement_full_journey.py`, `tests/e2e/test_brokerage_upload_to_portfolio_value.py`, `tests/e2e/test_four_asset_net_worth_golden_path.py`, `tests/e2e/test_personal_financial_report_package.py` |
