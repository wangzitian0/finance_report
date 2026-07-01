# `audit` — worklist

The number-governor fold lands in waves (issue #1419, umbrella #1416). This file
tracks what remains after step 1, the physical fold (registering `audit`,
relocating `money`/`ratio`/`quantity`/`unit_price` code+tests+conformance vectors
into `audit`, declaring the Shared-Kernel `units`, pinning the number-governor
invariants).

## Next: AC ownership transfer (its own atomic cutover)

Move the value-language ACs from their EPIC tables into audit's `roadmap` as
`AC-audit.*`, deleting the EPIC rows (DoD: a single home; no AC in both an EPIC
table and a roadmap). This is deferred because the value ACs are wired into more
than the EPIC table, and all references must move atomically or the per-type
PROTECTION count floor regresses:

- EPIC-002: `AC2.19.1`, `AC2.19.2`, `AC2.20.1` (Money / Currency / FX convert).
- EPIC-012: `AC12.9.*` (Ratio), `AC12.30.*` (Quantity + ExchangeRate),
  `AC12.32.*` (UnitPrice), `AC12.33.*` (composite ops), `AC12.36.*` (decimal
  scalar codec).
- Each move must also rename: every `@ac_proof(ac_ids=[...])` edge, the
  traceability docstring references in the BE *and* FE tests, and the tier
  baseline (`docs/ssot/ac-tier-baseline.json`) — keeping registry-eligible
  numeric ids (`AC-audit.<n>.<n>`) so `has_real_ref` / `has_proof` counts stay at
  or above `docs/ssot/protection-floor.json`.
- Edit only the audit/value rows: EPIC-012 is shared with middleware (leave its
  rows); EPIC-001 is identity's.

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
