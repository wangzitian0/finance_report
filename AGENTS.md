# Finance Report AI Agent Behavioral Guidelines

> **Prohibition**: AI may NOT modify this file without explicit authorization.
> **Checklist**: When you think you have completed a task, you need to check this file line by line to make sure you have met all the requirements.
> **English**: All code, PRs, commits, and reports must be in English; optional translated documentation files (e.g., *_ZH.md, *_CN.md) are allowed as non-authoritative copies.

---

## 🚨 Security & Red Lines (CRITICAL)

- **NEVER** use float for monetary amounts (**MUST** use `Decimal`).
- **NEVER** commit sensitive files (`.env`, `*.pem`, credentials).
- **NEVER** skip entry balance validation or post entries without accounting equation check.
- **NEVER** use direct `fetch()` in frontend; **MUST** use `lib/api.ts` wrapper.
- **NEVER** create `sa.Enum` without an explicit `name="..."` parameter.

---

## 🧭 Wiki Entry Map (Level 0/1)

**Level 0 Entry**: `AGENTS.md` (you are here)

**Level 1 Entries (by purpose)**
1. **Global Project Overview** → [README.md](README.md)
2. **Project Target (North Star)** → [target.md](target.md)
3. **Technical Truth / SSOT** → [docs/ssot/README.md](docs/ssot/README.md)
4. **Project Tracking / EPIC** → [docs/project/README.md](docs/project/README.md)

**Supplementary Entries**
- **Agent Skills** → [.opencode/skills/](.opencode/skills/)
- **Copilot Instructions** → [.github/copilot-instructions.md](.github/copilot-instructions.md)

**Reading Order (10-minute overview)**
1. [target.md](target.md) — Macro goals and decision criteria
2. [README.md](README.md) — Tech stack, quick start commands
3. [docs/ssot/README.md](docs/ssot/README.md) → Start with [schema.md](docs/ssot/schema.md)
4. [.opencode/oh-my-opencode.json](.opencode/oh-my-opencode.json) — Agent configurations

**Routing Rules (where to go when)**
- Need to understand business logic → [target.md](target.md)
- **Need environment setup / moon commands** → [docs/ssot/development.md](docs/ssot/development.md)
- Need to write code → [.opencode/skills/](.opencode/skills/) + SSOT files
- Need data model reference → [docs/ssot/](docs/ssot/)
- Need to track current work → [docs/project/](docs/project/)

---

## 🛠️ Environment & Automation (Moon)

**DO NOT manual check environment** (e.g., `docker ps`). Use `moon` to manage lifecycles.

- **Dev**: `moon run backend:dev` (FastAPI + DB), `moon run frontend:dev` (Next.js)
- **Test**: `moon run backend:test` (Auto-DB lifecycle + Integrated tests)
- **Quality**: `moon run :lint` (Check all), `moon run backend:format` (Ruff)
- **Proof**: `moon run :smoke` (E2E against local/remote)

*Reference: [docs/ssot/development.md](docs/ssot/development.md)*

---

## 🔍 Debugging & Observability

**Use `scripts/debug.py` for unified debugging** across all environments.

### Environment Detection

The debug tool automatically detects your environment:
- **Local/CI**: Uses Docker logs directly (fast)
- **Staging/Production**: Uses SSH + Docker logs or SigNoz (centralized)

### Common Commands

```bash
# View logs (auto-detects environment)
python scripts/debug.py logs backend
python scripts/debug.py logs frontend --tail 100
python scripts/debug.py logs backend --follow

# Specify environment explicitly
python scripts/debug.py logs backend --env staging
python scripts/debug.py logs frontend --env production

# Check service status (last 20 lines)
python scripts/debug.py status backend --env staging

# List all container names for an environment
python scripts/debug.py containers --env production

# View via SigNoz (staging/production only)
python scripts/debug.py logs backend --env production --method signoz
```

### Container Naming Patterns

