# `audit` — worklist

The number-governor fold lands in waves (issue #1419, umbrella #1416). This file
tracks what remains after step 2 (AC ownership transfer): step 1 physically
folded `money`/`ratio`/`quantity`/`unit_price` into `audit`; step 2 moved the
value-language ACs into audit's own `roadmap` as `AC-audit.*` — `AC-audit.19.*`/
`.20.*` (was EPIC-002 `AC2.19`/`AC2.20`), `AC-audit.9.*` (Ratio), `.30.*`
(Quantity + ExchangeRate), `.32.*` (UnitPrice), `.33.*` (composite ops), `.36.*`
(decimal scalar codec) — all renamed atomically across `@ac_proof(ac_ids=[...])`
edges, BE/FE traceability docstrings, and `docs/ssot/ac-tier-baseline.json`
(shrunk via `check_ac_tier_baseline.py --update`).

## Next: step 3 (issue #1419 close-out)

Whatever residual references step 2 surfaces (docs/SSOT cross-links, historical
mentions) — tracked in the issue, not yet itemized here.

## Later: audit's own base + extension + data

- `base` — audit's own value objects: financial invariants, confidence /
  provenance, trace records (the "governs number" core).
- `extension` — reach into `ledger` / `extraction` / `portfolio` / `reporting`
  to assert global numeric correctness + end-to-end traceability (closeout #1429).
- `data` — confidence / provenance rollups + the trace-record index (projection).

## Will not do here

- Touch the *content* of the conformance vectors or the BE-FE parity contract —
  only their physical location moved (into `audit`), the language-neutral
  standard itself is unchanged.
- Rename the colliding error classes (`FloatNotAllowedError` etc., independently
  defined per domain) to enable a flatter `audit.*` namespace — the submodule
  design (`audit.money`, `audit.ratio`, ...) avoids needing this.
