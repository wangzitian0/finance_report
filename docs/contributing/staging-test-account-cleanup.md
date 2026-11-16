# Staging Test-Account Cleanup

QA and E2E runs create disposable accounts on dev and staging databases. `common.runtime.dev.purge_test_accounts` reclaims aged test tenants safely.

The deletion logic, email predicates, and safety guards live in `apps/backend/src/identity/extension/account_purge.py` (`src.identity`, #1677, #3050) and are tested via `AC-identity.purge.*` in `common/identity/contract.py`.

## Modes

1. **Standard safe purge (default):**
   - Matches `DEFAULT_TEST_EMAIL_PATTERN` (`qa.*`, `e2e-*`, `load-test-*` on `example.com` / `test.example.com`).
   - Deletes owned rows per user savepoint (`workflow_sync_states` and child FK tables included) while respecting immutable ledger and append-only triggers.
   - Blocked accounts remain intact and are reported with `!`.

2. **Staging tenant rotation (`--staging-rotate`):**
   - Matches `STAGING_DISPOSABLE_EMAIL_PATTERN` (including `agent-random-*`, `*_journey_*`, `recon_disposition-*`, `journal_*`, `case*-*`, `probe*`, `pdf_oracle_*`, `holdout_*`, `oracle_*`, and `qa-(sweep|combo|bughunt)-*@test.zitian.party`).
   - Protects accounts newer than `--older-than-days` (default `14`) and emails in `PERSISTENT_TEST_EMAILS` / `--keep-email` / `TEST_USER_EMAIL`.
   - Uses transaction-scoped `SET LOCAL session_replication_role = 'replica'` on Postgres dev/staging databases to delete leaf-to-root including append-only `journal_entries`, `reviewed_statement_envelopes`, `trace_record_parents`, and `trace_records` (`scope_kind = 'TENANT'`), then verifies zero orphan trace rows before commit.

## Usage

Run from the repository root:

```bash
# 1. Standard dry run (changes nothing)
python -m common.runtime.dev.purge_test_accounts

# 2. Standard apply (preserves trigger-protected accounts)
python -m common.runtime.dev.purge_test_accounts --apply

# 3. Staging rotation dry run (preview aged disposable tenants >= 14 days old)
ENVIRONMENT=staging python -m common.runtime.dev.purge_test_accounts --staging-rotate --older-than-days 14

# 4. Staging rotation apply
ENVIRONMENT=staging python -m common.runtime.dev.purge_test_accounts --staging-rotate --older-than-days 14 --apply
```

## Safety

- **Dry run is the default.** Pass `--apply` to delete rows.
- **Environment guard.** `--apply` and `--staging-rotate` refuse any environment other than `development`, `dev`, `local`, `test`, `testing`, `ci`, or `staging` (`--staging-rotate` has no `--force` override).
- **Production triggers untouched.** Production database triggers and migrations never change.
