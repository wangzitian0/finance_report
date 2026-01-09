# Data Model SSOT Index

> This directory contains the core data models and design constraints for the financial management system.

## Document Index

| Document | SSOT Key | Description |
|----------|----------|-------------|
| [db.schema.md](./db.schema.md) | `db.schema` | PostgreSQL Schema Definition |
| [domain.accounting.md](./domain.accounting.md) | `domain.accounting` | Double-Entry Bookkeeping Model |
| [domain.reconciliation.md](./domain.reconciliation.md) | `domain.reconciliation` | Reconciliation Engine Model |

## Design Principles

1. **Docs explain "why", code defines "what"**
2. **Never hardcode volatile values in docs**
3. **All model changes: update SSOT first, then modify code**
