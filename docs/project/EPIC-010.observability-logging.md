# EPIC-010: Observability Logging (vendor-neutral OTEL)

> **Status**: ✅ Complete
> **Vision Anchor**: `decision-7-tech-stack`
> **Owner**: Platform / Backend
> **Phase**: 0
> **Duration**: 1 week
> **Dependencies**: EPIC-007 (Deployment)

---

## 🎯 Objective

Enable production-grade log observability via OpenTelemetry/OTLP, while keeping local/development runs functional without any observability backend. The app emits OTLP and is agnostic to which backend infra2 runs behind the collector.

---

## 🧭 Plan (STAR)

### Situation
- **Anchor**: Deployment readiness (EPIC-007) and platform observability SSOT.
- **Gap**: Production should ship logs to the OTLP collector, but local/dev must remain simple.

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
6. Add staging audit replay events for statement upload, async parsing, brokerage import, and reconciliation.
7. Expose a redacted runtime observability contract for health checks, startup logs, and alert triage.

### Result
- Optional OTEL export implemented; local/dev remains stdout-only.
- Infra templates updated with safe quoting.
- Production containers restarted successfully.
- Log ingestion still requires a backend image rebuild.
- The app emits OTLP only; alert routing (e.g. error-log alerts → Lark) is wired by infra2 behind the OTLP endpoint and is not declared by the app.

---

## ✅ Scope

- **Backend log shipping** via OTLP HTTP when configured.
- **Optional by default** in local/dev environments.
- **Vault-managed configuration** for staging/production.
- **App-owned vendor-neutral OTEL runtime contract** (exporter readiness on `/health` + startup log); alert rules and the observability backend are infra2's, behind the OTLP endpoint.

---

## ✅ Must Have

- Logs remain structured JSON in non-debug modes.
- OTEL export is **opt-in** and does not break app startup if the OTLP collector is unavailable.
- OTEL configuration is documented in SSOT and `.env.example`.
- Vault templates include OTEL keys for production.

---

## 🌟 Nice to Have

- Dashboard or saved view in the observability backend (infra2-owned) for backend logs.
- Additional domain-specific alerts beyond backend error logs.

---

## 📋 Task Checklist

### Backend
- [x] Add OTEL settings to `apps/backend/src/config.py`.
- [x] Configure optional OTLP log export in `apps/backend/src/observability/logger.py`.
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

> **The backend observability runtime ACs of EPIC-010 are no longer defined
> here.** The OTEL/logging/tracing/metrics/redaction/audit-log runtime ACs in
> groups AC10.1, AC10.2, AC10.4, AC10.8, AC10.10, AC10.11, AC10.12 and the
> backend rows of AC10.5/AC10.7/AC10.9 migrated into the `observability` package
> and are owned by, and sourced directly from,
> [`common/observability/contract.py`](../../common/observability/contract.py)'s
> `roadmap` under the package-scoped numeric `AC-observability.<group>.<seq>` id
> scheme (the leading "10" is dropped and the sequence preserved, so
> `AC10.<g>.<s>` becomes `AC-observability.<g>.<s>`).
> `common/testing/generate_ac_registry.py` reads package-contract roadmaps
> additively, so the AC index counts them without an EPIC-table mirror. This note
> references the new ids (keeping the registry↔EPIC link intact) but defines none
> of them — the contract is the single definition source. The **non-runtime**
> rows below stay defined here because they are cross-cutting infra governance,
> not backend observability: the SSOT/docs-linkage rows `AC10.5.1`–`AC10.5.3` and
> `AC10.7.5`, the infra2 deploy-template rows `AC10.6.1`–`AC10.6.4` and
> `AC10.7.6` (Vault `secrets.ctmpl` / `compose.yaml` / app README under the
> `repo/` infra2 submodule), and the Dokploy deploy-failure-snapshot tooling row
> `AC10.9.5`.

Migrated `AC-observability.<g>.<s>` ids (homed in the package roadmap):

> **Backend logging configuration** (was AC10.1.*):
> `AC-observability.1.1` · `AC-observability.1.2` · `AC-observability.1.3`
>
> **OTLP endpoint construction** (was AC10.2.*):
> `AC-observability.2.2`
>
> **OTEL configuration & error handling** (was AC10.4.*):
> `AC-observability.4.1` · `AC-observability.4.2` · `AC-observability.4.3` · `AC-observability.4.4`
>
> **OTEL config ownership** (was the backend-config row, now `AC-observability.5.4`):
> `AC-observability.5.4`
>
> **Must-have runtime traceability** (was the runtime rows of AC10.7.*):
> `AC-observability.7.1` · `AC-observability.7.2` · `AC-observability.7.3` · `AC-observability.7.4` · `AC-observability.7.7`
>
> **Staging audit replay logging** (was AC10.8.*):
> `AC-observability.8.1` · `AC-observability.8.2` · `AC-observability.8.3` · `AC-observability.8.4`
>
> **Production observability runtime contract** (was the app-owned rows of AC10.9.*):
> `AC-observability.9.1` · `AC-observability.9.2` · `AC-observability.9.3`
>
> **Backend OTEL metrics pillar** (was AC10.10.*):
> `AC-observability.10.1` · `AC-observability.10.2` · `AC-observability.10.3` · `AC-observability.10.4`
>
> **Logging content hardening** (was AC10.11.*):
> `AC-observability.11.1` · `AC-observability.11.2` · `AC-observability.11.3`
>
> **Async parse failure visibility** (was AC10.12.*):
> `AC-observability.12.1` · `AC-observability.12.2` · `AC-observability.12.3`

