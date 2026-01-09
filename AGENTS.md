# Finance Report AI Agent Behavioral Guidelines

> **Prohibition**: AI may NOT modify this file without explicit authorization.
> **English**: All code, PRs, commits, and reports must be in English

## 🧭 Wiki Entry Map (Level 0/1)

**Level 0 Entry**: `AGENTS.md` (you are here)

**Level 1 Entries (by purpose)**
1. **Global Project Overview** → [README.md](README.md)
2. **Project Goals & Specification** → [init.md](init.md)
3. **Technical Truth / SSOT** → [docs/ssot/README.md](docs/ssot/README.md)
4. **Project Tracking / EPIC** → [docs/project/README.md](docs/project/README.md)

**Supplementary Entries**
- **Agent Skills** → [.claude/skills/README.md](.claude/skills/README.md)
- **Copilot Instructions** → [.github/copilot-instructions.md](.github/copilot-instructions.md)

**Reading Order (10-minute overview)**
1. [init.md](init.md) — Project goals, business flows, phased delivery
2. [README.md](README.md) — Tech stack, quick start commands
3. [docs/ssot/README.md](docs/ssot/README.md) → Start with [schema.md](docs/ssot/schema.md)
4. [.claude/skills/README.md](.claude/skills/README.md) — Available agent roles

**Routing Rules (where to go when)**
- Need to understand business logic → [init.md](init.md)
- Need to write code → [.github/copilot-instructions.md](.github/copilot-instructions.md) + skill files
- Need data model reference → [docs/ssot/](docs/ssot/)
- Need to track current work → [docs/project/](docs/project/)

---

## 📌 Core Domain Context

**Read [init.md](init.md) for complete specification. Key points:**

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
- **Atomic Operations**: Define specific action sequence for each task
- **SSOT Alignment**: Actions must conform to [accounting.md](docs/ssot/accounting.md) and [reconciliation.md](docs/ssot/reconciliation.md)
- **Closed-Loop Changes**: Code change → Update SSOT → Verify → Update README

### 4. Result (Verification)
- **Self-Check**: Compare against project goals in [init.md](init.md)
- **Evidence Loop**: Use verification methods from SSOT "The Proof" sections
- **Update Docs**: Update README, Project docs, SSOT as needed

---

## 🚨 Core Mandatory Principles

### SSOT First
1. **SSOT is the highest truth**: The **sole authoritative source** is `docs/ssot/`. README is navigation only.
2. **No SSOT, no work**: Before introducing new components, define their truth in `docs/ssot/`.
3. **No hidden drift**: When code differs from SSOT, sync immediately. Never let SSOT rot.

### Accounting Integrity
4. **Entries must balance**: Every JournalEntry must have balanced debits and credits.
5. **Equation must hold**: At any point, the accounting equation must be satisfied.
6. **Use Decimal for money**: NEVER use float for monetary calculations.

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
| 📊 Accountant | `accountant.md` | Double-entry rules, entry validation |
| 🔗 Reconciler | `reconciler.md` | Matching algorithm tuning |
| 🧪 Tester | `tester.md` | Test strategy, quality assurance |

### Usage
```bash
@.claude/skills/accountant.md How should I record this cross-currency transaction?
@.claude/skills/reconciler.md Match accuracy dropped, please analyze
```

---

## 📅 Current Phase

**Phase 0**: Infrastructure Setup (Moonrepo + Docker)

See [init.md](init.md) Section 7 for full phased delivery plan.

---

## 🔐 Security & Red Lines

- **NEVER** commit sensitive files (`.env`, `*.pem`, credentials)
- **NEVER** use float for monetary amounts
- **NEVER** skip entry balance validation
- **NEVER** post entries without accounting equation check
