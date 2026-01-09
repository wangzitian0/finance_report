# Data Model SSOT Index

> **SSOT = Single Source of Truth**
> This directory is the **authoritative reference** for all technical decisions.

## Document Structure (MECE Organization)

Documents are organized by layer to ensure Mutually Exclusive, Collectively Exhaustive coverage:

### Database Layer
| Document | SSOT Key | Description |
|----------|----------|-------------|
| [db.schema.md](./db.schema.md) | `db.schema` | PostgreSQL tables, ER diagram, indexes |

### Domain Layer
| Document | SSOT Key | Description |
|----------|----------|-------------|
| [domain.accounting.md](./domain.accounting.md) | `domain.accounting` | Double-entry rules, accounting equation |
| [domain.reconciliation.md](./domain.reconciliation.md) | `domain.reconciliation` | Matching algorithm, confidence scoring |

### Future Documents (TODO)
- `domain.reporting.md` — Financial report generation
- `domain.extraction.md` — Gemini document parsing
- `ops.backup.md` — Backup and recovery procedures
- `ops.deployment.md` — Dokploy deployment guide

## Design Principles

1. **Docs explain "why", code defines "what"**
2. **Never hardcode volatile values** — Reference code as the source
3. **SSOT before implementation** — Define truth before writing code
4. **Immediate sync on drift** — If code differs, update SSOT immediately

## SSOT Template

Each SSOT document should follow this structure:
1. **Source of Truth** — Physical file locations
2. **Architecture Model** — Diagrams, key decisions
3. **Design Constraints** — Dos & Don'ts
4. **Playbooks (SOP)** — Standard operating procedures
5. **Verification (The Proof)** — How to validate

## Quick Links

- [AGENTS.md](../../AGENTS.md) — Agent behavioral guidelines
- [init.md](../../init.md) — Project specification
- [Project Tracking](../project/README.md) — EPIC & tasks
