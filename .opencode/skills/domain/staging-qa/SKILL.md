---
name: staging-qa
description: Real-device staging QA ritual for finance_report — walk https://report-staging.zitian.party with the operator's real statements, read backend logs on the VPS, and file redaction-safe bug issues. Use when the user asks to test staging, find staging bugs, do a real-data QA round, or verify a staging deploy before release.
---

# Staging QA — real documents, real logs, redacted reports

The one loop that has historically found the bugs CI cannot: live extraction
against the operator's real statements. Every round of it (2026-06-26,
2026-06-29, 2026-07-10) surfaced production-class bugs that all synthetic
gates passed.

## Setup

- **App**: https://report-staging.zitian.party — verify the deployed version
  first (health endpoint / footer) so findings attribute to the right build.
- **Test data**: the operator's real statements (they supply; typically from
  their local archive). NEVER copy real documents into the repo, issues, or
  scratch dirs that outlive the session.
- **Backend logs**: SSH to the VPS (address + credentials via local direnv /
  1Password; see `repo/docs/ssot/ops.pipeline.md`), then
  `docker logs finance_report-backend-staging --tail 200`. Read-only — never
  modify via SSH (orchestration.md operational guideline #1).

## The walk (assert numbers, not rendering)

1. Upload — through the canonical **single statement entry** (CSV + Manual are
   folded secondary entries; if you see parallel entries, that itself is a bug
   — standing design decision, EPIC-019/AC19.15).
2. Parse status → review queue → reconcile → balance sheet / dashboard →
   reports.
3. At each step verify **values**, not just page-loads: opening/closing
   balances reconcile to the statement, totals match, currency labels agree
   end-to-end, confidence/validated badges are earned (not vacuous).
   Past bug classes to re-probe: hardcoded currency, net-flow shown as
   balance, `balance_validated` true with nothing validated, stuck-in-parsing
   documents.

## Filing what you find

- **RL-6 first**: placeholder amounts/merchants/account digits ONLY. Grep
  every draft for real values before posting — issue titles included.
- Each bug: root cause (mechanism, not symptom) + **which gate should have
  caught it** (bug-fix work order in orchestration.md) — then the fix PR
  back-fills that gate.
- Batch findings into per-subsystem issues (the user's bar: a handful, not
  one per symptom), ROI-ranked.
- Every real-document extraction bug also adds a case to the real-corpus eval
  (#1764's G-growth guarantee) before its fix-issue closes.