### AC10.5: Documentation (SSOT) — retained (cross-cutting docs governance)

| ID | Requirement | Test Function | File | Priority |
|----|-------------|---------------|------|----------|
| AC10.5.1 | Observability SSOT exists | `test_observability_ssot_and_env_docs_are_linked()` | `infra/test_observability_contract.py` | P0 |
| AC10.5.2 | SSOT linked in index | `test_observability_ssot_and_env_docs_are_linked()` | `infra/test_observability_contract.py` | P0 |
| AC10.5.3 | OTEL vars documented in .env.example | `test_observability_ssot_and_env_docs_are_linked()` | `infra/test_observability_contract.py` | P0 |

*(The backend-config row that was in the `AC10.5.*` group migrated to `AC-observability.5.4`.)*

### AC10.6: Infrastructure Templates — retained (infra2 deploy-template governance)

| ID | Requirement | Test Function | File | Priority |
|----|-------------|---------------|------|----------|
| AC10.6.1 | OTEL keys in app secrets template | `test_vault_template_exposes_otel_keys_with_safe_quoting()` | `infra/test_observability_contract.py` | P0 |
| AC10.6.2 | OTEL keys documented in app README | `test_app_readme_and_compose_document_observability_rollout()` | `infra/test_observability_contract.py` | P0 |
| AC10.6.3 | IAC_CONFIG_HASH in compose.yaml | `test_app_readme_and_compose_document_observability_rollout()` | `infra/test_observability_contract.py` | P0 |
| AC10.6.4 | Template helpers use printf not default | `test_vault_template_exposes_otel_keys_with_safe_quoting()` | `infra/test_observability_contract.py` | P0 |

### AC10.7: Must-Have Acceptance Criteria Traceability — retained doc/infra rows

> The backend runtime rows of the `AC10.7.*` group migrated to
> `AC-observability.7.1`, `AC-observability.7.2`, `AC-observability.7.3`,
> `AC-observability.7.4`, and `AC-observability.7.7`. The two doc/infra-governance
> rows below stay defined here.

| ID | Requirement | Test Function | File | Priority |
|----|-------------|---------------|------|----------|
| AC10.7.5 | OTEL config documented | `test_observability_ssot_and_env_docs_are_linked()` | `infra/test_observability_contract.py` | P0 |
| AC10.7.6 | Vault templates include OTEL keys | `test_vault_template_exposes_otel_keys_with_safe_quoting()` | `infra/test_observability_contract.py` | P0 |

### AC10.9: Production Observability Runtime Contract — retained deploy-tooling row

> The app exposes only its own vendor-neutral OTEL runtime readiness. Choosing the
> observability backend and wiring alert rules (e.g. error-log alerts → Lark) are
> infra2's concern, reached through the OTLP endpoint — the app declares no
> backend-specific alert routing. The app-owned runtime rows of the `AC10.9.*`
> group migrated to `AC-observability.9.1`, `AC-observability.9.2`, and
> `AC-observability.9.3`; the deploy-tooling snapshot row below stays defined here.

| ID | Requirement | Test Function | File | Priority |
|----|-------------|---------------|------|----------|
| AC10.9.5 | RETIRED (App/Infra boundary #876): deploy failure snapshots are infra2-owned end to end — the app ships no Dokploy failure-snapshot tool and never reaches the Dokploy API for platform diagnostics (the app copy was an orphan duplicating infra2's `deploy_failure_snapshot`, which runs inside the deploy_v2 front door). The boundary intent stands: the app builds no observability-backend pivot links {tier:CODE-LED} {proof:property} | `test_AC10_9_5_app_side_snapshot_is_retired()`, `test_AC10_9_5_infra2_owns_deploy_failure_snapshots()` | `tests/tooling/test_dokploy_snapshot_retired.py` | P0 |

## 📏 Acceptance Criteria

> ℹ️ **Non-contiguous AC numbering**: Gaps in `AC10.x.y` numbers reflect deprecated or merged ACs preserved through generated registry indexes plus explicit overrides. Do **not** renumber. New ACs append to the next available index in this EPIC.

### 🟢 Must Have

| Standard | Verification | Status |
|----------|--------------|--------|
| Backend starts without an observability backend | Run app with no OTEL vars | ✅ |
| Logs export over OTLP | Set OTEL vars, logs visible in the backend UI | ✅ |
| No sensitive data in logs | Review log payloads | ✅ |
| App emits OTLP only | alert routing is wired by infra2 behind the OTLP endpoint, not declared by the app | ✅ |

### 🚫 Not Acceptable

- App fails to start when the OTLP collector is down.
- Logs contain secrets or PII.
- OTEL config is undocumented or not in Vault templates.
- App health exposes collector URLs, webhook URLs, bot secrets, or observability-backend API keys.

---

## ✅ Verification Evidence

- `moon run :test`
- `python tools/check_env_keys.py`
- (infra2-owned) observability backend status check
- (infra2-owned) observability backend test-trace for `service.name=finance-report-backend`
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
