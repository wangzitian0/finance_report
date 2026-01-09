# Project EPIC & Task Tracking

> Track project milestones, active tasks, and progress.

## Active Projects

| ID | Project | Status | Phase | 周期 |
|----|---------|--------|-------|------|
| [EPIC-001](./EPIC-001.phase0-setup.md) | 基础设施与认证系统 | 🟢 Complete | 0 | 2 周 |
| [EPIC-002](./EPIC-002.double-entry-core.md) | 复式记账核心引擎 | 🟡 In Progress | 1 | 3 周 |
| [EPIC-003](./EPIC-003.statement-parsing.md) | 智能对账单解析 | ⏳ Pending | 2 | 3 周 |
| [EPIC-004](./EPIC-004.reconciliation-engine.md) | 对账引擎与匹配算法 | ⏳ Pending | 3 | 4 周 |
| [EPIC-005](./EPIC-005.reporting-visualization.md) | 财务报表与可视化 | ⏳ Pending | 4 | 3 周 |
| [EPIC-006](./EPIC-006.ai-advisor.md) | AI 财务顾问 | ⏳ Pending | 4 | 2 周 |

**总周期**: 15-18 周

## 依赖关系

```
EPIC-001 ──→ EPIC-002 ──→ EPIC-003 ──→ EPIC-004
                │
                └──→ EPIC-005 ──→ EPIC-006
```

**关键路径**: EPIC-001 → EPIC-002 → EPIC-003 → EPIC-004  
**并行路径**: EPIC-005 可在 EPIC-002 完成后与 EPIC-003/004 并行

## Project File Convention

- **Naming**: `EPIC-XXX.<project_name>.md`
- **Status**: 🔴 Blocked | 🟡 In Progress | 🟢 Complete | ⏳ Pending

## 每个 EPIC 的评判标准

每个 EPIC 文档包含：
- ✅ **合格标准 (Must Have)**: 必须达到的最低要求
- 🌟 **优秀标准 (Nice to Have)**: 超预期的目标
- 🚫 **不合格信号**: 需要立即修复的问题
- ❓ **Q&A**: 待确认的问题

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
- [Skills](.claude/skills/) - AI 角色技能定义
