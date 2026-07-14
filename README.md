# Finance Report

[![CI](https://github.com/wangzitian0/finance_report/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/wangzitian0/finance_report/actions/workflows/ci.yml)
[![Coverage Status](https://coveralls.io/repos/github/wangzitian0/finance_report/badge.svg?branch=main)](https://coveralls.io/github/wangzitian0/finance_report?branch=main)
[![Deploy Staging](https://github.com/wangzitian0/finance_report/actions/workflows/deploy.yml/badge.svg?branch=main)](https://github.com/wangzitian0/finance_report/actions/workflows/deploy.yml)
[![Docs](https://github.com/wangzitian0/finance_report/actions/workflows/docs.yml/badge.svg?branch=main)](https://github.com/wangzitian0/finance_report/actions/workflows/docs.yml)

Personal finance system for accurate, auditable asset reporting and generated
personal financial-report packages: double-entry bookkeeping, statement import,
reconciliation, reports, AI-assisted review, and portfolio tracking.

## Operating Model

Engineering truth is organized as:

```text
README -> EPIC -> AC -> test
```

- **README** is the project fact entry point: stable EPIC navigation, tracker
  entry points, and links to generated reports.
- **EPIC documents** in `docs/project/EPIC-*.md` describe scope and acceptance
  criteria.
- **AC homes**: a **migrated package** owns its ACs as `AC-<pkg>.<group>.<seq>`
  in that package's `contract.py` `roadmap` (aggregated by `meta`'s data layer,
  never mirrored back into an EPIC table — see
  [`common/meta/migration-standard.md`](common/meta/migration-standard.md)).
  Legacy, not-yet-migrated modules still materialize ACs from EPIC documents
  into the generated registries: `docs/ac_registry.yaml`,
  `docs/infra_registry.yaml`, plus explicit overrides in
  `docs/ac_registry_overrides.yaml`.
- **Tests** are the proof. A referenced AC is not enough; behavior must be
  asserted by real tests.

`vision.md` is intentionally different. It owns the product's north-star goal
and culture — the axioms, trade-off rules, and decision filter for ambiguous
product and architecture choices. It guides endless iteration, but it does not
own implementation status.

## Structure & SSOT Layers

The structure-level SSOT is visible from the README so new work can navigate
from project intent to executable proof without reading archive fragments.

| Layer | Owner | What It Shows | Proof / Guard |
|---|---|---|---|
| Project entry | `README.md` | EPIC map, tracker entry points, and proof commands | `tools/check_ac_index.py` |
| Goal & culture | `vision.md` | North-star goal, axioms, trade-off rules, and direction for ambiguous choices | Referenced by EPIC vision anchors |
| Project tracking | `docs/project/README.md` | EPIC directory and non-EPIC documentation ownership | Active markdown ownership sweep |
| EPIC scope | `docs/project/EPIC-*.md` | Scope, ACs, owned docs, known gaps | AC registries |
| AC registry | `docs/ac_registry.yaml`, `docs/infra_registry.yaml`, `docs/ac_registry_overrides.yaml` | Generated acceptance criteria inventory and explicit non-derived overrides | `tools/generate_ac_registry.py --check` |
| SSOT index | `docs/ssot/README.md`, `docs/ssot/MANIFEST.yaml` | Technical truth ownership map | `tools/check_ssot_ownership.py` |
| Testing proof | CI traceability artifact, `unified-coverage.json` | AC-to-test proof and coverage baseline | `tools/check_ac_index.py`, `tools/check_coverage_policy.py` |

Implementation facts should be code-owned where possible. Prose SSOT documents
explain rationale and link to code, tests, generated registries, or issues
rather than duplicating code behavior.

## Proof Snapshot

Do not hand-write generated counts in this README. AC totals, per-EPIC proof
percentages, and coverage floors are code-owned or report-owned facts that
change whenever registries, tests, or coverage baselines change.

Use these sources instead:

- Live local AC coverage: `python tools/analyze_test_ac_coverage.py --no-write --stdout`
- Optional regenerated AC coverage snapshot: `python tools/analyze_test_ac_coverage.py`
- Traceability gate: `python tools/check_ac_index.py`
- E2E EPIC closure gate: `python tools/check_e2e_epic_traceability.py`
- Coverage baseline data: `unified-coverage.json`
- Coverage policy owner: `common/meta/extension/coverage/policy.py`

The Coveralls badge is main-branch reporting only. Pull requests do not publish
Coveralls status contexts; merge readiness follows the `finish` check and the
committed `unified-coverage.json` baseline.

Important caveat: the current AC coverage analyzer excludes `_ac_stubs`,
trivial placeholder assertions, pure `pass`, and pure skipped tests from
covered counts. CI fails mandatory AC coverage that is missing,
placeholder-only, or stub-only.

## EPIC Map

This map is for navigation only. Its EPIC row set is CI-validated against
`docs/project/EPIC-*.md` by `tools/check_e2e_epic_traceability.py`. Project
status and AC proof counts should be read from EPIC documents, generated
registries, and generated reports rather than duplicated here.

| EPIC | Scope |
|---|---|
| [EPIC-001](docs/project/EPIC-001.phase0-setup.md) | Infrastructure & authentication |
| [EPIC-002](docs/project/EPIC-002.double-entry-core.md) | Double-entry bookkeeping core |
| [EPIC-003](docs/project/EPIC-003.statement-parsing.md) | Statement parsing |
| [EPIC-004](docs/project/EPIC-004.reconciliation-engine.md) | Reconciliation engine |
| [EPIC-005](docs/project/EPIC-005.reporting-visualization.md) | Reports & visualization |
| [EPIC-006](docs/project/EPIC-006.ai-advisor.md) | AI advisor |
| [EPIC-007](docs/project/EPIC-007.deployment.md) | Deployment |
| [EPIC-008](docs/project/EPIC-008.testing-strategy.md) | Testing strategy & E2E gates |
| [EPIC-010](docs/project/EPIC-010.observability-logging.md) | observability logging |
| [EPIC-011](docs/project/EPIC-011.asset-lifecycle.md) | Asset lifecycle |
| [EPIC-012](docs/project/EPIC-012.foundation-libs.md) | Foundation libraries |
| [EPIC-013](docs/project/EPIC-013.statement-parsing-v2.md) | Statement parsing v2 |
| [EPIC-014](docs/project/EPIC-014.ttd-transformation.md) | TDD/TTD transformation |
| [EPIC-015](docs/project/EPIC-015.processing-account.md) | Processing account |
| [EPIC-016](docs/project/EPIC-016.two-stage-review-ui.md) | Two-stage review UI |
| [EPIC-017](docs/project/EPIC-017.portfolio-management.md) | Portfolio management |
| [EPIC-018](docs/project/EPIC-018.ai-driven-pipeline.md) | AI-driven pipeline |
| [EPIC-019](docs/project/EPIC-019.event-driven-upload-to-report-ux.md) | Event-driven upload-to-report UX |
| [EPIC-020](docs/project/EPIC-020.framework-aware-personal-reporting.md) | Framework-aware personal financial reporting |
| [EPIC-021](docs/project/EPIC-021.application-ai-advisor.md) | Application-layer AI Advisor |
| [EPIC-022](docs/project/EPIC-022.everyday-user-ia.md) | Everyday-user information architecture |
| [EPIC-023](docs/project/EPIC-023.llm-provider-abstraction.md) | LLM provider abstraction (litellm) |
| [EPIC-024](docs/project/EPIC-024.frontend-observability.md) | Frontend browser observability |
| [EPIC-025](docs/project/EPIC-025.dry-ssot-simplification.md) | DRY/SSOT simplification (reporting, statements, FE contracts, tests) |
| [EPIC-026](docs/project/EPIC-026.ac-authority-tiers.md) | AC authority tiers (CODE-ONLY/CODE-LED/HU/LLM-LED/LLM-ONLY) and the tier-to-valid-proof matrix |

## EPIC Status (Generated)

EPIC completion is a **derived view** of the one AC-keyed graph, rendered on
demand from the AC registries and test reports, never hand-written and never
committed-materialized (a committed snapshot churns on every AC change). Render
it with `tools/generate_epic_status.py --stdout`. The four completion categories
are reported separately so a high coverage number cannot hide manual or
placeholder debt; mutable live CI/deploy run status is deliberately excluded.

<!-- BEGIN GENERATED: epic-status -->

> EPIC status is a DERIVED view of the one AC-keyed graph (see
> [`common/testing/tdd.md`](common/testing/tdd.md) "Cross-Cutting Index Artifacts"). The
> per-EPIC completion numbers are **not committed** here, because a committed
> snapshot churns on every AC change and is the merge-train false-sharing
> hotspot this model removes.
>
> Render the live table on demand:
>
> ```bash
> python tools/generate_epic_status.py --stdout
> ```
>
> It reports four **separate** completion categories — automated AC coverage,
> placeholder/stub debt, manual-gate debt, and blockers — never a single
> percent, derived from `docs/ac_registry.yaml`, `docs/infra_registry.yaml`, the
> AC coverage report, and `unified-coverage.json`. Consistency (no dangling /
> missing proof) is gated by `python tools/check_ac_index.py`; live CI and
> deploy run status are intentionally excluded.

<!-- END GENERATED: epic-status -->

Known proof-quality caveats:

- Placeholder and stub references do not count as covered; mandatory ACs fail
  CI when they are missing, placeholder-only, or stub-only.
- Manual-verification ACs need automation or an explicit manual-gate category.
  See [issue #454](https://github.com/wangzitian0/finance_report/issues/454).
- AC-to-EPIC mismatch audit output is generated by
  `python tools/audit_ac_epic_mismatches.py`; do not copy current mismatch
  counts into this README.
- README EPIC status and completion metrics are a derived view rendered on
  demand by `python tools/generate_epic_status.py --stdout`; the mutable numbers
  are not committed (they churn on every AC change), and the AC-graph
  consistency gate `python tools/check_ac_index.py` enforces no dangling/missing
  proof. See [issue #455](https://github.com/wangzitian0/finance_report/issues/455).

## Vision Tracking

Do not hand-maintain open/closed blocker lists here. GitHub issue state and
labels are the source of truth for current tracker status.

- Macro proof tracker: [#521](https://github.com/wangzitian0/finance_report/issues/521)
- Personal report package tracker:
  [#563](https://github.com/wangzitian0/finance_report/issues/563)
- Related live work is tracked with labels such as `flow: upload-to-report`,
  `flow: net-worth`, and `scope: valuation`.
- If a stable proof path is needed in docs, write a parseable matrix and attach
  a checker rather than copying issue state by hand.

## Core Proof Paths

Macro correctness is a DERIVED view of the one AC-keyed graph. Its hand-curated
outcome source is
[`common/testing/data/critical-proof-outcomes.yaml`](common/testing/data/critical-proof-outcomes.yaml)
(macro outcome -> owner EPICs + proof_ids); the proof paths come from the
co-located `@ac_proof` decorators. The matrix is rendered on demand by
`python tools/generate_critical_proof_matrix.py` (never committed) and validated
by `python tools/check_ac_index.py`; the single internal-consistency
gate `python tools/check_ac_index.py` fails on any dangling/missing link. This is
the README -> EPIC -> E2E contract. The EPIC -> AC -> test contract remains owned
by the generated AC registries and AC traceability reports.

The macro outcome set is closed and parseable:

| Outcome ID | Purpose |
|---|---|
| `personal-financial-report-package` | Generated personal report package with statements, schedules, notes, and source traceability |
| `asset-distribution-net-worth` | Asset distribution, liabilities, and as-of net worth |
| `monthly-income-spending` | Current-period income, expenses, and net income |
| `investment-performance` | Portfolio import, valuation, and performance proof path |
| `annualized-income-long-term` | Salary, dividends, ESOP/restricted holdings, and long-term income proof path |
| `source-ledger-report-traceability` | Source document -> ledger -> report traceability |

The checker enforces README -> EPIC -> E2E closure: this table must match the
matrix, owner EPICs must reverse-declare their outcomes, covered outcomes need
explicit E2E proof anchors, and partial/gap outcomes need an issue. The separate
E2E EPIC closure gate ensures the README EPIC map matches project EPIC files and
that E2E-like assets outside product roots are explicitly classified.

## Documentation Debt Tracked As Issues

- [#453](https://github.com/wangzitian0/finance_report/issues/453):
  Move code-owned SSOT facts into common packages or generated contracts.
- [#454](https://github.com/wangzitian0/finance_report/issues/454):
  Convert manual-verification ACs into automated tests or explicit manual gates.
- [#455](https://github.com/wangzitian0/finance_report/issues/455):
  Generate README EPIC status and completion metrics from registries and test
  reports.
- [#456](https://github.com/wangzitian0/finance_report/issues/456):
  Fix AC-to-EPIC mismatch and invalid test references.
- AC-to-EPIC mismatch and invalid test references are generated by
  `python tools/audit_ac_epic_mismatches.py` and
  `python tools/analyze_test_ac_coverage.py --no-write --stdout`.

## Quick Start

Host prerequisites:

- A POSIX shell: macOS Terminal, Linux, or WSL Ubuntu
- Bash, Git, and curl in that same shell
- Docker Desktop with WSL integration or Podman for backend/full tests, local
  infrastructure, and smoke tests

The project bootstrap command installs or verifies the repo-pinned user-space
toolchain: uv, Python, nvm/Node.js, Moon CLI, backend dependencies, frontend
dependencies, and pre-commit hooks.

```bash
git clone https://github.com/wangzitian0/finance_report.git
cd finance_report

bash tools/bootstrap.sh
moon run :dev
```

Windows developers should run project commands inside WSL Ubuntu. Windows
PowerShell, Git Bash, Scoop-installed Python/uv, and the Codex Windows runner do
not share PATH entries or Python/Node packages with WSL. From PowerShell, enter
the project through WSL explicitly:

```powershell
wsl.exe -d Ubuntu --cd /home/<user>/workspace/finance_report --exec /bin/bash -lc "bash tools/bootstrap.sh"
```

Open <http://localhost:3000>.

## Development Commands

```bash
moon run :dev              # Start local development environment
moon run :dev -- --backend # Backend only
moon run :dev -- --frontend # Frontend only

moon run :lint             # Lint all workspaces
moon run :lint -- --fix    # Lint and auto-fix where supported

moon run :test -- --smart  # Default local loop: changed-file/affected coverage mode
moon run :test -- --fast   # Fast TDD loop without coverage
moon run :test             # Full local confidence gate with coverage
moon run :test -- --e2e    # Root deployment E2E tests
moon run :test -- --backend-e2e # Backend Tier-1 API E2E tests

moon run :build            # Build frontend
moon run :clean            # Clean local resources
```

Local fast feedback is advisory. PR CI is the authoritative merge gate, and
PR Preview/staging/production provide deployed-environment proof. Use
risk-triggered escalation for accounting, reconciliation, schema, API, shared
tooling, Docker, workflow, environment, or deploy changes; see
`common/testing/ci-cd.md`.

See `common/meta/development.md` for environment details and `common/testing/ci-cd.md`
for CI gates.

## Architecture

```text
apps/
├── backend/     # FastAPI + SQLAlchemy + PostgreSQL
└── frontend/    # Next.js + TypeScript

common/          # The package model: per-domain packages (meta, testing, runtime,
                 # ledger, extraction, llm, ...) each owning its contract + roadmap ACs
tools/           # Command entry points that delegate to common libraries
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
| `python tools/analyze_test_ac_coverage.py --no-write --stdout` | Live local AC-to-test coverage report |
| [docs/agents/](docs/agents/) | Agent workflow and red-line rules |

## License

MIT
