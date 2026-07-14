---
name: reporting
description: Financial report generation including balance sheet, income statement, and cash flow. Use when working with financial reports, multi-currency consolidation, or report calculations.
---

# Financial Reporting

This skill is a **pointer, not a mirror** (#1658): the hand-written snapshot it
used to carry drifted from the owning contract, and models read the owner
directly.

**Read the owner**: [common/reporting/reporting.md](../../../../common/reporting/reporting.md)

Also honor the red lines in `docs/agents/red-lines.md` (Decimal for money,
balanced entries, explicit `sa.Enum` names) and the work order in
`docs/agents/orchestration.md` (AC-anchored tests before code).
