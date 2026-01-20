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
- **Agent Skills** → [.claude/skills/README.md](.claude/skills/README.md)
- **Copilot Instructions** → [.github/copilot-instructions.md](.github/copilot-instructions.md)

**Reading Order (10-minute overview)**
1. [target.md](target.md) — Macro goals and decision criteria
2. [README.md](README.md) — Tech stack, quick start commands
3. [docs/ssot/README.md](docs/ssot/README.md) → Start with [schema.md](docs/ssot/schema.md)
4. [.claude/skills/README.md](.claude/skills/README.md) — Available agent roles

**Routing Rules (where to go when)**
- Need to understand business logic → [target.md](target.md)
- **Need environment setup / moon commands** → [docs/ssot/development.md](docs/ssot/development.md)
- Need to write code → [.github/copilot-instructions.md](.github/copilot-instructions.md) + skill files
- Need data model reference → [docs/ssot/](docs/ssot/)
- Need to track current work → [docs/project/](docs/project/)

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

## 🤖 Agent Role Activation

**Skill files location**: `.claude/skills/`

| Role | File | When to Use |
|------|------|-------------|
| 📋 PM | `pm.md` | Requirement analysis, task breakdown |
| 🏗️ Architect | `architect.md` | System design, tech decisions |
| 💻 Developer | `developer.md` | Code implementation |
| ⚖️ Auditor | `auditor.md` | Accounting, reconciliation, reporting, and audit |
| 🧪 Tester | `tester.md` | Test strategy, quality assurance |

### Usage
```bash
@.claude/skills/auditor.md How should I record this cross-currency transaction?
@.claude/skills/auditor.md Match accuracy dropped, please analyze
```

---

## 📅 Current Phase

**Phase 0**: Infrastructure Setup (Moonrepo + Docker)

See [docs/project/README.md](docs/project/README.md) for phased delivery status.
