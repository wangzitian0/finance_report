# Observability SSOT

> **SSOT Key**: `observability` | App-side OTLP consumption and `/health.observability` snapshot. Infrastructure contract (collector endpoint, `deployment.environment`, `service.version`, Lark alerts) lives in [infra2 observability SSOT](https://github.com/wangzitian0/infra2/blob/main/docs/ssot/ops.observability.md) and [infra2 environment SSOT](https://github.com/wangzitian0/infra2/blob/main/docs/ssot/core.environments.md#telemetry-identity).

## App-Side Configuration & Runtime Contract

`apps/backend/src/observability/` delegates stdout JSON logging and OTLP logs/traces/metrics to `infra2_sdk.service.init_service`, suppressing probe telemetry (`/livez`, `/readyz`, `/health`). `apps/backend/src/config.py` reads:
- `OTEL_EXPORTER_OTLP_ENDPOINT`: Optional OTLP HTTP collector URL (unset falls back cleanly to stdout in local dev).
- `OTEL_SERVICE_NAME`: Service identity (default `finance-report-backend`).
- `OTEL_RESOURCE_ATTRIBUTES`: Carries infra2-injected `deployment.environment` and `service.version`.

`/health.observability` exposes redacted boolean exporter flags (`otel_exporter_configured`, `logs_export_enabled`, `traces_export_enabled`, `metrics_export_enabled`), `service_name`, `deployment_environment`, and non-secret `resource_attributes` — never URLs, API keys, or webhooks.

## Log-Level Semantics

- `ERROR`: Actionable service fault (feeds zero-threshold error alerts).
- `WARNING`: Expected user/input outcomes (e.g., bad PDF extraction `statement.parse.failed`, rate limits).

Incident triage: [runtime-incident-response.md](../runtime/runtime-incident-response.md).
