"""Reconciliation test fixtures.

Stage 3 removed the legacy `bank_statement*` tables. Reconciliation fixtures are
now built natively on Layer 2 (`atomic_transactions`) plus the `StatementSummary`
conform, so the old Layer 0 -> Layer 2 projection bridge is no longer required.
`execute_matching` reads Layer 2 directly.
"""
