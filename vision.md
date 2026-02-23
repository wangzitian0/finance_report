# Finance Report Vision (North Star)

## Terminal Goal

**An accurate asset dashboard.**

I need to know at any time:
- How much money do I have? Where is it distributed across accounts?
- How much did I earn this month? How much did I spend?
- How are my investments performing?
- What is my annualized income considering ESOP/salary/multiple factors?

### Core Challenge: Data Accuracy

Asset data is scattered across multiple banks and brokers, in various formats (PDF, CSV, images).
Manual entry is prone to omissions; automated parsing can produce errors.
**How do we ensure the dashboard data is accurate?**

---

## Purpose

Build a self-hosted, professional-grade personal finance system that is trustworthy, auditable, and explainable.

**Target Users**
- Individuals and households who want accurate balance sheets, P&L, and cash flow from real accounts.
- Power users who value reconciliation accuracy and full data ownership over convenience.

**Success Outcomes**
- Double-entry bookkeeping is enforced and always balanced.
- Bank/broker statements can be imported and reconciled with high confidence.
- Financial reports are accurate, explainable, and multi-currency aware.
- Self-hosting is first-class: deployable without vendor lock-in.

---

## Core Idea: Confidence Accumulation

Inspired by **knowledge graph construction**:

```
Traditional ETL:
  Raw data → Clean → Load → Query
  (assumes data is correct)

Knowledge Graph:
  Raw data (Mention) → Extract → Entity → Link → Fuse → Knowledge
  (staged confirmation, accumulating confidence)
```

### Our Approach

```
Raw PDF/CSV
    ↓ Adapter extraction (LLM/OCR/model)
Record (source_type + events)
    ↓ Balance verification (machine)
    ↓ Human confirmation (Stage 1)
Confirmed Record
    ↓ Dedup + matching (machine)
    ↓ Human confirmation (Stage 2)
Knowledge (trusted data)
    ↓ Export
Dashboard and reports (referencing Wealthfolio's flow)
```

**Key insight: only confirmed data becomes knowledge.**

---

## Principles

- Accounting integrity is non-negotiable.
- SSOT defines technical truth; this document defines macro intent.
- AI is a parsing and explanation layer, not a source of record.
- Every feature must preserve auditability and traceability.
- Prefer deterministic logic for core bookkeeping and reconciliation.

## Decision Filter

Use this when choices are unclear:
1. Does this improve accuracy, auditability, or reconciliation confidence?
2. Does this keep the system self-hostable and data-private?
3. Does this reduce user cognitive load without hiding critical details?
4. Does it align with the double-entry model and SSOT constraints?

## Non-Goals

- Replacing accounting logic with LLMs.
- Becoming a consumer budgeting app with bank OAuth aggregation.
- Trading, portfolio optimization, or robo-advisory automation.

---

## Design Decisions

> Each decision follows **Problem → Choice → Result** format.
> When future decisions are unclear, return here to check alignment.

### Decision 1: Why Wealthfolio?

**Problem**: Portfolio calculations are complex (IRR, time-weighted returns, multi-currency FX).

**Choice**:
- ❌ Build our own → High effort, error-prone
- ✅ Reuse [Wealthfolio](https://wealthfolio.app/) → Mature open-source solution, we focus on the data pipeline

**Result**: We only need to produce accurate Activity CSV; calculations are delegated to Wealthfolio.

### Decision 2: Why an Event Middle Layer?

**Problem**: Converting directly from PDF to Wealthfolio format?

**Choice**:
- ❌ Direct conversion → Tight coupling between input and output, hard to extend
- ✅ Event middle layer → Decoupled, output target is swappable

**Benefits**:
- Multiple inputs (DBS PDF, Moomoo CSV) → Unified Events
- Unified Events → Multiple outputs (Wealthfolio, custom reports, future integrations)

### Decision 3: Why a Record Layer?

**Problem**: Why not output Events directly?

**Choice**: Introduce a Record layer (source document level).

**Benefits**:
- **Balance verification**: Records have opening/closing balances — `closing = opening + sum(events)`
- **Traceability**: Every Event knows which source file it came from
- **Atomic review**: One PDF is approved/rejected as a unit, no need to review line-by-line

### Decision 4: Why Two-Stage Review?

**Problem**: Too much to review at once?

**Choice**: Split into two stages:
1. **Record-level**: Is this PDF parsed correctly? (single file, easy to judge)
2. **Run-level**: Is the whole batch consistent? (cross-file, look at the big picture)

**Benefits**:
- Catch problems early (parsing errors found in Stage 1)
- Reduce rework (no need to redo everything)
- Lower cognitive load (focus on one dimension at a time)

### Decision 5: Why a Processing Account?

**Problem**: Bank A transfers out, 3 days later Bank B receives — where are the funds in between?

**Choice**: Introduce a virtual Processing account.

```
Day 1: A transfers out
  A: TRANSFER_OUT -10,000
  Processing: TRANSFER_IN +10,000  ← funds in Processing

Day 3: B receives
  Processing: TRANSFER_OUT -10,000
  B: TRANSFER_IN +10,000           ← funds arrive at B
```

**Benefits**:
- At any moment `sum(all accounts) + Processing = constant`
- Delayed transfers never cause funds to "disappear"
- Unpaired transfers are immediately visible (Processing balance ≠ 0)

### Decision 6: Why Manual = TRUSTED?

**Problem**: Some data cannot be automatically imported (ESOP, insurance, loans).

**Choice**: Manual input is treated as highest confidence.

**Logic**:
- User enters manually → User is responsible for accuracy
- No balance verification → Cannot verify (no corresponding bank statement)
- Trust directly → Takes priority when conflicting with other sources

**Priority hierarchy**:
```
Manual (user-entered)  →  TRUSTED   (highest confidence)
User-confirmed         →  HIGH
Auto-matched (≥85)     →  MEDIUM
Auto-parsed            →  LOW       (lowest confidence)
```

**Scenarios**: ESOP vesting, insurance premiums, loans to friends.

### Decision 7: Why FastAPI + Next.js? (Tech Stack Evolution)

**Problem**: Need storage, authentication, background tasks.

**Original choice** (2024): Appwrite → Self-hosted, fast development, data ownership.

**Evolved choice** (2025): FastAPI + Next.js + PostgreSQL.

**Why the change**:
- Appwrite's rigid data model didn't fit double-entry bookkeeping constraints
- Needed fine-grained control over accounting logic and transaction boundaries
- FastAPI + SQLAlchemy gives full control over the data layer
- PostgreSQL's DECIMAL and transaction support are critical for financial accuracy

**Result**: More upfront work, but full control over the domain model. Infrastructure (Docker, Dokploy) handles deployment. See `docs/ssot/development.md` for the current stack.

---

## Tradeoffs

### What We Do
- ✅ Asset tracking (banks, brokers, multi-currency)
- ✅ Data verification (balance reconciliation, human confirmation)
- ✅ Audit trail (immutable, traceable)

### What We Don't Do
- ❌ Spending categorization (fine-grained living expense breakdowns) → Extensible later
- ❌ Budget management → Not a core need
- ❌ Liability tracking (mortgages) → Not supported yet

### Why?
Focus on the core: **asset data accuracy**.
Other features can iterate later, but if the data is wrong, everything is useless.

---

## Where to Look Next

- Technical truth: `docs/ssot/`
- Project status: `docs/project/README.md`
- Developer entry: `README.md`

**Last updated**: 2026-02-23
