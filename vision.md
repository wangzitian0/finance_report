# Finance Report Vision

## Terminal Goal

**A generated personal financial-report package backed by an accurate asset
dashboard and an explainable financial assistant.**

The final product should generate a self-hosted personal financial report
package whose structure is inspired by US GAAP and Hong Kong listed-company
reporting: statements, schedules, notes, and source traceability. It is a
personal management report, not a regulated filing, audit opinion, legal
advice, tax advice, or regulated investment advice.

## Product Promise

The user should only need to upload financial source documents, such as bank
statements, brokerage statements, settlement notes, ESOP/RSU plan documents,
property or liability statements, CSV exports, and other supported records.

After upload, the system should automate the rest where the behavior can be
made trustworthy: extraction, validation, deduplication, reconciliation, FX and
stock-price refresh, ESOP and long-term compensation schedules, recurring fixed
expense accruals or pre-deductions, dashboard updates, and report-package
preparation.

Human review remains part of the product when source data is missing,
ambiguous, material, or inconsistent.

At any time, the system should help answer:

- Can I generate one auditable personal report package from trusted source
  data?
- How much money do I have, and where is it distributed?
- How much did I earn and spend this month?
- How are my investments performing?
- What is my annualized income across salary, ESOP, dividends, and other
  long-term components?
- What financial suggestions should my assistant surface from trusted data,
  known limitations, and pending actions?

## Core Challenge

Financial data is scattered across banks, brokers, statements, PDFs, CSVs, and
manual records. Manual entry can omit data; automated extraction can be wrong.

The product exists to make asset data trustworthy, auditable, explainable, and
useful for personal financial decisions.

## Product Principles

- Accounting integrity is non-negotiable.
- Confirmed data is more valuable than merely imported data.
- AI may parse, classify, explain, and suggest; it must not become the source of
  record.
- Deterministic logic owns core bookkeeping and report calculations.
- Automation should reduce user effort without hiding uncertainty.
- Human review should focus on uncertainty, exceptions, and material judgments.
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
  -> dashboard, assistant, and reports
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

## Directional Commitments

These commitments describe product direction. Implementation contracts belong
in `docs/ssot/`; delivery scope belongs in `docs/project/`.

### Personal Report Package Is The North-Star Output

Dashboards are working surfaces; the durable product output is a generated
personal financial-report package with report sections, schedules, notes, and
source-to-ledger-to-report traceability. Reporting contracts are owned by
`docs/ssot/reporting.md` and `docs/ssot/framework-reporting.md`.

<a id="decision-1-portfolio-self-developed"></a>

### Portfolio Is Native

Portfolio management is part of the system, not an outsourced portfolio SaaS.
Holdings, cost basis, dividends, allocation, performance, and restricted
compensation must remain tied to the accounting and reporting model. Detailed
contracts are owned by `docs/ssot/assets.md` and `docs/ssot/reporting.md`.

<a id="decision-2-event-middle-layer"></a>
<a id="decision-3-record-layer"></a>

### Uploaded Sources Become Reviewed Records Before Ledger Knowledge

Uploaded documents should become traceable records before they become trusted
ledger facts. The upload, extraction, record, workflow-event, and review
contracts are owned by `docs/ssot/extraction.md`,
`docs/ssot/workflow-events.md`, and `docs/ssot/confirmation-workflow.md`.

<a id="decision-4-two-stage-review"></a>

### Review Separates Source Accuracy From Batch Consistency

Review should separate whether a source parsed correctly from whether the full
batch reconciles consistently. Detailed review-state rules are owned by
`docs/ssot/confirmation-workflow.md` and `docs/ssot/reconciliation.md`.

<a id="decision-5-processing-account"></a>

### In-Transit Funds Must Stay Visible

Transfers can leave one account before arriving in another. In-transit value
must remain visible and reconcilable instead of disappearing from net worth.
The detailed Processing account contract is owned by
`docs/ssot/processing_account.md`.

### Manual Data Is Explicitly Trusted

Some assets and liabilities cannot be verified by imported statements. Manual
records are trusted because the user explicitly supplied them, but they must
remain clearly labeled as manual data. Source-type priority is owned by
`docs/ssot/source-type-priority.md`.

<a id="decision-7-tech-stack"></a>

### The Stack Must Stay Self-Hostable

The stack should support transactional control, Decimal-safe accounting,
explicit schemas, private deployment, and reproducible CI. Runtime and
environment contracts are owned by `docs/ssot/development.md`,
`docs/ssot/schema.md`, and `docs/ssot/deployment.md`.

## Non-Goals

- Replacing accounting logic with LLMs.
- Regulated US/HK filing compliance, XBRL filing, audit opinions, legal advice,
  tax advice, or regulated investment advice.
- <a id="non-goals-not-budgeting-app"></a>Becoming a consumer budgeting app
  centered on bank OAuth aggregation.
- <a id="non-goals-not-robo-advisor"></a>Automated trading, portfolio
  optimization, or robo-advisory execution.

## Relationship To Project Documents

This file does not own project status. Current implementation status lives in
`README.md`, EPIC scope lives in `docs/project/`, and proof lives in AC
registries plus tests.

Vision changes should be rare and directional. Implementation details should be
captured as EPIC -> AC -> test, or as code-owned contracts referenced by
`docs/ssot/`.
