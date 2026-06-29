# Finance Report Documentation

Welcome to the **Finance Report** documentation — your comprehensive guide to building and using a personal financial management system with double-entry bookkeeping and bank reconciliation.

## 🎯 Project Vision

Read the North Star goals and decision criteria before deep technical work:

- [Project Vision](target.md)
- [Project status and EPIC proof summary](https://github.com/wangzitian0/finance_report/blob/main/README.md)

## 📖 Documentation Guide

This documentation is organized into four main sections to help you find what you need quickly:

<div class="grid cards" markdown>

-   :material-book-open-page-variant:{ .lg .middle } __User Guide__

    ---

    Learn how to use Finance Report for daily financial management

    [:octicons-arrow-right-24: Start here](user-guide/getting-started.md)

-   :material-api:{ .lg .middle } __Generated References__

    ---

    Generated API and database contract inventories

    [:octicons-arrow-right-24: View references](reference/api-overview.md)

-   :material-file-document-multiple:{ .lg .middle } __Technical Documentation__

    ---

    Architecture, design decisions, and implementation details

    [:octicons-arrow-right-24: SSOT Docs](ssot/README.md)

-   :material-hammer-wrench:{ .lg .middle } __Development Guide__

    ---

    Setup development environment and contribute to the project

    [:octicons-arrow-right-24: Project Overview](project/README.md)

</div>

## 🚀 Quick Start

New to Finance Report? Follow these steps:

<div class="grid cards" markdown>

-   :material-rocket-launch:{ .lg .middle } __Getting Started__

    ---

    Set up your account and start tracking finances in minutes

    [:octicons-arrow-right-24: Quick start](user-guide/getting-started.md)

-   :material-bank:{ .lg .middle } __Account Management__

    ---

    Create and organize accounts using the Chart of Accounts

    [:octicons-arrow-right-24: Learn more](user-guide/accounts.md)

-   :material-book-open-variant:{ .lg .middle } __Journal Entries__

    ---

    Record transactions with double-entry bookkeeping

    [:octicons-arrow-right-24: View guide](user-guide/journal-entries.md)

-   :material-sync:{ .lg .middle } __Bank Reconciliation__

    ---

    Match bank statements with your records automatically

    [:octicons-arrow-right-24: Reconcile](user-guide/reconciliation.md)

</div>

## 🌟 Key Features

Feature status and proof live in the root [README](https://github.com/wangzitian0/finance_report/blob/main/README.md) and EPIC
documents. This page only provides navigation:

| Feature | Entry point |
|---------|-------------|
| **Double-Entry Bookkeeping** | [EPIC-002](project/EPIC-002.double-entry-core.md) |
| **Statement Import** | [EPIC-003](project/EPIC-003.statement-parsing.md) and [EPIC-013](project/EPIC-013.statement-parsing-v2.md) |
| **Reconciliation** | [EPIC-004](project/EPIC-004.reconciliation-engine.md) |
| **Reports & Visualization** | [EPIC-005](project/EPIC-005.reporting-visualization.md) |
| **AI Advisor** | [EPIC-006](project/EPIC-006.ai-advisor.md) |
| **Portfolio Management** | [EPIC-017](project/EPIC-017.portfolio-management.md) |

## 📚 Documentation Structure

This documentation site is organized as follows:

### User Guide
Step-by-step guides for end users:

- [Getting Started](user-guide/getting-started.md) — Setup and first steps
- [Account Management](user-guide/accounts.md) — Creating and managing accounts
- [Journal Entries](user-guide/journal-entries.md) — Recording transactions
- [Bank Reconciliation](user-guide/reconciliation.md) — Matching bank statements
- [Reports & Dashboards](user-guide/reports.md) — Financial reporting
- [AI Advisor](user-guide/ai-advisor.md) — Using the AI financial advisor

### Generated References
Generated implementation inventories:

- [Generated Contract References](reference/api-overview.md) — API and DB contract ownership
- [Generated API Reference](reference/api.md) — OpenAPI-derived endpoint inventory
- [Generated DB Schema Reference](reference/db-schema.md) — SQLAlchemy-derived table, enum, index, constraint, and FK inventory
- [Runtime Swagger UI](https://report.zitian.party/api/docs) — Full field-level contract

### Technical Documentation (SSOT)
Rationale docs with links to code owners, generated contracts, and proof tests:

- [Architecture Overview](ssot/README.md) — System architecture and design principles
- [Ledger (double-entry) model](https://github.com/wangzitian0/finance_report/blob/main/common/ledger/readme.md) — Double-entry bookkeeping rules
- [Reconciliation Engine](ssot/reconciliation.md) — Matching algorithms
- [Statement Extraction](https://github.com/wangzitian0/finance_report/blob/main/common/extraction/readme.md) — AI parsing pipeline
- [Reporting](ssot/reporting.md) — Report generation logic
- [AI Advisor](ssot/ai.md) — AI advisor implementation
- [Database Schema](ssot/schema.md) — Data-layer rules and migration guardrails
- [Development Guide](ssot/development.md) — Development environment setup

### Development & Project Management
Project tracking and development guides:

- [Project Overview](project/README.md) — EPIC tracking and roadmap
- [Design Decisions](project/DECISIONS.md) — Key architectural decisions
- EPICs: [Setup](project/EPIC-001.phase0-setup.md) | [Double-Entry](project/EPIC-002.double-entry-core.md) | [Statement Parsing](project/EPIC-003.statement-parsing.md) | [Reconciliation](project/EPIC-004.reconciliation-engine.md) | [Reporting](project/EPIC-005.reporting-visualization.md) | [AI Advisor](project/EPIC-006.ai-advisor.md) | [Deployment](project/EPIC-007.deployment.md)

## 🏗️ System Architecture

```mermaid
graph TB
    subgraph Frontend["Frontend (Next.js 14)"]
        UI[React UI]
        TQ[TanStack Query]
    end
    
    subgraph Backend["Backend (FastAPI)"]
        API[REST API]
        SVC[Services Layer]
        DB[(PostgreSQL)]
    end
    
    subgraph AI["AI Services"]
        Provider[Configured AI Provider]
    end
    
    UI --> TQ --> API
    API --> SVC --> DB
    SVC --> Provider
```

For detailed architecture documentation, see [Architecture Overview](ssot/README.md).

## 🔗 Quick Links

- **Live Application**: [report.zitian.party](https://report.zitian.party)
- **API Documentation**: [report.zitian.party/api/docs](https://report.zitian.party/api/docs)
- **GitHub Repository**: [github.com/wangzitian0/finance_report](https://github.com/wangzitian0/finance_report)
- **Report Issues**: [GitHub Issues](https://github.com/wangzitian0/finance_report/issues)

## 🤝 Contributing

Interested in contributing? Check out:

- [Development Guide](ssot/development.md) — Setup your development environment
- [Project Overview](project/README.md) — Understand the project structure and roadmap

## 📄 License

MIT License — See repository for details.
