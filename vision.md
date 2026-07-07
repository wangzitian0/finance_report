# Finance Report Vision

This file is culture, not specification. It carries the few irreducible bets
and the rules for choosing when those bets conflict. It does not own status,
scope, or contracts — see [Where Detail Lives](#where-detail-lives).

## Terminal Goal

**A generated personal financial-report package backed by an accurate asset
dashboard and an explainable financial assistant.**

The output is a self-hosted personal report package — statements, schedules,
notes, and source traceability — whose structure is inspired by US GAAP and
Hong Kong listed-company reporting. The US public-company framing is not
decoration: it is our schema discipline (see Axiom C). It is a personal
management report, not a regulated filing, audit opinion, legal advice, tax
advice, or regulated investment advice.

## Why This Exists

Financial data is scattered across banks, brokers, statements, PDFs, CSVs, and
manual records. Manual entry can omit data; automated extraction can be wrong.

The product exists to make asset data trustworthy, auditable, explainable, and
useful for personal financial decisions. The user uploads source documents; the
system automates the rest wherever the behavior can be made trustworthy, and
asks for human attention only where it cannot.

At any time, the system should help answer:

- Can I generate one auditable personal report package from trusted source
  data?
- How much money do I have, and where is it distributed?
- How much did I earn and spend this month?
- How are my investments performing?
- What is my annualized income across salary, ESOP, dividends, and other
  long-term components?
- What should my assistant surface from trusted data, known limitations, and
  pending actions?

## The Axioms

These are the irreducible bets. When a product or architecture choice is
ambiguous, derive the answer from these axioms first, then from the
[Trade-off Rules](#trade-off-rules), then from the
[Decision Filter](#decision-filter).

### Axiom A — Data is append-only; truth is recomputed, not edited

Stored facts only accumulate; a recorded fact is never changed in place. Truth
itself may change — a later statement corrects an earlier one, a price refreshes
— but it changes by **recomputing from the accumulated record**, never by
editing history.

Every value carries a version, and one version maps to exactly one value as it
propagates downstream. That is what lets the same number be both auditable and
current: pin a version and it stays reproducible; recompute and it stays fresh.
Append-only history plus versioned recomputation is what gives us retrospective
analysis. (How the layers and versions are actually structured is implementation,
owned downstream — not here.)

### Axiom B — Automation by default; attention only on the low-confidence tail

The default is fully automatic. The user is asked to look only at the nodes the
system flags — the issues automated review could not resolve with confidence.

Confidence is a first-class, measured property, co-equal with traceability.
What we ask a human to review, or an engineer to redesign, is exactly the
computation that — in hindsight — looks low-confidence. The same problem has a
macro face (which nodes the user reviews) and a micro face (which computations
the team improves). The mission over time is to **drive the proportion of
low-confidence data down**.

### Axiom C — Boundaries are risk-managed, not absolute

Our hard constraints are managed as risk, not absolutes.

- **Privacy / self-hosting**: the rule is *no catastrophically short stave*, not
  *no data ever leaves the box*. A trusted vendor leaking is a low-probability
  event; sending a statement image to a trusted extraction provider is
  acceptable. What is not acceptable is a single weak link far worse than the
  rest.
- **Schema**: the messy variety of real-world instruments is absorbed by
  adopting the discipline of US public-company reporting. Public companies have
  already generalized the fancy operations; we align to that standard rather
  than invent our own. Minor representational gaps are tolerable.
- **Process hygiene**: the same stave discipline applies to how we build. Real
  financial data — amounts, balances, account numbers, holder names — never
  appears in issues, PRs, commits, logs, or reports; development artifacts are
  a public surface, and one leaked statement is a catastrophically short stave.

### Axiom D — The model generalizes; code guarantees the number; key nodes keep slack

We are an AI-driven product, and the division of labor is drawn on purpose:

- **Reach for the model where a decision needs generalization.** Parsing,
  classifying, matching, explaining, judging the ambiguous case — default to the
  model, because that is where generalization beats hand-tuned rules. An
  AI-driven product pushes decisions *toward* the model, not away from it; a wall
  of brittle thresholds where a model would generalize is a smell, not a safeguard.
- **Code guarantees the number.** Money, accounting caliber, standardization, and
  every report line are owned by deterministic code — Decimal-safe, balanced,
  versioned. The model may *propose*; only code *disposes* a value into the ledger
  or a report. (This is the bound in [Trade-off Rule 5](#trade-off-rules);
  confidence governs the handoff per Axiom B.)
- **Key nodes keep slack.** A critical node carries tolerance instead of chasing
  infinite precision. We would rather bend and flag for review than hard-fail on a
  sub-cent drift or a transient hiccup. The slack lives in *thresholds and flow* —
  whether to auto-accept or escalate — never in the correctness of the number
  itself. Brittleness from over-specified detail is a defect, not rigor.

### Axiom E — Production trust is part of the product

A system that guards the user's numbers must also guard itself, by the same
standard it applies to data:

- **The system observes itself and fails closed.** A deployed tier declares
  what it requires; when a required dependency is absent, it refuses to look
  healthy. An unobserved production surface is treated exactly like
  low-confidence data — it is the part we do not yet trust, and the mission is
  to shrink it.
- **Required-in-production is an SLA commitment.** Declaring a dependency
  required is a promise that someone watches it continuously — its absence is
  discovered by the system within minutes, not by the next release's smoke
  test days later.
- **Alerting is judged by actionability.** One incident reads as one thread
  with its evidence attached. A storm of technically-true alerts that nobody
  can act on protects nothing; noise is a defect of the net, not of the
  operator's attention.

## North-Star Metric

**The proportion of low-confidence data trends down over time.** This is the
single measurable expression of the axioms: more data crossing from
machine-uncertain to trusted, with traceability intact, and less human attention
required per unit of trust.

## Trade-off Rules

When two goods conflict, the higher rule wins.

1. **Append-only over in-place truth.** The live number is a recompute; history
   is never edited to make it look right. (Axiom A)
2. **Accuracy over coverage.** Support fewer sources well before supporting many
   unreliably.
3. **Auditability over convenience — but automation stays the default.** We do
   not collapse source→ledger→report traceability for a cleaner surface. The
   cost of trust is paid as confidence-flagged review, not blanket manual entry.
   (Axiom B)
4. **No short stave over absolute isolation.** We drop a feature before we accept
   a weakest link far worse than the rest — but not before we accept a
   low-probability, well-bounded one. (Axiom C)
5. **Deterministic logic owns the number.** Anything that lands a value in the
   ledger or a report line is deterministic. AI may parse, classify, explain, and
   suggest; it is measured by confidence and never becomes the source of record.
   (Axiom D)
6. **Tolerance over infinite detail at a node.** When a node can either hard-fail
   on perfect precision or bend within a bounded tolerance and escalate, it bends:
   slack that degrades to review beats rigidity that breaks. This never overrides
   Rule 5 — the bend is in thresholds and flow, never in whether the ledger
   balances or a number is correct. (Axiom D)

If a choice still feels balanced after these rules, run the Decision Filter and
take the smaller step that improves proof quality.

## Good Taste

Culture for *how* we build — the craft counterpart to the axioms. The
trade-off rules say *what* to choose; these say whether the thing is built well.

1. **Good taste — kill the special case.** Re-see the problem so the edge case
   becomes the normal path; deleting a branch beats guarding it. Taste is
   earned by experience, not won by argument.
2. **Never break the user's trust.** Breaking a working report, a stored fact,
   or a published contract is a bug — however "theoretically correct."
   Backward compatibility of trusted data and contracts is sacred; we serve the
   user's data, we do not re-educate it. (Axiom A, pointed at our users.)
3. **Pragmatism over purity.** Solve the real problem in front of us, not a
   hypothetical one; reject the elegant-on-paper design that is complex in
   practice. Code serves reality, not a research paper.
4. **Simplicity is the standard.** One function, one thing, done well and
   short; past three levels of nesting, fix the function, not the symptom.
   Over-specified complexity is a defect, not rigor. (Axiom D.)
5. **A safety net that can silently degrade is not a safety net.** Prove a
   behavior against a real oracle, then lock the proof so no later change can
   hollow it out. A gate that can go vacuous while staying green is worse than
   no gate — it keeps spending trust it no longer earns. (Axiom E, pointed at
   our own tests and gates.)
6. **Human judgment is the scarce resource.** Machine time is cheap; the
   user's review bandwidth is not. Parallel work is bounded by write conflicts,
   not by compute cost. Behavior is proven by tests; visual quality is judged
   by human eyes on real screens. Spend compute freely to save judgment, never
   the reverse.

These govern *how* a change is built; when they still leave the choice
ambiguous, run the Decision Filter.

<a id="decision-filter-accuracy-auditability"></a>

## Decision Filter

Use this when the axioms and trade-off rules still leave a choice ambiguous:

1. Does it improve accuracy, auditability, or reconciliation confidence?
2. Does it keep the system self-hostable and data-private (no short stave)?
3. Does it reduce user cognitive load without hiding critical details?
4. Does it preserve double-entry integrity and traceability?
5. Can the behavior be expressed as EPIC -> AC -> test?

If the answer is unclear, choose the smaller step that improves proof quality.

## Directional Commitments

Settled directions that the rest of the repo anchors to. Each one carries a
cost; if it did not, it would not be a commitment. Implementation contracts are
owned under [Where Detail Lives](#where-detail-lives).

<a id="decision-1-portfolio-self-developed"></a>
**Portfolio is native.** Holdings, cost basis, dividends, allocation,
performance, and restricted compensation stay tied to the accounting and
reporting model — even at the cost of not outsourcing to a portfolio SaaS that
would be faster to ship.

<a id="decision-2-event-middle-layer"></a>
<a id="decision-3-record-layer"></a>
**Uploaded sources become reviewed records before ledger knowledge.** An upload
becomes a traceable record, then a trusted ledger fact — even at the cost of an
extra event/record layer between import and conclusion.

<a id="decision-4-two-stage-review"></a>
**Review separates source accuracy from batch consistency.** Whether a source
parsed correctly is judged apart from whether the full batch reconciles — even at
the cost of two review concerns instead of one.

<a id="decision-5-processing-account"></a>
**In-transit funds stay visible.** Value that has left one account but not
arrived in another remains visible and reconcilable in a Processing account —
even at the cost of carrying balances that are not yet settled anywhere.

**Manual data is explicitly trusted.** Assets that no statement can verify are
trusted because the user supplied them — at the cost of labeling them clearly as
manual so they never masquerade as imported proof.

<a id="decision-7-tech-stack"></a>
**The stack stays self-hostable.** Transactional control, Decimal-safe
accounting, explicit schemas, private deployment, reproducible CI — even at the
cost of declining managed services that would break private hosting.

## Non-Goals

- Replacing accounting logic with LLMs.
- Regulated US/HK filing compliance, XBRL filing, audit opinions, legal advice,
  tax advice, or regulated investment advice.
- <a id="non-goals-not-budgeting-app"></a>Becoming a consumer budgeting app
  centered on bank OAuth aggregation.
- <a id="non-goals-not-robo-advisor"></a>Automated trading, portfolio
  optimization, or robo-advisory execution.

## Where Detail Lives

This file holds no contracts, status, or enumerations. They live with their
owners:

- **Implementation contracts** → `docs/ssot/`, routed by
  `docs/ssot/MANIFEST.yaml` (one owner per concept). The staged
  confidence pipeline (raw -> extracted -> validated -> confirmed -> reconciled
  -> trusted -> reports) is owned by `docs/ssot/confirmation-workflow.md`;
  supported source classes by
  [`source_coverage_matrix`](docs/ssot/source-coverage-matrix.yaml).
- **Delivery scope & status** → `docs/project/` (EPICs) and `README.md`.
- **Agent process & governance** → `AGENTS.md` and `docs/agents/`.

Vision changes should be rare and directional. Implementation belongs in
EPIC -> AC -> test, or in code-owned contracts referenced by `docs/ssot/`.
