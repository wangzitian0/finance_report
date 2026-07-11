---
name: planning
description: Goal-first planning for finance_report system reviews, issue design/triage, prioritization, and "what should we do next" asks. Use BEFORE creating or restructuring GitHub issues, when reviewing a subsystem (testing, CI, delivery, UX), when ranking a backlog by ROI, or whenever the deliverable is a plan or issue tree rather than code. Enforces Vision → Guarantees → Gaps → Actions with a mandatory counterfactual pass and this repo's issue conventions.
---

# Planning — goal-first, counterfactual-gated

The normative work order lives in
[docs/agents/orchestration.md → Planning Work Order](../../../../docs/agents/orchestration.md).
This skill carries the rituals and templates. History: it took one 8-round
session (2026-07-12) for a bottom-up "survey what exists, then rationalize"
review to converge on a usable plan; the goal-first order below is what that
convergence actually followed.

## The order (never skip step 1)

1. **Vision first** — read [vision.md](../../../../vision.md); restate the
   terminal goal, the North-Star metric, and the axioms relevant to the ask
   *before* surveying any code or issues.
2. **Guarantees** — derive what must hold for the goal (walk the data
   pipeline end-to-end: source → extraction → trust boundary → ledger/report
   math → deployed serving, plus the meta-layer "gates can't go vacuous").
   State guarantees, not tasks. Argue completeness (what does the walk miss?).
3. **Gaps** — audit current state against the guarantees. Bottom-up inventory
   is evidence-gathering only — the conclusion must be derived downward.
4. **Actions** — minimal set covering the gaps. Prefer a *mechanism* that
   bounds work (a ratchet, a delete-as-you-touch rule) over a big-bang project
   that will never be scheduled.
5. **Counterfactual pass** — before presenting, answer in writing:
   - If every acceptance criterion here is met, what still fails?
   - Which numbers in this plan are measured vs. guessed?
   - Does any acceptance criterion describe a task instead of a guarantee?
   - What is each action's lock mechanism against silent regression?
   - Which inputs can only the operator provide? (Name them.)

## Root-issue template (acceptance = guarantees)

```markdown
# Root: <one-line problem statement>

> Goal derivation: <which vision axiom/metric this serves, in 2-3 sentences>

## Core problem
<mechanism, with measured evidence — file:line, counts, incident links>

## Solution shape
<mechanisms are suggestions; the Acceptance guarantees are the contract>

## Acceptance — each line is a guarantee, not a task
- [ ] G-<name>: <outcome that must hold> — enforced by <lock mechanism>
- [ ] ...

## Operator dependency (if any)
<inputs only the user can provide — real documents, product judgment, merges>

## Known residuals — named, deliberately not owned here
<what stays unguarded even at 100% acceptance, and why that's accepted>

## Relations
<peers / parents / lineage — native sub-issues for execution children>
```

## Issue hygiene

- **No issues during exploration.** A structure must survive one
  simplification pass + one counterfactual pass in conversation first
  (create-then-close-within-days is a process failure, not progress).
- **Orthogonality test**: orthogonal to every existing issue → new issue;
  overlapping → amend the existing one. Prefer amending an existing EPIC over
  creating a new one.
- **One root per problem**, execution children as native GitHub sub-issues;
  close superseded issues with a stated reason (`not_planned` vs `completed`
  matters).
- **Merge like-with-like**: the user's bar is ~4-5 issues per review round,
  not one issue per finding.

## Plan-output defaults

- **Minimum-PR plan is a first-class output**: batch cohesive issues into one
  PR; independent PRs run in parallel (bounded by write conflicts, never by
  compute — vision Good Taste 6). State the PR count explicitly.
- **ROI-ranked ordering**: every backlog presentation is ranked by
  impact-per-effort, with the ranking rationale stated.
- **Deliverable structure the user expects**: item → issue → action → goal →
  acceptance criteria.
