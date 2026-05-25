# Finance Report

Personal finance system for accurate, auditable asset reporting: double-entry
bookkeeping, statement import, reconciliation, reports, AI-assisted review, and
portfolio tracking.

## Operating Model

Engineering truth is organized as:

```text
README -> EPIC -> AC -> test
```

- **README** is the project fact entry point: current EPIC map, proof status,
  open blockers, and links to generated reports.
- **EPIC documents** in `docs/project/EPIC-*.md` describe scope and acceptance
  criteria.
- **AC registries** are generated from EPIC documents:
  `docs/ac_registry.yaml` and `docs/infra_registry.yaml`.
- **Tests** are the proof. A referenced AC is not enough; behavior must be
  asserted by real tests.

`vision.md` is intentionally different. It is a decision filter for ambiguous
product and architecture choices. It guides endless iteration, but it does not
own implementation status.

## Structure & SSOT Layers

The structure-level SSOT is visible from the README so new work can navigate
from project intent to executable proof without reading archive fragments.

| Layer | Owner | What It Shows | Proof / Guard |
|---|---|---|---|
| Project entry | `README.md` | EPIC map, current proof snapshot, blocker issues | `docs/analysis/test-ac-coverage-report.md` |
| Decision filter | `vision.md` | Direction for ambiguous product and architecture choices | Referenced by EPIC vision anchors |
| Project tracking | `docs/project/README.md` | EPIC directory and non-EPIC documentation ownership | Active markdown ownership sweep |
| EPIC scope | `docs/project/EPIC-*.md` | Scope, ACs, owned docs, known gaps | AC registries |
| AC registry | `docs/ac_registry.yaml`, `docs/infra_registry.yaml` | Generated acceptance criteria inventory | `scripts/generate_ac_registry.py --check` |
| SSOT index | `docs/ssot/README.md`, `docs/ssot/MANIFEST.yaml` | Technical truth ownership map | `scripts/check_ssot_ownership.py` |
| Testing proof | `docs/analysis/test-ac-coverage-report.md`, `unified-coverage.json` | Current AC-to-test and coverage evidence | `scripts/check_ac_traceability.py`, `scripts/coverage_policy.py` |

Implementation facts should be code-owned where possible. Prose SSOT documents
explain rationale and link to code, tests, generated registries, or issues
rather than duplicating code behavior.

## Current Proof Snapshot

Generated sources:

- AC coverage report: `docs/analysis/test-ac-coverage-report.md`
- Coverage baseline: `unified-coverage.json`
- Coverage policy owner: `scripts/coverage_policy.py`

Current generated numbers:

| Metric | Current |
|---|---:|
| Registered ACs | 983 |
| ACs with real test-candidate references | 744 / 983 (75.7%) |
| Registered ACs without real test reference | 239 |
| Stub-only AC placeholders | 215 |
| Invalid AC refs in real tests | 0 |
| Unified coverage floor | 94.38% |
| Backend / Frontend / Scripts coverage floors | 98.89% / 91.95% / 86.43% |

