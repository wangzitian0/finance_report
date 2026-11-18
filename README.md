# Finance Report

[![CI](https://github.com/wangzitian0/finance_report/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/wangzitian0/finance_report/actions/workflows/ci.yml)
[![Deploy Staging](https://github.com/wangzitian0/finance_report/actions/workflows/deploy.yml/badge.svg?branch=main)](https://github.com/wangzitian0/finance_report/actions/workflows/deploy.yml)
[![Docs](https://github.com/wangzitian0/finance_report/actions/workflows/docs.yml/badge.svg?branch=main)](https://github.com/wangzitian0/finance_report/actions/workflows/docs.yml)

Personal finance system for accurate, auditable asset reporting and generated
personal financial-report packages: double-entry bookkeeping, statement import,
reconciliation, reports, AI-assisted review, and portfolio tracking.

## Operating Model

Engineering truth uses a streamlined two-layer model:

```text
vision.md -> bounded-context invariants & tests -> user_cases_ssot.json -> UI / API / E2E
```

- **README** is the project entry point: EPIC navigation, governance checks,
  and local development commands.
- **Layer 1 — Bounded Contexts & Structural Boundaries** (`common/<pkg>/`,
  `apps/backend/src/<pkg>/`): each package owns its domain rules, verified by
  executable domain tests and structural boundary guards
  (`tools/check_app_boundary.py`, `tools/check_base_purity.py`,
  `tools/check_tier_imports.py`, `tools/check_public_orm_exports.py`).
- **Layer 2 — Business User Cases** (`common/meta/flows/user_cases_ssot.json`):
  owns the 47 end-to-end business user cases (`UC-01..UC-47` across 8 domains),
  binding UI routes, backend endpoints, and backend/frontend/E2E tests (see
  [`docs/reference/user-cases.md`](docs/reference/user-cases.md)).
- **EPIC documents** (`docs/project/EPIC-*.md`) retain historical goal stubs and
  architectural context as a closed, shrink-only directory.

`vision.md` is intentionally different. It owns the product's north-star goal
and culture — the axioms, trade-off rules, and decision filter for ambiguous
product and architecture choices. It guides endless iteration, but it does not
own implementation status.

## Structure & SSOT Layers

| Layer | Owner | What It Shows | Proof / Guard |
|---|---|---|---|
| Goal & culture | `vision.md` | North-star goal, axioms, trade-off rules, and direction for ambiguous choices | Decision filter |
| Bounded contexts & boundaries | `common/<pkg>/`, `apps/backend/src/<pkg>/` | Package specs (`readme.md`) and five-layer dependency/purity boundaries | `check_app_boundary.py`, `check_base_purity.py`, `check_tier_imports.py`, `check_public_orm_exports.py` |
| Business user cases | `common/meta/flows/user_cases_ssot.json` | 47 end-to-end business user cases (`UC-01..UC-47`) across 8 domains | `test_user_cases_consistency.py`, `userCasesConsistency.test.tsx` |
| Historical EPIC index | `docs/project/EPIC-*.md` | Closed, shrink-only goal stubs and design context | [EPIC Index](docs/project/README.md) |

Implementation facts live in code and executable tests rather than prose.

### LLM & Data-Driven Verification Guardrail

- **Persist real LLM outputs (`tests/fixtures/llm_cassettes/`)**: Generalization belongs to the LLM; committed cassettes freeze real provider responses to verify full-pipeline wiring. **Never hand-write LLM cassettes** — always record via real execution (`make llm-record` / `common/extraction/record_hf_cassettes.py`).
- **Zero-token deterministic PR CI (`github_ci.merge_authority`)**: Development/PR CI runs with `LLM_CASSETTE_MODE=replay` (zero network, zero API key) through the real extraction/conform/approval pipeline. Never bypass extraction post-processing when testing corpus replay.
- **Live-token Staging E2E, Smoke & 3-Statement Oracle (`staging_gate` / `scheduled_audit`)**: Deployed Staging hooks (`runtime-hooks.manifest.json`) run with real tokens (`AI_API_KEY`, `glm-5.3-flash`) to execute live E2E journeys, the 20-PDF 7-invariant 3-Statement Oracle (`tests/benchmarks/pdf_corpus_oracle.py`), and the Business Scenario Benchmark (`tests/benchmarks/run_financial_scenario_benchmark.py`).

See [`common/llm/readme.md#cassettes`](common/llm/readme.md#cassettes) and [`common/testing/ci-cd.md`](common/testing/ci-cd.md).

## EPIC Map

Historical index for navigation. Live tracker status lives in GitHub Issues and
CI outputs.

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
| [EPIC-026](docs/project/EPIC-026.ac-authority-tiers.md) | AC authority tiers (`CODE-ONLY/CODE-LED/HU/LLM-LED/LLM-ONLY`) and tier-import separation |

## Core Business Journeys

The 47 end-to-end business user cases live in [`common/meta/flows/user_cases_ssot.json`](common/meta/flows/user_cases_ssot.json) and are documented in [`docs/reference/user-cases.md`](docs/reference/user-cases.md). Six core financial outcomes anchor E2E and benchmark proof:

| Outcome ID | Purpose |
|---|---|
| `personal-financial-report-package` | Generated personal report package with statements, schedules, notes, and source traceability |
| `asset-distribution-net-worth` | Asset distribution, liabilities, and as-of net worth |
| `monthly-income-spending` | Current-period income, expenses, and net income |
| `investment-performance` | Portfolio import, valuation, and performance proof path |
| `annualized-income-long-term` | Salary, dividends, ESOP/restricted holdings, and long-term income proof path |
| `source-ledger-report-traceability` | Source document -> ledger -> report traceability |

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

moon run :build            # Build frontend
moon run :clean            # Clean local resources
```

Local fast feedback is advisory. PR CI is the authoritative merge gate, and
Staging and production provide deployed-environment proof. Use
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

common/          # Bounded-context domain specs (meta, testing, runtime,
                 # ledger, extraction, llm, ...), meta/flows/user_cases_ssot.json,
                 # and shared cross-cutting validators
tools/           # Command entry points that delegate to common libraries
docs/project/    # Historical EPIC stubs and project audit reports
```

## Key Links

| Resource | Purpose |
|---|---|
| [vision.md](vision.md) | Decision filter and long-term direction |
| [common/meta/flows/user_cases_ssot.json](common/meta/flows/user_cases_ssot.json) | 47 end-to-end business user cases SSOT ([docs/reference/user-cases.md](docs/reference/user-cases.md)) |
| [docs/project/](docs/project/) | Historical EPIC index and project audits |
| [common/readme.md](common/readme.md) | Bounded-context architecture and structural boundary guards |
| [docs/index.md](docs/index.md) | Documentation portal and system architecture |
| [docs/agents/](docs/agents/) | Agent workflow and red-line rules |

## License

MIT
