# Unified Code Audit & Roadmap (Jan 2026)

**Auditors**: Architecture, Product, Security, Dev, QA, Reconciler  
**Anchor**: `docs/project/EPIC-005.reporting-visualization.md`

## P0: Critical (Blockers, Data Loss, Security)

- [ ] **[Architect] Hard-coded Auth**: `MOCK_USER_ID` is used across core APIs, bypassing real auth and multi-user isolation. (`accounts.py:21`)
- [ ] **[Architect] Schema Mismatch**: Alembic creates `statements` tables, but ORM uses `bank_statements`. Migrations are broken.
- [ ] **[Developer] Data Loss**: Uploaded files are assigned a `file_path` but the temp file is deleted immediately, leaving dangling references.
- [ ] **[Lead] API Payload Limit**: PDF extraction sends the entire file as a Base64 JSON string, risking timeouts and Gateway 413 errors.
- [ ] **[Developer] Nullability Mismatch**: Database columns (`user_id`, `file_hash`) differ in nullability between Migration (`0001`) and ORM Models.

## P1: High (Core Features, SSOT Violations)

- [ ] **[PM] Missing Core UIs**: Accounts Grid, Manual Journal Entry, Statement Upload, and Approval Queue UIs are missing or placeholders.
- [ ] **[PM] Auth Status Overstated**: EPIC-001 documentation claims auth is complete, but no Auth Router exists in the backend.
- [ ] **[Dev] Cash Flow Missing**: Backend logic for Cash Flow Report is unimplemented (Phase 4), and UI is a placeholder.
- [ ] **[Architect] Storage Gap**: SSOT requires S3/MinIO, but code relies on ephemeral local paths (incompatible with containerized prod).
- [ ] **[Reconciler] Logic Error**: Draft entries are currently included in reconciliation candidates; they must be excluded.
- [ ] **[Reconciler] Immutability**: `ReconciliationMatch` records are mutated on accept/reject; SSOT mandates immutable versioning.
- [ ] **[PM/QA] CSV Balance Check**: CSV parsing hardcodes balance to `0.00`, guaranteeing failure of the mandatory Balance Validation check.
- [ ] **[Architect] Market Data**: Missing Market Data service and FX rate ingestion pipeline (breaks multi-currency reporting).
- [ ] **[Sec] PII Consent**: No mechanism for explicit user consent before sending sensitive financial contexts to 3rd-party AI (OpenRouter).
- [ ] **[Sec] Input Hygiene**: Lack of validation against Malicious PDF (ImageTragick) or CSV Injection (DDE) attacks.

## P2: Medium (UX, Logic Gaps, Optimization)

- [ ] **[UX] Upload Feedback**: No progress indicator for long-running PDF extraction (>10s); validation failures are not notified to user.
- [ ] **[UX] Onboarding**: Dashboard is empty for new users with no guidance; Mobile adaptiveness is unverified.
- [ ] **[UX] Navigation**: Landing page links to Docs/API but not the App itself. "Ignore" action is local-state only.
- [ ] **[Reconciler] Status Logic**: `PARSED` vs `APPROVED` threshold mapping is ambiguous; `PARSING` status is unused (process is sync).
- [ ] **[Dev] Missing Formats**: XLSX parsing is listed as a feature but unimplemented in `extraction.py`.
- [ ] **[Dev] FX Cache**: Implementation uses in-process Dictionary cache instead of Shared Redis (SSOT violation).
- [ ] **[Tester] Test Gaps**: Smoke tests cover only GET requests; Reconciliation complex scenarios (one-to-many) are untested.
- [ ] **[Architect] Infra Scripts**: Missing `migrate.sh`, `backup.sh`, `restore.sh` and deployment artifacts defined in init.
- [ ] **[Lead] AI Arch**: `ai_advisor` re-implements Session logic (redundant); Pattern-based Regex protection is fragile.
- [ ] **[PM] i18n**: Backend supports bi-lingual (En/Zh) responses, but Frontend lacks i18n infrastructure.

## P3: Low (Docs, Minor Polish)

- [ ] **[Tester] Doc Drift**: Verification statuses in SSOT docs are marked 'Pending' despite tests existing in the codebase.
- [ ] **[UX] Visual Polish**: Dark Mode support and Table data-density on small screens need verification.
- [ ] **[PM] Feature Refinement**: Category breakdown granularity is shallow (no multi-level support).

---

## Open Decisions

1. **Auto-Approval**: Should >=85 score auto-approve to `APPROVED` status, or pause at `PARSED`?
2. **Naming**: Align Migrations to current ORM (`bank_statements`) or revert ORM to legacy names?
3. **Storage**: Formalize S3/MinIO immediately (Phase 1) or update SSOT to allow Local Storage?