Important caveat: the current AC coverage analyzer excludes `_ac_stubs` and
trivial placeholder assertions from covered counts. Remaining proof-quality
hardening is tracked in
[issue #452](https://github.com/wangzitian0/finance_report/issues/452).

## Core Proof Paths

The brokerage PDF to asset-report path is the current north-star proof slice for
upload-to-report correctness.

| Product path step | EPIC owner | AC owner | Executable proof | CI tier |
|---|---|---|---|---|
| Upload Moomoo/Futu brokerage PDF through `/api/statements/upload` | [EPIC-008](docs/project/EPIC-008.testing-strategy.md) / [EPIC-013](docs/project/EPIC-013.statement-parsing-v2.md) | AC8.13.10 | `test_multi_brokerage_pdf_upload_imports_positions_and_updates_latest_portfolio_value` | Post-merge staging AI/OCR gate |
| Background parse detects brokerage payload and imports positions | [EPIC-017](docs/project/EPIC-017.portfolio-management.md) | AC17.4.7 / AC17.5.4 / AC8.13.10 | `test_parse_statement_background_imports_brokerage_positions` | Backend shard |
| Statement-scoped import creates holdings | [EPIC-017](docs/project/EPIC-017.portfolio-management.md) | AC17.4.6 / AC8.13.10 | `test_statement_import_flows_to_holdings_and_balance_sheet` | Backend shard |
| Imported holdings affect balance sheet value | [EPIC-005](docs/project/EPIC-005.reporting-visualization.md) / [EPIC-017](docs/project/EPIC-017.portfolio-management.md) | AC17.5.4 / AC8.13.10 | `test_statement_import_flows_to_holdings_and_balance_sheet` | Backend shard |
| User completes import and reaches portfolio value | [EPIC-017](docs/project/EPIC-017.portfolio-management.md) | AC17.8.1 / AC17.8.2 / AC17.8.4 | `AC17.8.1 AC17.8.2 AC17.8.4 completes parsed statement import and portfolio value navigation` | Frontend test |

Detailed EPIC/AC/test ownership for this path lives in
[EPIC-017](docs/project/EPIC-017.portfolio-management.md#brokerage-pdf-to-asset-report-proof-matrix);
the provider-backed gate is owned by
[EPIC-008](docs/project/EPIC-008.testing-strategy.md#tier-3-e2e-implementation).

## EPIC Map

Completion below separates project status from proof status. "AC proof" is from
the generated AC coverage report and should not be hand-edited without
refreshing the report.

| EPIC | Scope | Project status | AC proof |
|---|---|---|---:|
| [EPIC-001](docs/project/EPIC-001.phase0-setup.md) | Infrastructure & authentication | Complete with deferred debt | 19 / 29 (65.5%) |
| [EPIC-002](docs/project/EPIC-002.double-entry-core.md) | Double-entry bookkeeping core | Complete | 52 / 59 (88.1%) |
| [EPIC-003](docs/project/EPIC-003.statement-parsing.md) | Statement parsing | Complete, TDD aligned | 42 / 47 (89.4%) |
| [EPIC-004](docs/project/EPIC-004.reconciliation-engine.md) | Reconciliation engine | Complete, TDD aligned | 34 / 39 (87.2%) |
| [EPIC-005](docs/project/EPIC-005.reporting-visualization.md) | Reports & visualization | Complete, with investment metric gaps | 32 / 36 (88.9%) |
| [EPIC-006](docs/project/EPIC-006.ai-advisor.md) | AI advisor | Complete | 52 / 63 (82.5%) |
| [EPIC-007](docs/project/EPIC-007.deployment.md) | Deployment | Complete, manual-gate heavy | 6 / 39 (15.4%) |
| [EPIC-008](docs/project/EPIC-008.testing-strategy.md) | Testing strategy & E2E gates | Core complete | 71 / 93 (76.3%) |
| [EPIC-009](docs/project/EPIC-009.pdf-fixture-generation.md) | PDF fixture generation | Complete, manual-gate heavy | 0 / 37 (0.0%) |
| [EPIC-010](docs/project/EPIC-010.signoz-logging.md) | SigNoz logging | Complete, manual-gate heavy | 0 / 21 (0.0%) |
| [EPIC-011](docs/project/EPIC-011.asset-lifecycle.md) | Asset lifecycle | In progress (P0 complete) | 38 / 38 (100.0%) |
| [EPIC-012](docs/project/EPIC-012.foundation-libs.md) | Foundation libraries | In progress | 52 / 62 (83.9%) |
| [EPIC-013](docs/project/EPIC-013.statement-parsing-v2.md) | Statement parsing v2 | Complete | 60 / 60 (100.0%) |
| [EPIC-014](docs/project/EPIC-014.ttd-transformation.md) | TDD/TTD transformation | In progress | 0 / 6 (0.0%) |
| [EPIC-015](docs/project/EPIC-015.processing-account.md) | Processing account | Complete, TDD aligned | 31 / 31 (100.0%) |
| [EPIC-016](docs/project/EPIC-016.two-stage-review-ui.md) | Two-stage review UI | Planned / active foundation | 159 / 217 (73.3%) |
| [EPIC-017](docs/project/EPIC-017.portfolio-management.md) | Portfolio management | Planned / partially implemented | 82 / 82 (100.0%) |
| [EPIC-018](docs/project/EPIC-018.ai-driven-pipeline.md) | AI-driven pipeline | In progress | 14 / 24 (58.3%) |

Known proof-quality caveats:

- Placeholder and stub references do not count as covered, but remaining stub
  debt still leaves EPIC-007, EPIC-009, EPIC-010, EPIC-014, EPIC-016, and
  EPIC-018 proof weaker than their project status. See
  [issue #452](https://github.com/wangzitian0/finance_report/issues/452).
- Manual-verification ACs need automation or an explicit manual-gate category.
  See [issue #454](https://github.com/wangzitian0/finance_report/issues/454).
- Invalid AC references are currently zero; the AC-to-EPIC mismatch audit
  reports zero actionable mismatches and tracks fixture-only fake IDs separately
  in [docs/analysis/ac-epic-mismatch-report.md](docs/analysis/ac-epic-mismatch-report.md).
- README EPIC metrics should eventually be generated or validated by CI. See
  [issue #455](https://github.com/wangzitian0/finance_report/issues/455).

## Current Vision Blockers

Minimum blocker set for a fresh user to reach the accurate-dashboard journey:

1. North-star PDF upload to accurate net worth: `wangzitian0/finance_report#444`

Recently resolved blockers:

- Brokerage buy/sell/dividend investment accounting: `wangzitian0/finance_report#393`
- Source-type trust hierarchy and no-downgrade promotion: `wangzitian0/finance_report#395`
- Account-level statement coverage and balance continuity: `wangzitian0/finance_report#396`
- Processing account sidebar/status: `wangzitian0/finance_report#367`

## Documentation Debt Tracked As Issues

- [#452](https://github.com/wangzitian0/finance_report/issues/452):
  Harden AC traceability against stub and placeholder tests.
- [#453](https://github.com/wangzitian0/finance_report/issues/453):
  Move code-owned SSOT facts into common packages or generated contracts.
- [#454](https://github.com/wangzitian0/finance_report/issues/454):
  Convert manual-verification ACs into automated tests or explicit manual gates.
- [#455](https://github.com/wangzitian0/finance_report/issues/455):
  Generate README EPIC status and completion metrics from registries and test
  reports.
- AC-to-EPIC mismatch and invalid test references:
  [docs/analysis/ac-epic-mismatch-report.md](docs/analysis/ac-epic-mismatch-report.md).

## Quick Start

```bash
git clone https://github.com/wangzitian0/finance_report.git
cd finance_report

moon run :setup
moon run :dev
```

Open <http://localhost:3000>.

## Development Commands

```bash
moon run :dev              # Start local development environment
moon run :dev -- --backend # Backend only
moon run :dev -- --frontend # Frontend only

moon run :lint             # Lint all workspaces
moon run :lint -- --fix    # Lint and auto-fix where supported

moon run :test             # Full tests with coverage
moon run :test -- --fast   # Fast TDD loop without coverage
moon run :test -- --smart  # Changed-file coverage mode
moon run :test -- --e2e    # E2E tests

moon run :build            # Build frontend
moon run :clean            # Clean local resources
```

See `docs/ssot/development.md` for environment details and `docs/ssot/ci-cd.md`
for CI gates.

## Architecture

```text
apps/
├── backend/     # FastAPI + SQLAlchemy + PostgreSQL
└── frontend/    # Next.js + TypeScript

scripts/         # CI, coverage, registry, fixture, and lifecycle tools
docs/project/    # EPICs and project audit reports
docs/ssot/       # Rationale docs that link to code owners and proof tests
```

Code-owned facts should live in code or generated contracts, not prose. The
migration path is tracked in
[issue #453](https://github.com/wangzitian0/finance_report/issues/453).

## Key Links

| Resource | Purpose |
|---|---|
| [vision.md](vision.md) | Decision filter and long-term direction |
| [docs/project/](docs/project/) | EPIC documents and project audits |
| [docs/ssot/](docs/ssot/) | Rationale docs, code-owner links, proof references |
| [docs/analysis/test-ac-coverage-report.md](docs/analysis/test-ac-coverage-report.md) | Generated AC-to-test coverage report |
| [docs/agents/](docs/agents/) | Agent workflow and red-line rules |

## License

MIT
