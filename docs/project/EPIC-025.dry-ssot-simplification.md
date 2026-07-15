# EPIC-025: DRY/SSOT Simplification — Reporting, Statements, FE Contracts, Tests

<!-- epic-file: design-doc -->
<!-- 0 AC rows by design (#1821 Wave B): every registered AC migrated to the
     `meta` package roadmap (fe-contract-types group); remaining/future scope
     for this EPIC is tracked by GitHub issues + owning package contracts,
     not new EPIC-table rows. -->

> **Status**: 🚧 In Progress
> **Vision Anchor**: `decision-7-tech-stack`
> **Owner**: Platform / Backend / Frontend
> **Phase**: Hardening
> **Dependencies**: EPIC-005 (Reporting), EPIC-003 (Statement Workflow), EPIC-022 (Everyday-User IA)

---

## 🎯 Objective

Close the DRY/SSOT backlog (issue #1158) intentionally deferred from the CI-gate
cleanup. Four large surfaces mix responsibilities or duplicate shared shapes:
reporting calculation vs. orchestration, statement router vs. workflow services,
hand-written frontend contracts vs. OpenAPI-generated types, and repeated test
fixtures. This EPIC removes the duplication **without changing any behavior** —
financial semantics, accounting invariants, AC traceability, and CI gate
coverage are preserved. Each slice is behavior-preserving and independently
verifiable.

---

## 🧭 Plan (STAR)

### Situation
- **Anchor**: The engineering tech-stack discipline (`decision-7-tech-stack`) —
  prefer code-owned / generated single sources of truth over duplicated prose,
  shapes, and inline orchestration.
- **Gap**: `reporting.py` (2.3k LoC) mixes pure calculation with orchestration;
  `routers/statements.py` owns transaction/state-transition boundaries that
  belong in services; `lib/types.ts` re-rolls the `{items,total}` envelope and
  drifts from OpenAPI; reporting tests duplicate chart-of-accounts / golden
  scenario / FX-rate fixtures.

### Tasks
- **Reporting**: extract pure calculation helpers into `services/reporting_calc.py`.
- **Statements**: move approve/reject transaction + state orchestration into a
  `services/statement_workflow.py` contract; keep the router thin.
- **Frontend**: introduce a single `ListResponse<T>` envelope, an OpenAPI
  drift-guard, and pin `lib/api.ts` as the only raw-`fetch` boundary.
- **Tests**: extract shared reporting fixtures; drop duplicate `test_user_id`.

### Actions
1. Create `reporting_calc.py` (pure, DB-free money/period/classification math);
   `reporting.py` imports from it. Public report outputs are byte-identical.
2. Create `statement_workflow.py` with `approve_statement_workflow` /
   `reject_statement_workflow` owning their transaction boundary; routes delegate.
3. Add `ListResponse<T>` to `lib/types.ts`; derive the three list wrappers;
   add `contractTypes.test.ts` (OpenAPI drift + single fetch boundary).
4. Add `tests/reporting/_report_fixtures.py`; adopt it in reporting tests; remove
   duplicate `test_user_id` fixtures.

### Result
- No behavioral change: existing reporting / statement / frontend tests stay green.
- Duplicated shapes and inline orchestration collapse to single owners.

---

## ✅ Scope

- **In**: behavior-preserving extraction/consolidation of the four surfaces above.
- **Out**: any change to financial formulas, accounting sign rules, FX
  conversion, state-machine semantics, API request/response wire shapes, or AC
  coverage. No new product features.

---

## ✅ Must Have

- Reporting calculation helpers live in one importable module; report totals and
  the balance-sheet equation are unchanged.
- Statement approve/reject expose a service-level workflow that owns its
  transaction boundary; the router only maps HTTP↔service.
- The frontend list envelope has a single definition; `lib/api.ts` is the only
  module issuing raw `fetch`.
- Shared reporting test fixtures have one definition; AC traceability is intact.

---

## 🌟 Nice to Have

- Further extraction of reporting export/CSV into a dedicated serializer.
- Generic typed client helpers over `Paths` for path-level FE↔BE typing.

---

## 🧪 Test Cases

> **Test Organization**: Tests organized by feature blocks using ACx.y.z numbering.

### AC25.1 — Reporting calculation extraction

> Migrated (migration closeout wave 2, #1663) to [`common/reporting/contract.py`](../../common/reporting/contract.py)'s `roadmap`: `AC-reporting.dry-ssot.1`.

### AC25.2 — Statement workflow service contract

> Migrated (migration closeout wave 2, #1663) to [`common/extraction/contract.py`](../../common/extraction/contract.py)'s `roadmap`: `AC-extraction.2502.1`.

### AC25.3 — Frontend contract consolidation

> Both rows were `.test.ts` frontend tests; #1820/#1825 later gave the
> governance gate TS test-ref resolution, so they migrated too (below)
> instead of staying blocked on the old Python-only limitation.

(AC25.3.1 removed and AC25.3.2 removed, canonical: migrated to the `meta` package roadmap as `AC-meta.fe-contract-types.1` through `.2`, #1821 Wave B)

### AC25.4 — Test fixture consolidation

> Migrated (migration closeout wave 2, #1663) to [`common/reporting/contract.py`](../../common/reporting/contract.py)'s `roadmap`: `AC-reporting.dry-ssot.2`.

### AC25.5 — Router boundary: no router imports another router (#1097)

> Migrated (migration closeout wave 2, #1663) to [`common/meta/contract.py`](../../common/meta/contract.py)'s `roadmap`: `AC-meta.router.1`.

### AC-counter — Package model: the `counter` worked example (a package = DDD bounded context)

> The package model (a package = a DDD bounded context: `readme.md` +
> `PackageContract` + `base/extension/data` layers (formerly `types/ops/store/api` roles) + `__all__` published language,
> governance computed from contracts) is specified by the meta package itself in
> [../../common/meta/readme.md](../../common/meta/readme.md). The
> `counter` platform package is its first worked example.
>
> **`AC-counter.1.1`, `AC-counter.1.2`, `AC-counter.1.3`, and `AC-counter.1.4` are NOT defined here.**
> They are owned by, and sourced directly from,
> [`common/counter/contract.py`](../../common/counter/contract.py)'s `roadmap`;
> `common/meta/extension/generate_ac_registry.py` reads package-contract roadmaps
> additively, so the AC index counts them without an EPIC-table mirror. This
> blockquote references the IDs (keeping the registry↔EPIC link intact) but
> defines none of them — the contract is the single definition source. This is
> the precedent: a package's ACs live in its contract, never duplicated.

### AC-testing — Package model: the `testing` package (test/fixture-scoped capability)

> The `testing` package (test/fixture-scoped capability code reused across
> backend, tooling, and E2E tests — AC evidence, fixture VOs, and the relocated
> LLM cassette + PDF fixture corpus) is specified by
> [`common/testing/README.md`](../../common/testing/README.md) +
> [`common/testing/contract.py`](../../common/testing/contract.py).
>
> **`AC-testing.1.1` through `AC-testing.8.3` are NOT defined here.** They are
> owned by, and sourced directly from, `common/testing/contract.py`'s
> `roadmap`; `common/meta/extension/generate_ac_registry.py` reads package-contract
> roadmaps additively, so the AC index counts them without an EPIC-table
> mirror. This blockquote references the ids (keeping the registry↔EPIC link
> intact) but defines none of them — the contract is the single definition
> source, per the `counter` precedent above.
>
> Groups 1-8 (`AC-testing.1.*`-`AC-testing.8.*`) migrated from the retired
> EPIC-009 (PDF fixture generation; deleted by #1719 — the
> [`testing` package](../../common/testing/README.md#pdf-fixtures) owns the
> scope) ACs. EPIC-023's cassette layer/streaming-bridge/integrity-gate ACs
> (AC23.5/AC23.6/AC23.7) do NOT migrate here despite their EPIC-authored
> `{tier:CODE-ONLY}` annotation: `common/meta/extension/authority_classifier.py`
> detects any cassette/replay-harness test as the `LLM` band regardless of
> how deterministic its assertions are, which `common/meta/extension/
> check_authority_reconcile.py` enforces against `testing`'s single
> package-wide `CODE-ONLY` tier — see `common/testing/contract.py`'s module
> docstring.

### AC-platform — Platform: domain EventBus via the transactional outbox (meta-layer capability #1)

> The first *runtime* capability of the meta layer: a domain **EventBus
> implemented with the transactional outbox pattern**, in the new
> [`common/platform`](../../common/platform/readme.md) package. A producer
> publishes a `DomainEvent` through an `OutboxEventBus` built from the caller's
> `AsyncSession`, so the event row is written into one shared `outbox` table in
> the SAME transaction as the domain state change (atomic); a separate
> `OutboxRelay` reads committed `pending` rows and dispatches them post-commit
> (at-least-once, so handlers must be idempotent). `counter` now emits its
> `Incremented` event through this bus.
>
> **`AC-platform.1.1`, `AC-platform.1.2`, `AC-platform.1.3`, `AC-platform.1.4`, and `AC-platform.1.5` are NOT defined
> here.** They are owned by, and sourced directly from,
> [`common/platform/contract.py`](../../common/platform/contract.py)'s `roadmap`
> (`AC-platform.1.5` is the cross-package one proving `counter` emits atomically through
> the outbox); `common/meta/extension/generate_ac_registry.py` reads it additively, so the
> AC index counts them without an EPIC-table mirror. This blockquote references
> the IDs (keeping the registry-to-EPIC link intact) but defines none of them —
> the contract is the single definition source, exactly as the `AC-counter`
> precedent.

---

## 📏 Acceptance Criteria

### 🟢 Must Have

| Standard | Verification | Status |
|----------|--------------|--------|
| Reporting math has one owner | `reporting_calc` imported by `reporting` | 🚧 |
| Report behavior unchanged | Existing reporting suite green | 🚧 |
| Statement workflow owns its txn | Service test transitions + commits | 🚧 |
| One FE list envelope + fetch boundary | `contractTypes.test.ts` green | 🚧 |
| One reporting fixture source | `_report_fixtures` adopted | 🚧 |

### 🚫 Not Acceptable

- Any change to financial formulas, sign rules, FX conversion, or wire shapes.
- A statement transitioning without its posting transaction committed atomically.
- A second raw-`fetch` boundary in the frontend.
- Loss of any existing AC's test reference.

---

## 🔗 References

- Issue: #1158
- SSOT Reporting: [../ssot/schema.md](../../common/meta/schema.md)
- Reporting EPIC: [EPIC-005.*](.) · Statement workflow EPIC: [EPIC-003.*](.)
- FE typed contract: `apps/frontend/src/lib/api-schema.ts`
