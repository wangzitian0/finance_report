# Finance Report - Audit & Roadmap (Jan 2026)

> **Current System Status** — Comprehensive audit identifying critical issues, priorities, and next steps.

**Last Updated**: 2026-01-13  
**Anchor Document**: [`docs/project/EPIC-005.reporting-visualization.md`](project/EPIC-005.reporting-visualization.md)

## 🧭 Navigation

- **[Project Overview](project/README.md)** — EPIC tracking and roadmap
- **[Technical Docs](ssot/README.md)** — Single Source of Truth (SSOT)
- **[Development Guide](ssot/development.md)** — Setup and development workflow

---

## 🔴 Top 10 High-Priority Blockers

| # | Category | Issue | Impact | Status |
|---|----------|-------|--------|--------|
| 1 | **Security** | No JWT auth - uses `X-User-Id` header | Anyone can impersonate any user | ⚠️ MVP intentional |
| 2 | **Security** | No HTTPS enforcement in local dev | Credentials sent in plaintext locally | ⚠️ Acceptable for dev |
| 3 | **Data** | `MOCK_USER_ID` in `users.py` | Legacy code path bypasses real auth | 🔧 Needs cleanup |
| 4 | **Schema** | No Alembic migrations directory | Cannot track DB schema changes | ✅ Resolved |
| 5 | **API** | PDF extraction sends full Base64 in JSON | Gateway 413 on large files (>5MB) | ⚠️ Mitigated by 10MB limit |
| 6 | **Frontend** | `README.md` Quick Start uses wrong compose file | `docker-compose.ci.yml` doesn't exist | ✅ Fixed in PR #46 |
| 7 | **Feature** | Cash Flow report unimplemented | Backend returns placeholder data | ❌ P1 |
| 8 | **Feature** | XLSX parsing listed but unimplemented | Feature advertised but broken | ❌ P1 |
| 9 | **Security** | No PII consent for AI context | Sends financial data to OpenRouter | ⚠️ Legal risk |
| 10 | **Testing** | Smoke tests cover only GET requests | POST/PUT/DELETE untested in E2E | ⚠️ Coverage gap |

---

## ✅ Recently Resolved (Jan 2026)

| Issue | Resolution |
|-------|------------|
| Hard-coded `MOCK_USER_ID` in core APIs | Replaced with `get_current_user_id()` from header |
| Schema Mismatch (statements vs bank_statements) | ORM now uses `bank_statements` consistently |
| Data Loss (temp file deleted after upload) | Files now stored in S3/MinIO |
| Missing Auth Router | Added `/auth/register`, `/auth/login`, `/auth/me` |
| Docker Compose CI file missing | Unified to `docker-compose.yml` |
| Frontend API URL hardcoded to localhost | Changed to relative path with Next.js rewrites |
| CORS blocking PR deployments | Added `cors_origin_regex` for dynamic subdomains |
| Backend `/api` prefix mismatch | Removed prefix, Traefik strips `/api` |
| Nullability Mismatch (e.g. `user_id`) | Verified `nullable=False` in migration and ORM |

---

## P1: High Priority (Core Features)

- [ ] **Implement JWT-based authentication** — Replace `X-User-Id` header with proper tokens
- [ ] **Complete Cash Flow report** — Backend logic is placeholder
- [ ] **Add Alembic migrations** — Currently no schema version control
- [ ] **Implement XLSX parsing** — Advertised but unimplemented
- [ ] **Add PII consent flow** — Before sending data to AI

## P2: Medium Priority (Polish)

- [x] **Fix README Quick Start** — References wrong compose file
- [ ] **Add upload progress indicator** — PDF extraction can take >10s
- [ ] **Clean up MOCK_USER_ID** — Dead code in users.py
- [ ] **Add E2E tests for mutations** — Only GET requests tested
- [ ] **Mobile responsiveness audit** — Unverified

---

## Open Decisions

1. **Auto-Approval**: Should ≥85 score auto-approve directly, or require confirmation?
2. **JWT Strategy**: Use FastAPI-Users or custom implementation?
3. **i18n**: Frontend lacks internationalization - needed for multi-language support
