# Finance Report Vision

## Terminal Goal

**A generated personal financial-report package backed by an accurate asset
dashboard.**

The final product should generate a self-hosted personal financial report
package whose structure is inspired by US GAAP and Hong Kong listed-company
reporting: statements, schedules, notes, and source traceability. It is a
personal management report, not a regulated filing, audit opinion, legal
advice, or tax advice.

At any time, the system should help answer:

- Can I generate one auditable personal report package from trusted source
  data?
- How much money do I have, and where is it distributed?
- How much did I earn and spend this month?
- How are my investments performing?
- What is my annualized income across salary, ESOP, dividends, and other
  long-term components?

## Core Challenge

Financial data is scattered across banks, brokers, statements, PDFs, CSVs, and
manual records. Manual entry can omit data; automated extraction can be wrong.

The product exists to make asset data trustworthy, auditable, and explainable.

## Product Principles

- Accounting integrity is non-negotiable.
- Confirmed data is more valuable than merely imported data.
- AI may parse, classify, explain, and suggest; it must not become the source of
  record.
- Deterministic logic owns core bookkeeping and report calculations.
- Human review should reduce uncertainty without hiding important details.
- Self-hosting and data ownership are first-class constraints.
- Every workflow should preserve traceability from source document to ledger to
  report.

## Confidence Accumulation

The guiding model is staged confidence:

```text
raw source
  -> extracted record
  -> machine validation
  -> human confirmation
  -> reconciliation and deduplication
  -> trusted ledger knowledge
  -> dashboard and reports
```

Only trusted or explicitly reviewed data should drive conclusions that claim to
be accurate.

<a id="decision-filter-accuracy-auditability"></a>

## Decision Filter

Use this when product or architecture choices are ambiguous:

1. Does it improve accuracy, auditability, or reconciliation confidence?
2. Does it keep the system self-hostable and data-private?
3. Does it reduce user cognitive load without hiding critical details?
4. Does it preserve double-entry integrity and traceability?
5. Can the behavior be expressed as EPIC -> AC -> test?

If the answer is unclear, choose the smaller step that improves proof quality.

## Strategic Decisions

### Personal Report Package Is The North-Star Output

Dashboards are working surfaces; the durable product output is a generated
personal financial-report package. The package should include balance sheet,
income statement, cash-flow view, investment schedules, annualized income and
long-term compensation schedules, notes, and source-to-ledger-to-report
traceability.

US GAAP and Hong Kong listed-company reporting are reference structures for
coverage, naming, and disclosure discipline. The system must not claim filing
compliance unless that scope is explicitly registered, tested, and reviewed.

<a id="decision-1-portfolio-self-developed"></a>

### Portfolio Is Native

Portfolio management is part of the system, not an external integration layer.
The product should support holdings, cost basis, dividends, allocation, and
performance metrics while remaining tied to the accounting model.

<a id="decision-2-event-middle-layer"></a>
<a id="decision-3-record-layer"></a>

### Record Layer Before Ledger Knowledge

Source documents should be reviewed as records before they become trusted
ledger facts. A record carries source metadata, validation results, and
traceability back to the original file.

<a id="decision-4-two-stage-review"></a>

### Two-Stage Review

Review should separate:

1. **Record-level review**: did this source parse correctly?
2. **Run-level review**: does the whole batch reconcile consistently?

This keeps local parse errors from being mixed with cross-document consistency
questions.

<a id="decision-5-processing-account"></a>

### Processing Account For In-Transit Funds

Transfers can leave one account before arriving in another. A virtual
Processing account makes in-transit funds visible instead of letting money
appear to disappear.

### Manual Data Is Explicitly Trusted

Some assets and liabilities cannot be verified by imported statements. Manual
records are trusted because the user explicitly supplied them, but they should
remain clearly labeled as manual/trusted data.

<a id="decision-7-tech-stack"></a>

### FastAPI + Next.js + PostgreSQL

The current stack exists because the domain needs transactional control,
Decimal-safe accounting, explicit schemas, and a self-hostable deployment model.

## Non-Goals

- Replacing accounting logic with LLMs.
- Regulated US/HK filing compliance, XBRL filing, audit opinions, legal advice,
  or tax advice.
- <a id="non-goals-not-budgeting-app"></a>Becoming a consumer budgeting app
  centered on bank OAuth aggregation.
- <a id="non-goals-not-robo-advisor"></a>Trading, portfolio optimization, or
  robo-advisory automation.

## Relationship To Project Documents

This file does not own project status. Current implementation status lives in
`README.md`, EPIC scope lives in `docs/project/`, and proof lives in AC
registries plus tests.

Vision changes should be rare and directional. Implementation details should be
captured as EPIC -> AC -> test, or as code-owned contracts referenced by docs.
