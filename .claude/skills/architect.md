# System Architect

## Role Definition
You are the System Architect, responsible for the overall design and technical decisions of the financial management system.

## Core Design Philosophy

### Ultimate Goal
**Double-entry accuracy + Smart reconciliation efficiency** → Trustworthy financial reports

### Design Principles
1. **Double-entry at the core** - Accounting equation is the mathematical foundation
2. **AI as assistant** - Gemini handles parsing and explanation, not bookkeeping decisions
3. **Human review as safety net** - Medium/low confidence transactions require manual confirmation
4. **Auditable** - All operations are traceable for accounting compliance

## Four-Layer Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     Presentation Layer                       │
│  apps/frontend/ (Next.js 14) - Bookkeeping UI, Review, Reports│
├─────────────────────────────────────────────────────────────┤
│                     Application Layer                        │
│  apps/backend/routers/ - REST API (FastAPI)                  │
│  apps/backend/services/ - Business logic layer               │
├─────────────────────────────────────────────────────────────┤
│                     Domain Layer                             │
│  apps/backend/models/ - ORM models (SQLAlchemy)              │
│  apps/backend/schemas/ - Pydantic validation                 │
│  apps/backend/services/                                      │
│    ├── accounting.py - Double-entry core                     │
│    ├── reconciliation.py - Matching algorithms               │
│    └── extraction.py - Gemini document parsing               │
├─────────────────────────────────────────────────────────────┤
│                     Infrastructure Layer                     │
│  PostgreSQL 15 - Transactional database                      │
│  Redis 7 - Cache and queue                                   │
│  Gemini 2.0 Flash (free) - AI capabilities                            │
└─────────────────────────────────────────────────────────────┘
```

## Data Flow Design

### Statement Import Flow
```
Upload file → Gemini parsing → Balance verification → Generate candidate entries → Match scoring → Review/Auto-accept
                                    ↓
                             Validation failed → Manual review queue
```

### State Machine

```
JournalEntry: draft → posted → reconciled
                 ↓        ↓
              rejected   void (reversal)

ReconciliationMatch: pending → auto_accepted / pending_review → accepted / rejected
```

## Technology Stack Decisions

| Component | Choice | Reason |
|-----------|--------|--------|
| Monorepo | Moonrepo | First-class multi-language support, incremental task execution |
| Backend | FastAPI + SQLAlchemy | Async high performance, mature ORM |
| Frontend | Next.js 14 + shadcn/ui | App Router + rapid UI development |
| Database | PostgreSQL | ACID transactions, financial standard |
| AI | Gemini 2.0 Flash (free) | Vision + Text, cost-effective |
| Deployment | Dokploy | Self-hosted, data sovereignty |

## Key Design Decisions

### Why "Journal Entry + Lines" Model?
```
Problem: Simple debit/credit columns cannot express one-to-many or many-to-many transactions
Solution: JournalEntry (header) + JournalLine[] (lines)
Benefit: Flexibly supports complex transactions, multi-party balancing in single entry
```

### Why Threshold-Based Match Scoring?
```
≥85: Auto-accept, reduces manual burden
60-84: Review queue, manual confirmation
<60: Marked as unmatched, requires entry creation
```

### Why AI Only Parses, Not Books?
```
Problem: LLMs have hallucination risks, direct booking could corrupt ledger
Solution: AI only extracts structured data, booking by rule engine
Validation: Opening + transactions ≈ Closing, reject if not matching
```

## Extension Points

### Adding New Statement Types
1. Create parser in `services/extraction/`
2. Configure Gemini prompt template
3. Register in `SUPPORTED_STATEMENT_TYPES`

### Adding New Report Types
1. Create report logic in `services/reporting/`
2. Implement `generate()` method
3. Add display component in frontend
