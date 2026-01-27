# docs/ Directory Guide

> **Authoritative definition**: See [README.md § Documentation System](../README.md#-documentation-system)

This directory contains all project documentation organized by the 4-category system.

---

## 📂 Directory Structure

```
docs/
├── README.md              ← You are here (directory guide)
├── index.md               ← MkDocs homepage (user-facing)
├── target.md              ← Symlink to ../target.md (for MkDocs)
│
├── user-guide/            ← Category 1: User Documentation (Onboarding)
│   ├── getting-started.md
│   ├── accounts.md
│   ├── journal-entries.md
│   ├── reconciliation.md
│   ├── reports.md
│   └── ai-advisor.md
│
├── reference/             ← Category 1: API Reference
│   ├── api-overview.md
│   ├── api-accounts.md
│   ├── api-journal.md
│   ├── api-reconciliation.md
│   └── api-chat.md
│
├── ssot/                  ← Category 2: Technical Truth (SSOT)
│   └── README.md          ← SSOT index and modification guide
│
└── project/               ← Category 3: Project Tracking
    └── README.md          ← EPIC index and modification guide
```

---

## 📝 How to Modify This Directory

### Before Adding New Files

1. **Determine the category**: Which of the 4 categories does this belong to?
2. **Read the target directory's README**: Each subdirectory has its own guide
3. **Follow naming conventions**: See the relevant README for patterns

### Content Placement Rules

| Content Type | Location |
|--------------|----------|
| User-facing guides (how to use) | `user-guide/*.md` |
| API endpoint documentation | `reference/*.md` |
| Technical rules & constraints | `ssot/*.md` |
| EPIC goals & progress | `project/EPIC-XXX.<name>.md` |
| Implementation details | `project/EPIC-XXX.<name>-GENERATED.md` |

### MkDocs Workflow

```bash
# Install dependencies
pip install -r docs/requirements.txt

# Serve locally with live reload (http://127.0.0.1:8000)
mkdocs serve

# Build static site (output: site/)
mkdocs build
```

**If adding new pages**: Update `mkdocs.yml` nav section in project root.

---

## 📁 Loose Files

| File | Status | Notes |
|------|--------|-------|
| `index.md` | ✅ Correct | MkDocs homepage |
| `target.md` | ✅ Correct | Symlink for MkDocs nav |
| `deployment-architecture.md` | ⚠️ Legacy | Superseded by `ssot/deployment.md` |
| `FX_RATE_SEEDING.md` | ⚠️ Legacy | Superseded by `ssot/market_data.md` |

---

## 🔗 Quick Links

- [📖 Live Documentation Site](https://wangzitian0.github.io/finance_report/)
- [🏠 Project Root README](../README.md) — **Documentation system definition**
- [🎯 target.md](../target.md) — North Star goals
- [🤖 AGENTS.md](../AGENTS.md) — AI agent guidelines

---

*This file is the guide for the `docs/` directory. Read before modify, keep consistent after.*
