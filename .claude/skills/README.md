# Claude Skills Guide

## Overview

This directory contains 6 professional role definitions for multi-agent collaborative development of the financial management system.

## Available Roles

| Role | File | Responsibility |
|------|------|----------------|
| 📋 Product Manager | `pm.md` | Requirements analysis, task breakdown |
| 🏗️ System Architect | `architect.md` | System design, technical decisions |
| 💻 Full-Stack Developer | `developer.md` | FastAPI backend, Next.js frontend |
| 📊 Accounting Advisor | `accountant.md` | Double-entry rules, chart of accounts |
| 🔗 Reconciliation Specialist | `reconciler.md` | Matching algorithms, review queue |
| 🧪 QA Engineer | `tester.md` | Balance verification, equation testing |

## Usage

### Single Role Consultation
```
@.claude/skills/accountant.md How should I record this cross-currency investment?
```

### Multi-Role Collaboration
```
@.claude/skills/architect.md @.claude/skills/accountant.md Please review this reconciliation engine design together
```

### Collaboration Matrix

```
              PM    Arch  Dev   Acct  Recon Tester
Chart design        ✓           ✓Lead
Double-entry        ✓Lead       ✓
Reconciliation      ✓           ✓     ✓Lead
API impl                  ✓Lead             ✓
Frontend                  ✓Lead
Testing                   ✓                 ✓Lead
```
