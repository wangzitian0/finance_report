# Finance Report

[![CI](https://github.com/wangzitian0/finance_report/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/wangzitian0/finance_report/actions/workflows/ci.yml)
[![Coverage Status](https://coveralls.io/repos/github/wangzitian0/finance_report/badge.svg?branch=main)](https://coveralls.io/github/wangzitian0/finance_report?branch=main)
[![Deploy Staging](https://github.com/wangzitian0/finance_report/actions/workflows/staging-deploy.yml/badge.svg?branch=main)](https://github.com/wangzitian0/finance_report/actions/workflows/staging-deploy.yml)
[![Docs](https://github.com/wangzitian0/finance_report/actions/workflows/docs.yml/badge.svg?branch=main)](https://github.com/wangzitian0/finance_report/actions/workflows/docs.yml)

Personal finance system for accurate, auditable asset reporting: double-entry
bookkeeping, statement import, reconciliation, reports, AI-assisted review, and
portfolio tracking.

## Operating Model

Engineering truth is organized as:

```text
README -> EPIC -> AC -> test
```

- **README** is the project fact entry point: stable EPIC navigation, tracker
  entry points, and links to generated reports.
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
| Project entry | `README.md` | EPIC map, tracker entry points, and generated proof links | `docs/analysis/test-ac-coverage-report.md` |
| Decision filter | `vision.md` | Direction for ambiguous product and architecture choices | Referenced by EPIC vision anchors |
| Project tracking | `docs/project/README.md` | EPIC directory and non-EPIC documentation ownership | Active markdown ownership sweep |
| EPIC scope | `docs/project/EPIC-*.md` | Scope, ACs, owned docs, known gaps | AC registries |
| AC registry | `docs/ac_registry.yaml`, `docs/infra_registry.yaml` | Generated acceptance criteria inventory | `tools/generate_ac_registry.py --check` |
| SSOT index | `docs/ssot/README.md`, `docs/ssot/MANIFEST.yaml` | Technical truth ownership map | `tools/check_ssot_ownership.py` |
| Testing proof | `docs/analysis/test-ac-coverage-report.md`, `unified-coverage.json` | Checked-in AC-to-test snapshot and coverage baseline | `tools/check_ac_traceability.py`, `tools/check_coverage_policy.py` |

Implementation facts should be code-owned where possible. Prose SSOT documents
explain rationale and link to code, tests, generated registries, or issues
rather than duplicating code behavior.

## Proof Snapshot

Do not hand-write generated counts in this README. AC totals, per-EPIC proof
percentages, and coverage floors are code-owned or report-owned facts that
change whenever registries, tests, or coverage baselines change.

Use these sources instead:

- Checked-in AC coverage snapshot: `docs/analysis/test-ac-coverage-report.md`
- Live local AC coverage: `python tools/analyze_test_ac_coverage.py --stdout`
- Traceability gate: `python tools/check_ac_traceability.py`
- Coverage baseline data: `unified-coverage.json`
- Coverage policy owner: `common/coverage/policy.py`

Important caveat: the current AC coverage analyzer excludes `_ac_stubs`,
trivial placeholder assertions, pure `pass`, and pure skipped tests from
covered counts. CI fails mandatory AC coverage that is missing,
placeholder-only, or stub-only.

## EPIC Map

This map is for navigation only. Project status and AC proof counts should be
read from EPIC documents, generated registries, and generated reports rather
than duplicated here.

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
| [EPIC-009](docs/project/EPIC-009.pdf-fixture-generation.md) | PDF fixture generation |
| [EPIC-010](docs/project/EPIC-010.signoz-logging.md) | SigNoz logging |
| [EPIC-011](docs/project/EPIC-011.asset-lifecycle.md) | Asset lifecycle |
| [EPIC-012](docs/project/EPIC-012.foundation-libs.md) | Foundation libraries |
| [EPIC-013](docs/project/EPIC-013.statement-parsing-v2.md) | Statement parsing v2 |
| [EPIC-014](docs/project/EPIC-014.ttd-transformation.md) | TDD/TTD transformation |
| [EPIC-015](docs/project/EPIC-015.processing-account.md) | Processing account |
| [EPIC-016](docs/project/EPIC-016.two-stage-review-ui.md) | Two-stage review UI |
| [EPIC-017](docs/project/EPIC-017.portfolio-management.md) | Portfolio management |
| [EPIC-018](docs/project/EPIC-018.ai-driven-pipeline.md) | AI-driven pipeline |

Known proof-quality caveats:

- Placeholder and stub references do not count as covered; mandatory ACs fail
  CI when they are missing, placeholder-only, or stub-only.
- Manual-verification ACs need automation or an explicit manual-gate category.
  See [issue #454](https://github.com/wangzitian0/finance_report/issues/454).
- AC-to-EPIC mismatch audit output lives in
  [docs/analysis/ac-epic-mismatch-report.md](docs/analysis/ac-epic-mismatch-report.md);
  do not copy current mismatch counts into this README.
- README EPIC metrics should eventually be generated or validated by CI. See
  [issue #455](https://github.com/wangzitian0/finance_report/issues/455).

## Vision Tracking

Do not hand-maintain open/closed blocker lists here. GitHub issue state and
labels are the source of truth for current tracker status.

- Macro proof tracker: [#521](https://github.com/wangzitian0/finance_report/issues/521)
- Related live work is tracked with labels such as `flow: upload-to-report`,
  `flow: net-worth`, and `scope: valuation`.
- If a stable proof path is needed in docs, write a parseable matrix and attach
  a checker rather than copying issue state by hand.

## Core Proof Paths

Macro correctness is owned by
[`docs/ssot/critical-proof-matrix.yaml`](docs/ssot/critical-proof-matrix.yaml)
and checked by `python tools/check_critical_proof_matrix.py`. This is the
README -> EPIC -> E2E contract. The EPIC -> AC -> test contract remains owned by
the generated AC registries and AC traceability reports.

The macro outcome set is closed and parseable:

| Outcome ID | Purpose |
|---|---|
| `asset-distribution-net-worth` | Asset distribution, liabilities, and as-of net worth |
| `monthly-income-spending` | Current-period income, expenses, and net income |
| `investment-performance` | Portfolio import, valuation, and performance proof path |
| `annualized-income-long-term` | Salary, dividends, ESOP/restricted holdings, and long-term income proof path |
| `source-ledger-report-traceability` | Source document -> ledger -> report traceability |

The checker enforces README -> EPIC -> E2E closure: this table must match the
matrix, owner EPICs must reverse-declare their outcomes, covered outcomes need
explicit E2E proof anchors, and partial/gap outcomes need an issue.

## Documentation Debt Tracked As Issues

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

bash scripts/bootstrap.sh
moon run :dev
```

Windows developers should run project commands inside WSL Ubuntu. Windows
PowerShell, Git Bash, Scoop-installed Python/uv, and the Codex Windows runner do
not share PATH entries or Python/Node packages with WSL. From PowerShell, enter
the project through WSL explicitly:

```powershell
wsl.exe -d Ubuntu --cd /home/<user>/workspace/finance_report --exec /bin/bash -lc "bash scripts/bootstrap.sh"
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
