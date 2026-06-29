# AC behavioral-evidence pipeline (spike)

A bare `pass` carries ~0 bits of information — it only says "no exception was
raised". Today an AC is counted "covered" if its id string appears in a
CI-executed file that contains *any* assertion token; this proves **presence**,
not **behavior**. This package adds a second, measured signal so a test can say
*how well* it pursued an AC, not just *that it ran*.

## The record

Each `(test, AC)` pair emits a five-field record:

| field        | axis | meaning |
|--------------|------|---------|
| `code`       | L2   | binary outcome (`pass`/`fail`/`skip`/`error`) — hard gate |
| `score`      | L3   | graded signal in `[0,1]` — ratcheted, never regressed |
| `metric`     | —    | **names the yardstick** the score was measured against |
| `provenance` | —    | where the number came from (`deterministic` / `golden_fixture@<ref>` / `live_llm`) |
| `comment`    | —    | human/agent-readable rationale (doubles as an eval record) |

`metric` + `provenance` are the **honesty anchor**: a score must be
`compare(actual, golden)`, not a hand-assigned grade. A self-assigned score is
just `assert True` moved up one level.

## The chain

```
test  --record_ac_evidence(record_property, ...)-->  junit-xml <property>
      --tools/aggregate_ac_evidence.py-->            per-AC aggregate JSON
      --tools/check_ac_score_baseline.py-->          L2 + L3 ratchet gate
```

- **L2 (always hard):** every baselined AC must show `code == pass` this run.
- **L3 (ratchet):** current score ≥ baseline; the baseline only moves up via
  `--update` (mirrors the existing `unified-coverage.json` line-coverage ratchet).
- **New ACs** are informational until adopted — each AC matures from soft to
  enforced on its own schedule. No big-bang migration of the ~1200 ACs.

### CI wiring (blocking, not a follow-up)

The ratchet is a **hard, only-goes-up CI gate** today, not a deferred spike:

- The dedicated `ac-behavioral-ratchet` job in `.github/workflows/ci.yml` waits
  on every test stage that emits junit (`backend`, `backend-integration`,
  `backend-e2e-tier1`, `frontend`), downloads their junit artifacts, runs
  `tools/aggregate_ac_evidence.py` to reduce them per AC, then runs
  `tools/check_ac_score_baseline.py` against the checked-in
  `docs/ssot/ac-score-baseline.jsonl`. It is a **separate** job — not part of
  `ac-traceability`.
- The `finish` aggregation job **requires** `ac-behavioral-ratchet` to succeed
  (both via `needs:` and an explicit `result != "success"` failure check) on the
  PR test path, so a baselined AC that regresses below its score, goes missing,
  or reports a non-`pass` `code` blocks the merge gate — exactly like the
  line-coverage ratchet.
- If no junit evidence reaches the job, the aggregate is empty and every
  baselined AC is reported as `missing`, which fails the gate: a lost or
  un-uploaded artifact cannot pass vacuously.

## Two consumers, one emission

The same emitted record feeds both a deterministic PR gate (stable subset) and a
post-merge eval dashboard (full score distribution, LLM noise tolerated) — the
split already modelled by `trust_mode` on the co-located `@ac_proof`
declarations and the derived critical-proof matrix rendered on demand from the
AC graph.
This is why a separate evaluation engine is unnecessary: the test harness *is*
the eval emitter.

## Anchored ACs (real end-to-end)

Each AC below emits a deterministic, measured score that the blocking ratchet
enforces:

- **AC4.1.4** (reconciliation description similarity) emits its measured
  similarity in `apps/backend/tests/reconciliation/test_reconciliation_scoring.py`.
- **AC8.16.1** (augmentation seam excludes superseded valuations) emits the
  corrected-only net-worth match in
  `apps/backend/tests/integration/test_augmentation_seam_e2e.py`.
- **AC-ledger.6.4** (double-entry posting balances debits == credits) emits the
  measured debit/credit imbalance of a multi-line salary entry posted through the
  real `post_journal_entry` path in
  `apps/backend/tests/ledger/test_accounting_equation.py`. This is the
  reference pattern for anchoring a flagship money journey to L2 + L3.

Seeded baseline: `docs/ssot/ac-score-baseline.jsonl` (sorted, line-oriented JSONL
with `merge=union` so independent ACs auto-merge — one AC per line — instead of
all ACs colliding in one central JSON object). Hermetic proof of the whole chain:
`tests/tooling/test_ac_evidence_pipeline.py`.

## Deliberately **out of scope** (follow-ups)

1. Deriving `code` from the actual test report via a `pytest_runtest_makereport`
   hook instead of trusting the in-body default.
2. A periodic mutation / golden-swap audit that verifies scores actually drop
   when behavior breaks (the real L3 proof).
3. Migrating additional ACs and front-end (vitest) emission.
