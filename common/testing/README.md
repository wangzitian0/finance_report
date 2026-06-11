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

## Two consumers, one emission

The same emitted record feeds both a deterministic PR gate (stable subset) and a
post-merge eval dashboard (full score distribution, LLM noise tolerated) — the
split already modelled by `trust_mode` in `docs/ssot/critical-proof-matrix.yaml`.
This is why a separate evaluation engine is unnecessary: the test harness *is*
the eval emitter.

## Scope of this spike

- Wired exactly one real AC end-to-end: **AC4.1.4** (reconciliation description
  similarity) emits its measured similarity in
  `apps/backend/tests/reconciliation/test_reconciliation_scoring.py`.
- Seeded baseline: `docs/ssot/ac-score-baseline.json`.
- Hermetic proof of the whole chain: `tests/tooling/test_ac_evidence_pipeline.py`.

## Deliberately **out of scope** (follow-ups)

1. Wiring `tools/check_ac_score_baseline.py` into the blocking CI `ac-traceability`
   job (needs backend-junit → aggregator artifact plumbing across CI jobs).
2. Deriving `code` from the actual test report via a `pytest_runtest_makereport`
   hook instead of trusting the in-body default.
3. A periodic mutation / golden-swap audit that verifies scores actually drop
   when behavior breaks (the real L3 proof).
4. Migrating additional ACs and front-end (vitest) emission.
