# Staging Test-Account Cleanup

QA and E2E runs create disposable accounts on dev and staging databases. `apps/backend/scripts/purge_test_accounts.py` reclaims aged test tenants safely.

The deletion logic, email predicates, and safety guards live in `apps/backend/src/identity/extension/account_purge.py` (`src.identity`, #1677, #3050) and are covered by backend identity tests.

## Usage

1. **Standard safe purge (default):**
   - Uses `DEFAULT_TEST_EMAIL_PATTERN` (`qa.*`, `e2e-*`, `load-test-*`, `*_journey_*`, `recon_disposition-*`, `journal_*`, `case*-*`, `probe*`, `qa-(sweep|combo|bughunt)-*@test.zitian.party`, etc.) while protecting `PERSISTENT_TEST_EMAILS` / `--keep-email` / `TEST_USER_EMAIL`.
   - Deletes owned rows per user savepoint (`workflow_sync_states` and child FK tables included) while leaving immutable ledger/append-only accounts intact as `blocked`.

2. **Append-only tenant rotation (`--rotate-append-only`):**
   - Combine with `--older-than-days 14` on `dev`/`staging` databases (`is_safe_purge_environment`, no `--force` bypass).
   - Uses transaction-scoped `SET LOCAL session_replication_role = 'replica'` on Postgres to delete leaf-to-root including `journal_entries`, `reviewed_statement_envelopes`, `trace_record_parents`, and `trace_records` (`scope_kind = 'TENANT'`), then verifies zero orphan trace rows before commit.

```bash
# 1. Dry run (changes nothing) — works both locally and inside backend container (/app)
python scripts/purge_test_accounts.py

# 2. Safe apply (preserves trigger-protected accounts)
python scripts/purge_test_accounts.py --apply

# 3. Staging rotation dry run (preview aged disposable tenants >= 14 days old)
ENVIRONMENT=staging python scripts/purge_test_accounts.py --rotate-append-only --older-than-days 14

# 4. Staging rotation apply
ENVIRONMENT=staging python scripts/purge_test_accounts.py --rotate-append-only --older-than-days 14 --apply
```

## Safety

- **Dry run is the default.** Pass `--apply` to delete rows.
- **Environment guard.** `--apply` and `--rotate-append-only` refuse any environment other than `development`, `dev`, `local`, `test`, `testing`, `ci`, or `staging` (`--rotate-append-only` has no `--force` override).
- **Production triggers untouched.** Production database triggers and migrations never change.
