# ledger module contract (template vertical slice)

> The first **vertical domain module** in the backend — the worked example of the
> target shape every other domain (portfolio, market, ingest, reconcile, report,
> advisor) should follow. Authoritative prose:
> [`docs/ssot/base-packages.md`](../../../../docs/ssot/base-packages.md) and the
> module/role model in the project DAG discussion.

## Roles (files converge by role)

| role | what lives here | status |
|------|-----------------|--------|
| `types/` | domain **nouns** — `Entry`, `Leg` (the balance invariant) | ✅ this module |
| `ops/` | domain **verbs** — `post_entry` (edges in the project DAG) | ✅ this module |
| `store/` | persistence — `src.models.journal`, `services.accounting` | ⏳ legacy location, fold in next |
| `api/` | boundary — `src.routers`, `src.schemas.journal` | ⏳ legacy location, fold in next |

## The dependency rule (what makes the project a DAG)

```
api → ops → { types, store } → kernel (src.money / src.ratio / …)
```

- Dependencies point **down only**; never upward, never sideways-cyclic.
- The model layer must **not** import a service (the previous
  `models.journal → services.confidence_tier` cycle was removed by moving
  `derive_confidence_tier` next to the enum it maps). Enforced by
  `tests/tooling/test_ledger_module.py`.
- Cross-module calls are explicit verbs: e.g. `portfolio` / `investment` call
  `ledger.post_entry`; `ledger` knows nothing about them.

## Invariants

1. **An entry cannot exist unbalanced.** `Entry` raises `UnbalancedEntryError` at
   construction unless debits == credits **per currency** (stronger than the
   legacy currency-blind `abs(debit-credit) < 0.01` check). This makes the
   system's central invariant a type, like `Money` rejecting `float`.
2. **Legs are positive `Money`.** No zero/negative lines; direction carries sign.
3. **Policy stays in callers.** Which account is debited/credited for a
   buy/sell/dividend is the caller's account-selection policy; `ledger` only
   guarantees the result balances and persists it.

## Usage

```python
from src.ledger import Entry, post_entry

posted = await post_entry(
    db, user_id=user_id, entry_date=d, memo="Buy AAPL", source_id=src,
    entry=Entry.transfer(debit=investment_acct, credit=cash_acct, money=gross,
                         event_type="investment_buy", tags={...}),
)
```
