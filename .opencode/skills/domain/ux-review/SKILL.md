---
name: ux-review
description: Persona-based UI/UX review ritual for finance_report — walk the core flows as an everyday (non-accountant) user on PC and mobile/PWA, find confusion points, and deliver an ROI-ranked issue set with acceptance criteria. Use when the user asks for a UX review from an ordinary-user or top-designer perspective, or after landing a UI-heavy change.
---

# UX Review — everyday-user persona, ROI-ranked output

Requested near-verbatim in 6 sessions before being encoded. The persona and
the deliverable format below are the user's own recurring spec.

## Persona

An everyday user, not an accountant. They want "how much money do I have,
where is it, what changed this month" answered in seconds. The machinery
(audit, confidence tiers, reconciliation, traceability) must be reachable but
never in the way — trust is shown at the moment of doubt, not up front.

## Standing design decisions (violating these = the finding)

- **Upload is ONE primary statement entry**, with CSV + Manual folded as
  secondary — never a flat list of parallel entries (EPIC-019 / AC19.15).
- **Mobile/PWA uses the bottom-tab IA**: Home · Chat · Add · Audit · More;
  machinery lives under the Audit hub (EPIC-022 PR12).
- **No internal jargon in UI copy** — no repo-speak (SSOT, AC, tier, layer-2);
  plain words an everyday user recognizes.
- Check the owning EPIC (`docs/project/EPIC-019`, `EPIC-022`) before proposing
  IA changes — decisions recorded there outrank reviewer instinct.

## The walk

First-run → upload a statement → parse progress → review flagged items →
dashboard (net worth, distribution) → monthly income/spending → reports →
assistant. Do the full pass twice: PC viewport and mobile/PWA viewport.

Judge at each step: confusion points, dead ends, unexplained states, jargon,
trust moments (does a surprising number offer a path to its source?), and
whether the low-confidence tail — the only thing the user is *supposed* to
look at (vision Axiom B) — is actually the most visible thing.

## Deliverable format (the user's recurring spec)

Item → issue → action → goal → acceptance criteria, **ROI-ranked**. Merge
like-with-like: ~4-5 issues per round, orthogonal to existing ones (amend,
don't duplicate). Screenshots must not contain real financial data (RL-6).

Behavior is proven by tests, but **visual quality is judged by human eyes and
simulators** (AGENTS.md) — recommend and rank; never self-certify a visual
outcome as done.
