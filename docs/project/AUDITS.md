# Audit Index

> This file is the single entry point for all AC / traceability audit reports.
> Readers should start here and follow links to the relevant report.

---

## Current Audit (Active)

| Report | Date | Scope | Branch |
|--------|------|-------|--------|
| [AC-AUDIT-2026-05-04.md](./AC-AUDIT-2026-05-04.md) | 2026-05-04 | Full vision → EPIC → AC → test consistency | `audit/vision-epic-ac-alignment` |

**Latest findings summary**: 760 ACs across 18 EPICs — 0 orphans, 0 duplicates, 0 EPIC↔registry mismatches.
See the report for P0/P1/P2 fix details and follow-up actions.

---

## Archived Audits

Older reports are kept in [`docs/project/archive/`](./archive/) for historical reference.
They are **not current**; do not use them for rule interpretation.

| Report | Date | Scope | Why Archived |
|--------|------|-------|--------------|
| [AC-AUDIT-2026-02-25.md](./archive/AC-AUDIT-2026-02-25.md) | 2026-02-25 | AC numbering compliance | Superseded by 2026-05-04 audit |
| [AC-TEST-TRACEABILITY-AUDIT.md](./archive/AC-TEST-TRACEABILITY-AUDIT.md) | 2026-02 era | Test ↔ AC traceability (542-AC era) | Body reflects legacy AC inventory; head refreshed in 2026-05-04 audit |

---

## How to File a New Audit

1. Create `docs/project/AC-AUDIT-YYYY-MM-DD.md` following the structure of the current report.
2. Update this index: move the previous "Current" entry to "Archived Audits" and add the new report.
3. Append a summary to `docs/project/DECISIONS.md` under a dated heading.

---

> **Last Updated**: 2026-05-05
