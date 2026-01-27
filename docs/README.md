# Finance Report Documentation

> **Modification Guide** — How to read and modify documentation in this directory.

---

## 📂 Directory Structure

```
docs/
├── README.md              ← You are here (Modification Guide)
├── target.md              ← North Star goals and decision criteria
├── index.md               ← MkDocs homepage (auto-generated site entry)
│
├── user-guide/            ← End-user documentation (MkDocs onboarding)
│   ├── getting-started.md
│   ├── accounts.md
│   ├── journal-entries.md
│   ├── reconciliation.md
│   ├── reports.md
│   └── ai-advisor.md
│
├── reference/             ← API reference (MkDocs onboarding)
│   ├── api-overview.md
│   ├── api-accounts.md
│   ├── api-journal.md
│   ├── api-reconciliation.md
│   └── api-chat.md
│
├── ssot/                  ← Technical Truth (Single Source of Truth)
│   └── README.md          ← SSOT modification guide
│
└── project/               ← EPIC tracking and project management
    └── README.md          ← Project modification guide
```

---

## 📖 Reading Guide

### For Different Purposes

| You want to... | Read |
|----------------|------|
| **Understand project goals** | [target.md](target.md) — North Star, decision criteria |
| **Learn how to use the app** | [user-guide/](user-guide/getting-started.md) or [live docs](https://wangzitian0.github.io/finance_report/) |
| **Integrate with the API** | [reference/](reference/api-overview.md) |
| **Understand technical decisions** | [ssot/](ssot/README.md) — Technical truth |
| **Track project progress** | [project/](project/README.md) — EPIC tracking |
| **Set up development environment** | [ssot/development.md](ssot/development.md) |

### For New Developers (10-minute Overview)

1. **[target.md](target.md)** — Macro goals and decision criteria
2. **[ssot/development.md](ssot/development.md)** — Environment setup, moon commands
3. **[ssot/schema.md](ssot/schema.md)** — Database models
4. **[project/README.md](project/README.md)** — Current EPICs and status

### Onboarding Content (MkDocs Generated)

The following directories are **user-facing onboarding documentation**, generated and served by MkDocs:

- **`user-guide/`** — End-user guides (Getting Started, Accounts, Journal Entries, etc.)
- **`reference/`** — API reference documentation

Live site: [wangzitian0.github.io/finance_report](https://wangzitian0.github.io/finance_report/)

---

## 📝 How to Modify This Directory

### Three-Track Documentation System

| Track | Directory | Purpose | Audience |
|-------|-----------|---------|----------|
| **Technical Truth** | `ssot/` | How things work (authoritative) | Developers |
| **Project Tracking** | `project/` | What we're building (EPIC progress) | Team |
| **User Onboarding** | `user-guide/`, `reference/` | How to use the app | End Users |

### Content Placement Rules

| Content Type | Location |
|--------------|----------|
| Technical rules & constraints | `ssot/*.md` |
| Database models, API contracts | `ssot/schema.md`, `ssot/*.md` |
| EPIC goals & acceptance criteria | `project/EPIC-XXX.<name>.md` |
| EPIC implementation details | `project/EPIC-XXX.<name>-GENERATED.md` |
| User-facing how-to guides | `user-guide/*.md` |
| API endpoint documentation | `reference/*.md` |
| Architectural decisions | `ssot/*.md` or `project/DECISIONS.md` |

### Documentation Principles

1. **SSOT is authoritative** — When code differs from SSOT, update SSOT immediately
2. **Project tracks work** — EPICs document goals and progress, not implementation details
3. **User guides are for users** — Keep technical details in SSOT
4. **API reference stays in sync** — Update when endpoints change
5. **No orphan files** — Every document belongs to a category

### EPIC File Convention

Each EPIC has **two files**:

| File Type | Naming | Author | Content |
|-----------|--------|--------|---------|
| **Human Review** | `EPIC-XXX.<name>.md` | Human/PM | Goals, acceptance criteria, Q&A |
| **Machine Generated** | `EPIC-XXX.<name>-GENERATED.md` | AI/Automation | Implementation details, test results |

### MkDocs Workflow

```bash
# Install dependencies
pip install -r docs/requirements.txt

# Serve locally with live reload
mkdocs serve

# Build static site (output: site/)
mkdocs build
```

**If adding new pages**: Update `mkdocs.yml` nav section.

---

## 🔗 Quick Links

- [📖 Live Documentation Site](https://wangzitian0.github.io/finance_report/)
- [🏠 Project Root README](../README.md)
- [🤖 AGENTS.md](../AGENTS.md) — AI agent guidelines
- [🎯 target.md](target.md) — North Star goals

---

## 📁 Loose Files in docs/

The following files exist at `docs/` root level:

| File | Status | Notes |
|------|--------|-------|
| `target.md` | ✅ Correct | Root-level (North Star) |
| `index.md` | ✅ Correct | MkDocs homepage |
| `deployment-architecture.md` | ⚠️ Legacy | Content moved to `ssot/deployment.md` |
| `FX_RATE_SEEDING.md` | ⚠️ Legacy | Content moved to `ssot/market_data.md` Section 10 |

> **Note**: Legacy files are kept for reference but `ssot/` versions are authoritative.

---

*This file serves as the modification guide for the `docs/` directory. For technical truth, see [ssot/README.md](ssot/README.md). For project tracking, see [project/README.md](project/README.md).*
