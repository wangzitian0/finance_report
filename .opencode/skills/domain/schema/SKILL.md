---
name: schema
description: PostgreSQL database schema, table structures, relationships, and migration rules. Use when working with SQLAlchemy models, Alembic migrations, or database design.
---

# Database Schema

This skill is a **pointer, not a mirror** (#1658): the hand-written snapshot it
used to carry drifted from the owning contract, and models read the owner
directly.

**Read the owner**: [common/meta/schema.md](../../../../common/meta/schema.md)

Also honor the red lines in `docs/agents/red-lines.md` (Decimal for money,
balanced entries, explicit `sa.Enum` names) and the work order in
`docs/agents/orchestration.md` (AC-anchored tests before code).
