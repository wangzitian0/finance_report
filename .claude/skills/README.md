# Claude Skills Guide

## Overview

This directory contains professional skill definitions for AI-powered collaborative development of the financial management system.

## Available Skills

| Role | Directory/File | Source | Responsibility |
|------|----------------|--------|----------------|
| 📊 Accounting Advisor | `accountant.md` | Project-specific | Double-entry rules, chart of accounts, financial compliance |
| 🔗 Reconciliation Specialist | `reconciler.md` | Project-specific | Bank statement matching algorithms, review queue management |
| 🔧 Backend Developer | `backend-development/` | [mrgoonie/claudekit-skills](https://github.com/mrgoonie/claudekit-skills) | Production backend systems, security (OWASP Top 10), performance optimization, API design |
| 🧪 Senior QA Engineer | `senior-qa/` | [davila7/claude-code-templates](https://github.com/davila7/claude-code-templates) | Testing strategies, test automation, quality assurance, coverage analysis |
| ⚛️ Vercel React Developer | `vercel-react-best-practices/` | [langgenius/dify](https://github.com/langgenius/dify) | Next.js/React performance optimization, bundle optimization, SSR/client best practices |
| 📋 Product Manager | `product-manager-toolkit/` | [davila7/claude-code-templates](https://github.com/davila7/claude-code-templates) | PRD templates, RICE prioritization, customer interview analysis |
| ✍️ Skill Writer | `skill-writer/` | [pytorch/pytorch](https://github.com/pytorch/pytorch) | Creating new Claude skills with proper structure and documentation |
| 🎨 UI/UX Pro | `ui-ux-pro-max/` | [nextlevelbuilder/ui-ux-pro-max-skill](https://github.com/nextlevelbuilder/ui-ux-pro-max-skill) | Professional UI/UX design for multiple platforms, design systems, accessibility |

## Usage

### Single Skill Consultation
```bash
# Domain-specific skills
@.claude/skills/accountant.md How should I record this cross-currency investment?
@.claude/skills/reconciler.md Improve matching accuracy for this transaction type

# Development skills
@.claude/skills/backend-development/SKILL.md How to implement OAuth 2.1 authentication?
@.claude/skills/senior-qa/SKILL.md Create comprehensive test strategy for reconciliation engine
@.claude/skills/vercel-react-best-practices/SKILL.md Optimize Next.js bundle size

# Product & Design skills
@.claude/skills/product-manager-toolkit/SKILL.md Prioritize these features using RICE
@.claude/skills/ui-ux-pro-max/SKILL.md Design a financial dashboard with shadcn/ui

# Meta skill
@.claude/skills/skill-writer/SKILL.md Help me create a new skill for financial reporting
```

### Multi-Skill Collaboration
```bash
# Backend + QA
@.claude/skills/backend-development/SKILL.md @.claude/skills/senior-qa/SKILL.md Implement secure API with comprehensive tests

# Accounting + Backend
@.claude/skills/accountant.md @.claude/skills/backend-development/SKILL.md Review double-entry implementation for security issues

# Product + Design + Frontend
@.claude/skills/product-manager-toolkit/SKILL.md @.claude/skills/ui-ux-pro-max/SKILL.md @.claude/skills/vercel-react-best-practices/SKILL.md Design and build reconciliation review queue UI
```

## Skill Categories

### Domain-Specific (Finance)
- **Accounting**: Double-entry bookkeeping, financial compliance
- **Reconciliation**: Transaction matching, confidence scoring

### Development
- **Backend**: FastAPI, PostgreSQL, security, performance
- **QA**: Testing strategies, automation, coverage
- **Frontend**: Next.js, React optimization, SSR/SSG

### Product & Design
- **Product Management**: Feature prioritization, PRD writing
- **UI/UX**: Design systems, accessibility, multi-platform

### Meta
- **Skill Writing**: Creating new Claude skills

## Collaboration Matrix

| Task | Primary Skill | Supporting Skills |
|------|---------------|-------------------|
| Chart of accounts design | Accounting | Backend (validation) |
| Double-entry validation | Accounting | QA (test coverage) |
| Reconciliation algorithm | Reconciliation | Backend (implementation), QA (testing) |
| API security | Backend | QA (security testing) |
| Financial reports UI | UI/UX | Vercel React (optimization) |
| Feature prioritization | Product Manager | Accounting (domain validation) |
| Performance optimization | Vercel React | Backend (API performance) |

## Adding New Skills

Use the **Skill Writer** skill to create new skills:

```bash
@.claude/skills/skill-writer/SKILL.md I need to create a skill for financial statement analysis
```

## License & Attribution

- **Project-specific skills** (`accountant.md`, `reconciler.md`): Custom for this project
- **External skills**: See individual skill directories for licenses (typically MIT)
