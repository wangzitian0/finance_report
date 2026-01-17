# Finance Report Target (North Star)

**Purpose**
Build a self-hosted, professional-grade personal finance system that is trustworthy, auditable, and explainable.

**Target Users**
- Individuals and households who want accurate balance sheets, P&L, and cash flow from real accounts.
- Power users who value reconciliation accuracy and full data ownership over convenience.

**Success Outcomes**
- Double-entry bookkeeping is enforced and always balanced.
- Bank/broker statements can be imported and reconciled with high confidence.
- Financial reports are accurate, explainable, and multi-currency aware.
- Self-hosting is first-class: deployable without vendor lock-in.

**Non-Goals**
- Replacing accounting logic with LLMs.
- Becoming a consumer budgeting app with bank OAuth aggregation.
- Trading, portfolio optimization, or robo-advisory automation.

**Principles**
- Accounting integrity is non-negotiable.
- SSOT defines technical truth; this document defines macro intent.
- AI is a parsing and explanation layer, not a source of record.
- Every feature must preserve auditability and traceability.
- Prefer deterministic logic for core bookkeeping and reconciliation.

**Decision Filter**
Use this when choices are unclear:
1. Does this improve accuracy, auditability, or reconciliation confidence?
2. Does this keep the system self-hostable and data-private?
3. Does this reduce user cognitive load without hiding critical details?
4. Does it align with the double-entry model and SSOT constraints?

**Where to Look Next**
- Technical truth: `docs/ssot/`
- Project status: `docs/project/README.md`
- Developer entry: `README.md`

**Last updated**: 2026-01-18
