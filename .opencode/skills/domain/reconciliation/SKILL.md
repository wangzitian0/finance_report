---
name: reconciliation
description: Bank reconciliation matching algorithm, confidence scoring, and state machine. Use when working with statement matching, review queues, or transaction reconciliation.
---

# Reconciliation Engine

This skill is a **pointer, not a mirror** (#1658): the hand-written snapshot it
used to carry drifted from the owning contract, and models read the owner
directly.

**Read the owner**: [common/reconciliation/reconciliation.md](../../../../common/reconciliation/reconciliation.md)

Also honor the red lines in `docs/agents/red-lines.md` (Decimal for money,
balanced entries, explicit `sa.Enum` names) and the work order in
`docs/agents/orchestration.md` (AC-anchored tests before code).
