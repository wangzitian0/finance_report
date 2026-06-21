# EPIC-025: DRY/SSOT Simplification — Reporting, Statements, FE Contracts, Tests

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

| ID | Requirement | Test Function | File | Priority |
|----|-------------|---------------|------|----------|
| AC25.1.1 | Pure reporting math (money quantization, accounting sign rules, period boundaries, income-bucket classification) is provided by `services.reporting_calc` and re-used by `services.reporting`; the balance-sheet equation and report totals are unchanged | `test_reporting_calc_extraction` | `apps/backend/tests/reporting/test_reporting_calc_extraction.py` | P1 |

### AC25.2 — Statement workflow service contract

| ID | Requirement | Test Function | File | Priority |
|----|-------------|---------------|------|----------|
| AC25.2.1 | `approve_statement_workflow` / `reject_statement_workflow` own the transaction + state transition (PARSED→APPROVED/REJECTED) at the service layer, returning the updated statement; the router delegates and stays thin | `test_statement_workflow_service` | `apps/backend/tests/api/test_statement_workflow_service.py` | P1 |

### AC25.3 — Frontend contract consolidation

| ID | Requirement | Test Function | File | Priority |
|----|-------------|---------------|------|----------|
| AC25.3.1 | The list-response envelope has a single `ListResponse<T>` definition and the per-entity list responses derive from it; declared OpenAPI-mirrored contract types resolve to a real generated `Schemas[...]` key (drift guard) | `contractTypes drift` | `apps/frontend/src/__tests__/contractTypes.test.ts` | P1 |
| AC25.3.2 | `lib/api.ts` is the single raw-`fetch` boundary — no other frontend source module issues a raw `fetch(` call | `contractTypes fetch boundary` | `apps/frontend/src/__tests__/contractTypes.test.ts` | P1 |

### AC25.4 — Test fixture consolidation

| ID | Requirement | Test Function | File | Priority |
|----|-------------|---------------|------|----------|
| AC25.4.1 | Shared reporting fixtures (standard chart of accounts, golden dashboard scenario, standard FX rates) are provided by a single `tests/reporting/_report_fixtures` module and reused, with duplicate per-file `test_user_id` fixtures removed; existing AC traceability is preserved | `test_report_fixtures_shared` | `apps/backend/tests/reporting/test_report_fixtures_shared.py` | P1 |

### AC25.5 — Router boundary: no router imports another router (#1097)

| ID | Requirement | Test Function | File | Priority |
|----|-------------|---------------|------|----------|
| AC25.5.1 | No backend router module imports a symbol from another router (`from src.routers.<x> import ...` is absent across `apps/backend/src/routers`); the personal-report-package assembly calls `services.performance_report.build_investment_performance_report_schedule` directly instead of the portfolio router handler, preserving behavior | `test_AC25_5_1_no_router_imports_another_router` | `apps/backend/tests/api/test_router_boundary.py` | P1 |

### AC25.6 — Package model: the `counter` worked example (a package = DDD bounded context)

> The package model (README + `PackageContract` + `types/ops/store/api` roles +
> `__all__` published language, governance computed from contracts) is specified
> in [../ssot/package-model.md](../ssot/package-model.md). The `counter` platform
> package is its first worked example; these ACs are mirrored from
> `apps/backend/src/counter/contract.py`'s `roadmap` so the AC-index gate stays
> green while governance moves into package contracts.

| ID | Requirement | Test Function | File | Priority |
|----|-------------|---------------|------|----------|
| AC25.6.1 | `CounterKey` validates the namespaced lowercase dotted `domain.action` shape and rejects invalid keys with `InvalidCounterKeyError`; the package converges by role and `contract.interface` equals `__init__.__all__` | `test_counter_key_rejects_invalid` | `apps/backend/tests/counter/test_key.py` | P0 |
| AC25.6.2 | `Count` is a non-negative tally; constructing a negative count raises `NegativeCountError`; domain `types` never import the store/api/ORM | `test_count_rejects_negative` | `apps/backend/tests/counter/test_count.py` | P0 |
| AC25.6.3 | `increment` bumps the per-(user, key) tally by one, returns the new per-user `Count`, and emits an `Incremented` domain event; ops depend only on the `CounterRepository` port, never the ORM | `test_increment_is_per_user` | `apps/backend/tests/counter/test_increment.py` | P1 |
| AC25.6.4 | `get_count` returns the per-user count for a concrete `user_id` and the global count (sum across users) when `user_id` is `None`; `check_package_contract` validates `counter` against its `PackageContract` | `test_global_vs_per_user_count` | `apps/backend/tests/counter/test_query.py` | P1 |

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
- SSOT Reporting: [../ssot/schema.md](../ssot/schema.md)
- Reporting EPIC: [EPIC-005.*](.) · Statement workflow EPIC: [EPIC-003.*](.)
- FE typed contract: `apps/frontend/src/lib/api-schema.ts`
