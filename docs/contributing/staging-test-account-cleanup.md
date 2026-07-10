# Staging Test-Account Cleanup

QA and E2E runs leave behind disposable accounts (`qa.*@example.com`,
`e2e-*@test.example.com`, `load-test-*@example.com`) on shared/staging
databases. `tools/purge_test_accounts.py` reclaims them safely.

This is the operator runbook. The deletion logic, safety model, and email
predicate live in `apps/backend/src/identity/extension/account_purge.py`
(published via `src.identity`, #1677) and are unit tested
(`AC-identity.purge.*` in `common/identity/contract.py`'s roadmap).

## What it does

- Selects accounts whose email matches a **narrow** predicate (qa/e2e/load-test
  prefixes on `example.com` / `test.example.com`). Plain `user@example.com`
  fixtures are **not** matched.
- Deletes each matched account and every row it owns, **one account per
  transaction (savepoint)** — all-or-nothing, never half-deleted.
- An account that still holds **immutable posted/reconciled ledger entries** is
  reported as `blocked` and left fully intact (the same contract the API enforces
  with a `409`, see [#988](https://github.com/wangzitian0/finance_report/issues/988)).
  Void those entries first if the account genuinely must go.

## Usage

Run from the repository root.

```bash
# 1. Dry run (default): report what WOULD be purged / blocked. Changes nothing.
python tools/purge_test_accounts.py

# 2. Apply on a dev/staging database:
python tools/purge_test_accounts.py --apply

# 3. One-off custom predicate (e.g. a specific load-test batch):
python tools/purge_test_accounts.py --pattern '^load-test-2026-.*@example\.com$' --apply
```

The target database and mode are echoed (with credentials redacted) before
anything runs:

```
[purge-test-accounts] target=postgresql+asyncpg://***@staging-db:5432/finance_report environment='staging' mode=dry-run
```

### Output

```
Matched 4 test account(s); Would purge 3, blocked 1.
  ~ qa.alice@example.com
  ~ e2e-bob@test.example.com
  ~ load-test-carol@example.com
  ! qa.has-ledger@example.com — blocked: cannot delete immutable journal entry ... with status posted
```

(`~` = would purge in a dry run, `-` = purged with `--apply`, `!` = blocked.)

## Safety

- **Dry run is the default.** You must pass `--apply` to delete anything.
- **Environment guard.** `--apply` is refused unless `ENVIRONMENT` (or its alias
  `ENV`) is one of `development` / `dev` / `local` / `test` / `testing` / `ci` /
  `staging`. The guard reads the raw variable, so an **unset/empty** value is
  treated as unsafe (not as the `development` default); running against any other
  environment requires an explicit `--force`. **Never** point this at production.
- **No force-delete of real ledger data.** The immutable-ledger guard is never
  bypassed; blocked accounts are surfaced, not destroyed.

## Scheduling (optional)

This tool is intentionally **operator-run**, not wired to a destructive cron.
If a recurring sweep is wanted, schedule the **dry-run** form for visibility and
keep `--apply` a manual, reviewed action.
