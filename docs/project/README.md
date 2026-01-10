# Project EPIC & Task Tracking

> Track project milestones, active tasks, and progress.

## Active Projects

| ID | Project | Status | Phase | Duration |
|----|---------|--------|-------|----------|
| [EPIC-001](./EPIC-001.phase0-setup.md) | Infrastructure & Authentication | 🟢 Complete | 0 | 2 weeks |
| [EPIC-002](./EPIC-002.double-entry-core.md) | Double-Entry Bookkeeping Core | 🟡 In Progress | 1 | 3 weeks |
| [EPIC-003](./EPIC-003.statement-parsing.md) | Smart Statement Parsing | ⏳ Pending | 2 | 4 weeks |
| [EPIC-004](./EPIC-004.reconciliation-engine.md) | Reconciliation Engine & Matching | ⏳ Pending | 3 | 5 weeks |
| [EPIC-005](./EPIC-005.reporting-visualization.md) | Financial Reports & Visualization | ⏳ Pending | 4 | 3 weeks |
| [EPIC-006](./EPIC-006.ai-advisor.md) | AI Financial Advisor | ⏳ Pending | 4 | 2 weeks |
| [EPIC-007](./EPIC-007.deployment.md) | Production Deployment | 🟡 In Progress | 0 | 1 week |

**Total Duration**: 17-20 weeks

## Dependencies

```
EPIC-001 ──→ EPIC-002 ──→ EPIC-003 ──→ EPIC-004
                │
                └──→ EPIC-005 ──→ EPIC-006

EPIC-007 (Deployment) ──→ Deploy EPIC 1-3 features
```

**Critical Path**: EPIC-001 → EPIC-002 → EPIC-003 → EPIC-004  
**Parallel Path**: EPIC-005 can start after EPIC-002, parallel with EPIC-003/004  
**Infrastructure Path**: EPIC-007 deploys completed features to production

## Project File Convention

- **Naming**: `EPIC-XXX.<project_name>.md`
- **Status**: 🔴 Blocked | 🟡 In Progress | 🟢 Complete | ⏳ Pending

## Quality Standards for Each EPIC

Each EPIC document contains:
- ✅ **Must Have**: Minimum requirements to pass
- 🌟 **Nice to Have**: Excellence targets beyond expectations
- 🚫 **Not Acceptable**: Issues requiring immediate fix
- ❓ **Q&A**: Questions requiring clarification

## Reading Order

1. Check this index for active projects
2. Open the specific EPIC file for details
3. Reference [init.md](../../init.md) for overall specification
4. Reference [SSOT](../ssot/) for technical details

## Archived Projects

Completed projects moved to `docs/project/archived/`

---

## Quick Links

- [Project Specification](../../init.md)
- [SSOT Index](../ssot/README.md)
- [AGENTS.md](../../AGENTS.md)
