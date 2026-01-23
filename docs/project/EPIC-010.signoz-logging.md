# EPIC-010: SigNoz Logging Integration

> **Status**: ✅ Complete
> **Owner**: Platform / Backend
> **Phase**: 0
> **Duration**: 1 week
> **Dependencies**: EPIC-007 (Deployment)

---

## 🎯 Objective

Enable production-grade log observability via SigNoz (OTLP), while keeping local/development runs functional without a SigNoz deployment.

---

## 🧭 Plan (STAR)

### Situation
- **Anchor**: Deployment readiness (EPIC-007) and platform observability SSOT.
- **Gap**: Production should ship logs to SigNoz, but local/dev must remain simple.

### Tasks
- **Backend**: Add optional OTLP log export gated by config.
- **Docs**: Define observability SSOT and document env vars.
- **Infra**: Wire Vault templates for OTEL variables.
 - **Ops**: Ensure deployments can refresh Vault templates safely.

### Actions
1. Add OTEL config fields and update logging setup.
2. Add SSOT + `.env.example` documentation.
3. Update Vault templates/README in infra repo.
4. Add restart-safe wiring for Vault template updates.
5. Validate via tests and env consistency check.

### Result
- Optional OTEL export implemented; local/dev remains stdout-only.
- Infra templates updated with safe quoting.
- Production containers restarted successfully.
- Log ingestion still requires a backend image rebuild.

---

## ✅ Scope

- **Backend log shipping** via OTLP HTTP when configured.
- **Optional by default** in local/dev environments.
- **Vault-managed configuration** for staging/production.

---

## ✅ Must Have

- Logs remain structured JSON in non-debug modes.
- OTEL export is **opt-in** and does not break app startup if SigNoz is unavailable.
- OTEL configuration is documented in SSOT and `.env.example`.
- Vault templates include OTEL keys for production.

---

## 🌟 Nice to Have

- Dashboard or saved view in SigNoz for backend logs.
- Basic alert on elevated error rates.

---

## 📋 Task Checklist

### Backend
- [x] Add OTEL settings to `apps/backend/src/config.py`.
- [x] Configure optional OTLP log export in `apps/backend/src/logger.py`.
- [x] Keep fallback to stdout when OTEL vars are absent.

### Documentation (SSOT)
- [x] Add `docs/ssot/observability.md` and link in SSOT index.
- [x] Document OTEL vars in `.env.example`.

### Infrastructure
- [x] Add OTEL keys to `repo/finance_report/finance_report/10.app/secrets.ctmpl`.
- [x] Document OTEL keys in `repo/finance_report/finance_report/10.app/README.md`.
- [x] Provide Vault values for staging/production.
- [x] Add `IAC_CONFIG_HASH` to `repo/finance_report/finance_report/10.app/compose.yaml` for restart-safe updates.
- [x] Replace unsupported template helpers (`default`) with `printf`.

---

## 📏 Acceptance Criteria

### 🟢 Must Have

| Standard | Verification | Status |
|----------|--------------|--------|
| Backend starts without SigNoz | Run app with no OTEL vars | ✅ |
| Logs export to SigNoz | Set OTEL vars, logs visible in UI | ✅ |
| No sensitive data in logs | Review log payloads | ✅ |

### 🚫 Not Acceptable

- App fails to start when SigNoz is down.
- Logs contain secrets or PII.
- OTEL config is undocumented or not in Vault templates.

---

## ✅ Verification Evidence

- `moon run backend:test`
- `python scripts/check_env_keys.py`
- `uv run invoke signoz.status`
- `uv run invoke signoz.shared.test-trace --service-name=finance-report-backend`
- `docker exec finance_report-backend python -c 'import opentelemetry'` (missing in prod image)

---

## 🔗 References

- SSOT Observability: `docs/ssot/observability.md`
- Platform Observability: `repo/docs/ssot/ops.observability.md`
- Deployment EPIC: `docs/project/EPIC-007.deployment.md`
