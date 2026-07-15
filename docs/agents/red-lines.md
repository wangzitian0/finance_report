# Agent Red Lines

> **SSOT Key**: `security_red_lines`
> **Audience**: AI agents operating on this codebase.
> These rules are **non-negotiable**. Violating any of them blocks shipping.

---

## 🚨 Security Rules (NEVER violate)

| # | Rule | Evidence |
|---|------|---------|
| 1 | **NEVER use float for monetary amounts** — use `Decimal` | `apps/backend/tests/accounting/test_decimal_safety.py` |
| 2 | **NEVER commit sensitive files** (`.env`, `*.pem`, credentials) | `.pre-commit-config.yaml` enforces this |
| 3 | **NEVER skip entry balance validation** or post entries without accounting equation check | `test_post_unbalanced_entry_rejected` |
| 4 | **NEVER use raw `fetch()` in frontend** — use `lib/api.ts` wrapper | `apps/frontend/src/lib/api.ts` |
| 5 | **NEVER create `sa.Enum` without `name="..."`** parameter | `test_enums_have_explicit_names` |
| 6 | **NEVER put real financial data in issues / PRs / reports / commits / logs** — real amounts, balances, account/card numbers, account holder names, local file paths, or real statement filenames. Use redacted or generated/anonymized values. | Issue/PR redaction checklist (issue + PR templates); generated-fixture rule in [orchestration.md](./orchestration.md); see "Financial-data hygiene" below |

### Financial-data hygiene

Sensitive financial data includes: monetary amounts and balances; account, card, or IBAN numbers; account holder or counterparty names; local file paths; and real statement filenames.

When a bug is found from real data, reproduce it with a **GENERATED/anonymized fixture** — never paste or commit the real document, its filename, or its values.

---

## 🏛️ Accounting Integrity

These invariants must hold at **all times**:

```
Assets = Liabilities + Equity + (Income - Expenses)
```

- Every `JournalEntry` must have **balanced debits and credits**.  
  Test: `apps/backend/tests/ledger/test_accounting.py::test_balanced_entry_passes`
- Accounting equation must be satisfied at every point.  
  Test: `apps/backend/tests/ledger/test_accounting_equation.py::test_accounting_equation_violation_detected`
- Reconciliation thresholds (≥85 auto-accept; 60–84 review; <60 unmatched) must not be overridden.  
  See: [reconciliation.md](../../common/reconciliation/reconciliation.md)

---

## ⚙️ Engineering Integrity

| Rule | Detail |
|------|--------|
| **Explicit Enum naming** | All `sa.Enum` MUST have `name="..._enum"` in SQLAlchemy. |
| **Frontend env vars** | `NEXT_PUBLIC_` vars MUST be defined as `ARG`/`ENV` in `apps/frontend/Dockerfile`. |
| **Backend env vars** | All vars MUST have type + default in `apps/backend/src/config.py` and be in `.env.example`. |
| **Cross-repo sync** | Production config changes (Vault/Compose) REQUIRE a separate PR in [`infra2`](https://github.com/wangzitian0/infra2); never reintroduce an infra source checkout. |
| **Async transaction boundary** | Routers call `commit()`; Services call `flush()` only. |

---

## 🔒 Agent Deliverable Scope

- ❌ Agent **NEVER** merges a PR automatically.
- ✅ Agent **MUST** ensure CI passes before reporting completion.
- ⏸️ Merging = **User's authority**, not Agent's.

For the full agent workflow, see [orchestration.md](./orchestration.md).

---

## Concept Ownership

These concepts are **owned** by this document in the SSOT manifest:

- `security_red_lines` → `docs/agents/red-lines.md`

Cross-referenced by:
- [AGENTS.md](https://github.com/wangzitian0/finance_report/blob/main/AGENTS.md)
- [common/ledger/readme.md](https://github.com/wangzitian0/finance_report/blob/main/common/ledger/readme.md)
- [common/meta/schema.md](../../common/meta/schema.md)
- [common/reconciliation/reconciliation.md](../../common/reconciliation/reconciliation.md)
