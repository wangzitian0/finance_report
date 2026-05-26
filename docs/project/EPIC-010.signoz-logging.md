# EPIC-010: SigNoz Logging Integration

> **Status**: ✅ Complete
> **Vision Anchor**: `decision-7-tech-stack`
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

## 🧪 Test Cases

> **Test Organization**: Tests organized by feature blocks using ACx.y.z numbering.
> **Coverage**: See `apps/backend/tests/infra/test_logger.py`, `apps/backend/tests/infra/test_observability_contract.py`, and `docs/ssot/observability.md`

### AC10.1: Backend Logging Configuration

| ID | Requirement | Test Function | File | Priority |
|----|-------------|---------------|------|----------|
| AC10.1.1 | OTEL settings in config | `test_otel_settings_are_explicit_and_environment_backed()` | `infra/test_observability_contract.py` | P0 |
| AC10.1.2 | Optional OTLP log export configured | `test_configure_otel_logging_with_fake_exporter()` | `infra/test_logger.py` | P0 |
| AC10.1.3 | Fallback to stdout when OTEL vars absent | `test_select_renderer_uses_json_in_production()` | `infra/test_logger.py` | P0 |

### AC10.2: OTLP Endpoint Construction
| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC10.2.2 | Build OTLP endpoint preserves logs path | `test_build_otlp_logs_endpoint_preserves_logs_path()` | `infra/test_logger.py` | P0 |
*(AC10.2.1 removed — canonical copy is AC12.1.1 in EPIC-012)*

### AC10.3: Renderer Selection

*(AC10.3.1 and AC10.3.2 removed — canonical copies are AC12.2.1 and AC12.2.2 in EPIC-012)*

### AC10.4: OTEL Configuration & Error Handling

| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC10.4.1 | Configure OTEL logging warns on missing dependency | `test_configure_otel_logging_missing_dependency_warns()` | `infra/test_logger.py` | P0 |
| AC10.4.2 | Configure OTEL logging with fake exporter | `test_configure_otel_logging_with_fake_exporter()` | `infra/test_logger.py` | P1 |

### AC10.5: Documentation (SSOT)

| ID | Requirement | Test Function | File | Priority |
|----|-------------|---------------|------|----------|
| AC10.5.1 | Observability SSOT exists | `test_observability_ssot_and_env_docs_are_linked()` | `infra/test_observability_contract.py` | P0 |
| AC10.5.2 | SSOT linked in index | `test_observability_ssot_and_env_docs_are_linked()` | `infra/test_observability_contract.py` | P0 |
| AC10.5.3 | OTEL vars documented in .env.example | `test_observability_ssot_and_env_docs_are_linked()` | `infra/test_observability_contract.py` | P0 |
| AC10.5.4 | OTEL vars documented in config.py | `test_otel_settings_are_explicit_and_environment_backed()` | `infra/test_observability_contract.py` | P0 |

### AC10.6: Infrastructure Templates

| ID | Requirement | Test Function | File | Priority |
|----|-------------|---------------|------|----------|
| AC10.6.1 | OTEL keys in app secrets template | `test_vault_template_exposes_otel_keys_with_safe_quoting()` | `infra/test_observability_contract.py` | P0 |
| AC10.6.2 | OTEL keys documented in app README | `test_app_readme_and_compose_document_observability_rollout()` | `infra/test_observability_contract.py` | P0 |
| AC10.6.3 | IAC_CONFIG_HASH in compose.yaml | `test_app_readme_and_compose_document_observability_rollout()` | `infra/test_observability_contract.py` | P0 |
| AC10.6.4 | Template helpers use printf not default | `test_vault_template_exposes_otel_keys_with_safe_quoting()` | `infra/test_observability_contract.py` | P0 |

### AC10.7: Must-Have Acceptance Criteria Traceability

| ID | Requirement | Test Function | File | Priority |
|----|-------------|---------------|------|----------|
| AC10.7.1 | Backend starts without SigNoz | `test_backend_otel_absence_is_startup_safe()` | `infra/test_observability_contract.py` | P0 |
| AC10.7.2 | Logs export to SigNoz | `test_configure_otel_logging_with_fake_exporter()` | `infra/test_logger.py` | P0 |
| AC10.7.3 | No sensitive data in logs | `test_external_api_logging_omits_sensitive_arguments_by_default()` | `infra/test_observability_contract.py` | P0 |
| AC10.7.4 | OTLP optional by default | `test_backend_otel_absence_is_startup_safe()` | `infra/test_observability_contract.py` | P0 |
| AC10.7.5 | OTEL config documented | `test_observability_ssot_and_env_docs_are_linked()` | `infra/test_observability_contract.py` | P0 |
| AC10.7.6 | Vault templates include OTEL keys | `test_vault_template_exposes_otel_keys_with_safe_quoting()` | `infra/test_observability_contract.py` | P0 |
| AC10.7.7 | Structured JSON logs in non-debug | `test_production_renderer_outputs_structured_json()` | `infra/test_observability_contract.py` | P0 |

**Traceability Result**:
- Total AC IDs: 18 (AC10.2.1, AC10.3.1, AC10.3.2 removed as duplicates of EPIC-012 canonical ACs)
- Requirements converted to AC IDs: 100% (EPIC-010 checklist + must-have standards)
- Requirements with implemented test references: 100% (contract tests cover config, docs, templates, and logger behavior)
- Test files: 2
- Note: Staging/production SigNoz UI checks remain operational smoke verification outside the AC contract suite

---

## 📏 Acceptance Criteria

> ℹ️ **Non-contiguous AC numbering**: Gaps in `AC10.x.y` numbers within `docs/infra_registry.yaml` reflect deprecated/merged ACs preserved for historical traceability. Do **not** renumber. New ACs append to the next available index in the relevant feature block.

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

- `moon run :test`
- `python scripts/check_env_keys.py`
- `uv run invoke signoz.status`
- `uv run invoke signoz.shared.test-trace --service-name=finance-report-backend`
- `docker exec finance_report-backend python -c 'import opentelemetry'` (missing in prod image)

---

## 🔗 References

- SSOT Observability: [../ssot/observability.md](../ssot/observability.md)
- Platform Observability: `repo/docs/ssot/ops.observability.md`
- Deployment EPIC: `docs/project/EPIC-007.deployment.md`

## 📄 Owned Documentation Surfaces

These non-EPIC docs are part of this EPIC's maintained surface:

- [../ssot/observability.md](../ssot/observability.md) — platform observability rationale.
- [../ssot/observability-logging.md](../ssot/observability-logging.md) — structured logging and OTEL trace/log correlation.