| Environment | Backend | Frontend | Postgres | Redis |
|-------------|---------|----------|----------|-------|
| Local/CI | `finance-report-backend` | `finance-report-frontend` | `finance-report-db` | `finance-report-redis` |
| Staging | `finance-report-backend-staging` | `finance-report-frontend-staging` | `finance-report-db-staging` | `finance-report-redis-staging` |
| Production | `finance-report-backend` | `finance-report-frontend` | `finance-report-db` | `finance-report-redis` |
| PR (#47) | `finance-report-backend-pr-47` | `finance-report-frontend-pr-47` | `finance-report-db-pr-47` | `finance-report-redis-pr-47` |

### SigNoz Integration

For staging/production, structured logs are shipped to SigNoz via OTLP:

- **Staging**: `https://signoz-staging.zitian.party`
- **Production**: `https://signoz.zitian.party`

Query logs by service name:
```
service_name = "finance-report-backend"
```

See [docs/ssot/observability.md](docs/ssot/observability.md) for OTLP configuration details.

### Remote Debugging (SSH)

For operations not covered by `debug.py`, SSH access is available:

```bash
# SSH into VPS (read-only inspection recommended)
ssh root@$VPS_HOST

# Check container status
docker ps --filter name=finance-report

# View logs directly
docker logs finance-report-backend --tail 50
docker logs finance-report-backend -f

# Restart container (use with caution)
docker restart finance-report-backend
```

**IMPORTANT**: Prefer `debug.py` over direct SSH. Direct modifications on VPS are discouraged—deploy via CI instead.

---

## 📌 Core Domain Context

**Read [target.md](target.md) for macro goals and decision criteria. Key points:**

### Accounting Equation (MUST satisfy)
```
Assets = Liabilities + Equity + (Income - Expenses)
```

### Reconciliation Thresholds
| Score | Action |
|-------|--------|
| ≥ 85 | Auto-accept |
| 60-84 | Review queue |
| < 60 | Unmatched |

### Precision Requirements
- **Reconciliation tolerance**: 0.1 USD
- **Statistics tolerance**: 1%

---

## 🛠️ Problem Solving Framework (STAR)

AI must use this cascade structure before processing tasks:

### 1. Situation (Context Assessment)
- **Anchor Project**: Bind to a project in `docs/project/`
- **Current State**: Describe system status and problem impact
- **Truth Check**: Read relevant topics in `docs/ssot/`, identify gap between current state and ideal

### 2. Tasks (Multi-Dimensional Breakdown)
- **Goal Decomposition**: Break down based on Situation
- **Layer Assignment**: Assign tasks to appropriate layers:
  - **Backend**: `apps/backend/` (FastAPI, SQLAlchemy)
  - **Frontend**: `apps/frontend/` (Next.js, React)
  - **Infrastructure**: `infra/` (Docker, deployment)

### 3. Actions (Execution Steps)
- **Atomic Operations**: Define specific action sequence for each task.
- **SSOT Alignment**: Actions must conform to [accounting.md](docs/ssot/accounting.md) and [reconciliation.md](docs/ssot/reconciliation.md).
- **Contract Validation**:
    - **Infra Check**: If adding environment variables, sync `repo` submodule (`infra2`).
    - **DB Check**: Ensure explicit `name` for Enums and check migration length.
    - **Next.js Check**: Ensure `NEXT_PUBLIC_` variables are added to `Dockerfile` `ARG`.
- **Closed-Loop Changes**: Code change → Update SSOT → Verify → Update README.

### 4. Result (Verification)
- **Self-Check**: Compare against project goals in [target.md](target.md)
- **Engineering Audit**:
    - [ ] **Submodule Sync**: Did I update `infra2` for config changes?
    - [ ] **Enum Naming**: Are all `sa.Enum` fields explicitly named (e.g., `name="..._enum"`)?
    - [ ] **Next.js Bake**: Are `NEXT_PUBLIC_` variables added to `Dockerfile` `ARG`?
- **Evidence Loop**: Use verification methods from SSOT "The Proof" sections
- **Update Docs**: Update README, Project docs, SSOT as needed

---

## 🚨 Core Mandatory Principles

### SSOT First
1. **SSOT is the highest truth**: The **sole authoritative source** is `docs/ssot/`. README is navigation only.
2. **No SSOT, no work**: Before introducing new components, define their truth in `docs/ssot/`.
3. **No hidden drift**: When code differs from SSOT, sync immediately. Never let SSOT rot.

### Engineering Integrity
4. **Explicit Enum Naming**: All database enums **MUST** have an explicit `name` parameter in SQLAlchemy.
5. **Environment Lifecycle**:
    - `NEXT_PUBLIC_` variables **MUST** be defined in `Dockerfile` as `ARG` and `ENV`.
    - Backend variables **MUST** be documented in `.env.example` and `config.py`.
6. **Cross-Repo Sync**: Changes to production configuration (Vault/Compose) **REQUIRE** a corresponding PR in the `repo` submodule (`infra2`).
7. **Async Transaction Boundary**: Routers handle `commit()`; Services use `flush()` or internal logic.

### Accounting Integrity
8. **Entries must balance**: Every JournalEntry must have balanced debits and credits.
9. **Equation must hold**: At any point, the accounting equation must be satisfied.

### Delivery
1. **Prefer Dokploy API for debugging**: Use `curl` + Dokploy API instead of browser. See `.env.example` for env vars. If Dokploy is not enough to debug, use `ssh root@$VPS_HOST`, **You can only read, not modify**.
2. **PR must work in test environment**: Before delivering PR, ensure health check passes on `report-pr-XX.zitian.party`.
3. **Shared network isolation (Critical)**: In Dokploy shared network, use unique container names (e.g., `finance-report-db-pr-47`) as hostnames. Never use generic names like `postgres` or `redis` to avoid cross-PR routing conflicts.

### Environment Variable Management
4. **Three-layer SSOT**:
   - `secrets.ctmpl` → Staging/Prod required keys (Vault)
   - `.env.example` → Complete variable documentation
   - `config.py` → Type definitions + defaults
5. **Variable classification**:
   - **Required** (secrets.ctmpl): DATABASE_URL, S3_*
    - **Optional** (config.py defaults): DEBUG, BASE_CURRENCY, PRIMARY_MODEL (Gemini Vision), OPENROUTER_API_KEY (AI features), REDIS_URL (Prod/Staging only)
   - **Infrastructure** (direnv managed): DOKPLOY_*, VAULT_*, VPS_*
6. **Consistency check**: CI runs `scripts/check_env_keys.py` to validate secrets.ctmpl ↔ config.py
7. **Adding new variables**:
   1. Add to `secrets.ctmpl` (if required for production)
   2. Add to `config.py` (with type and default)
   3. Update `.env.example` (with classification comment)
   4. Run `python scripts/check_env_keys.py` to verify

---

## 📁 Documentation Hierarchy

| Category | Path | Purpose | Audience |
|----------|------|---------|----------|
| **Project EPIC** | `docs/project/` | Task tracking, milestones | AI / Maintainers |
| **Module README** | Each `apps/*/README.md` | Directory intro, design guide | Developers |
| **SSOT** | `docs/ssot/` | Technical truth, authoritative reference | Everyone |
| **User Manual** | `docs/onboarding/` (TODO) | User-facing guides | End Users |

### MECE Document Organization

```
docs/
├── ssot/                 # Technical Truth (Flat Ontology)
│   ├── development.md    # Moon commands, DB lifecycle, CI
│   ├── schema.md         # Database layer
│   ├── accounting.md     # Accounting domain
│   ├── reconciliation.md # Reconciliation domain
│   ├── extraction.md     # Document parsing
│   ├── reporting.md      # Financial reports
│   └── market_data.md    # FX & stock prices
├── project/              # EPIC & Task Tracking
│   ├── README.md
│   └── EPIC-001.phase0-setup.md
└── onboarding/           # User Manual (TODO)
    └── README.md
```

---

## 💻 Coding Standards

### Python (Backend)
```python
# ✅ Correct - Use Decimal
from decimal import Decimal
amount = Decimal("100.50")

# ❌ Wrong - Float precision
amount = 100.50
```

### Entry Validation
```python
def validate_balance(lines: list[JournalLine]) -> bool:
    debit = sum(l.amount for l in lines if l.direction == "DEBIT")
    credit = sum(l.amount for l in lines if l.direction == "CREDIT")
    return abs(debit - credit) < Decimal("0.01")
```

### TypeScript (Frontend)
- Strict TypeScript (no `any`)
- Server Components by default
- Client components only when needed

---

## 🤖 Agent & Skill Architecture

**Three-layer System**: Orchestrator → Agents → Skills

### Configured Agents

Agents are defined in `.opencode/oh-my-opencode.json`:

| Agent | Cost | When to Use |
|-------|------|-------------|
| **Sisyphus** | — | Main orchestrator, handles most tasks directly with skills (including documentation) |
| `explore` | FREE | Codebase exploration, parallel grep (use in background) |
| `librarian` | FREE | External docs, OSS examples (use in background) |
| `frontend-ui-ux-engineer` | MEDIUM | **Mandatory** for visual/styling changes |
| `multimodal-looker` | MEDIUM | Image/PDF analysis |

### Built-in System Agent

| Agent | Cost | When to Use |
|-------|------|-------------|
| `oracle` | EXPENSIVE | Architecture decisions, debugging (system built-in, not configured) |

### Sisyphus Workflow

Sisyphus (orchestrator) handles most tasks directly by loading relevant skills.
Delegation happens ONLY for:

1. **Parallel exploration** → `explore` + `librarian` (background, parallel)
2. **Visual changes** → `frontend-ui-ux-engineer` (mandatory for CSS/styling)
3. **Image/PDF analysis** → `multimodal-looker`
4. **Architecture decisions** → `oracle` (expensive, use sparingly)

### Skill Categories

Skills are organized in `.opencode/skills/` by category:

```
skills/
├── domain/              # Project-specific (from SSOT)
│   ├── accounting/      # Double-entry bookkeeping
│   ├── reconciliation/  # Statement matching
│   ├── reporting/       # Financial statements
│   ├── extraction/      # Document parsing
│   ├── schema/          # Database models
│   └── development/     # Moon commands, CI/CD
│
├── professional/        # Reusable expertise
│   ├── backend-development/  # FastAPI, security, performance
│   ├── frontend-react/       # Next.js + Vercel best practices
│   ├── qa-testing/           # Testing strategies, automation
│   ├── ui-ux-design/         # UI/UX design, accessibility
│   ├── product-management/   # PRD, RICE prioritization
│   └── auditor/              # Financial auditing
│
└── meta/                # About skills themselves
    └── skill-writer/    # Creating new skills
```

### Skill Reference

| Category | Skill | Purpose |
|----------|-------|---------|
| **Domain** | `domain/accounting` | Double-entry bookkeeping rules |
| | `domain/reconciliation` | Bank statement matching |
| | `domain/reporting` | Financial statements generation |
| | `domain/extraction` | AI document parsing |
| | `domain/schema` | Database models, migrations |
| | `domain/development` | Moon commands, CI/CD, DB lifecycle |
| **Professional** | `professional/backend-development` | Full backend guide (11 reference docs) |
| | `professional/frontend-react` | React/Next.js patterns + Vercel rules |
| | `professional/qa-testing` | Testing strategies, automation |
| | `professional/ui-ux-design` | UI/UX design, accessibility |
| | `professional/product-management` | PRD templates, RICE prioritization |
| | `professional/auditor` | Financial auditing expertise |
| **Meta** | `meta/skill-writer` | Creating new skills |

### Usage

```bash
# Load a skill on-demand
/skill domain/accounting

# Skills are auto-loaded for agents based on oh-my-opencode.json
# Sisyphus has: domain/development, domain/schema, domain/accounting,
#               domain/reconciliation, professional/backend-development
```

---

## 📅 Current Phase

**Phase 0**: Infrastructure Setup (Moonrepo + Docker)

See [docs/project/README.md](docs/project/README.md) for phased delivery status.
