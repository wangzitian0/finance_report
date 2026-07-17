# `audit` — worklist

The number-governor fold lands in waves (issue #1419, umbrella #1416). This file
tracks what remains after step 2 (AC ownership transfer): step 1 physically
folded `money`/`ratio`/`quantity`/`unit_price` into `audit`; step 2 moved the
value-language ACs into audit's own `roadmap` as `AC-audit.*` — `AC-audit.19.*`/
`.20.*` (was EPIC-002 `AC2.19`/`AC2.20`), `AC-audit.9.*` (Ratio), `.30.*`
(Quantity + ExchangeRate), `.32.*` (UnitPrice), `.33.*` (composite ops), `.36.*`
(decimal scalar codec) — all renamed atomically across `@ac_proof(ac_ids=[...])`
edges, BE/FE traceability docstrings, and `common/meta/data/ac-tier-baseline.json`
(shrunk via `check_ac_tier_baseline.py --update`).

## Next: step 3 (issue #1419 close-out)

Whatever residual references step 2 surfaces (docs/SSOT cross-links, historical
mentions) — tracked in the issue, not yet itemized here.

## Audit assurance migration (#1906)

- PR-A establishes the TraceRecord model, codec, repository, shadow adapters,
  and fixed-cohort projection.
- Package replacement PRs cut consumers over and delete their local authority
  inference paths.
- PR-Z deletes the explicitly composed shadow compatibility seams and legacy
  trust projections after every package replacement is green.

## Will not do here

- Touch the *content* of the conformance vectors or the BE-FE parity contract —
  only their physical location moved (into `audit`), the language-neutral
  standard itself is unchanged.
- Rename the colliding error classes (`FloatNotAllowedError` etc., independently
  defined per domain) to enable a flatter `audit.*` namespace — the submodule
  design (`audit.money`, `audit.ratio`, ...) avoids needing this.
