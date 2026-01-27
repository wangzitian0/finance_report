# EPIC-010: SigNoz Logging Integration — GENERATED

> **Auto-generated implementation summary** — Do not edit manually.
> **Last updated**: 2026-01-27
> **Source EPIC**: [EPIC-010.signoz-logging.md](./EPIC-010.signoz-logging.md)

---

## 📋 Implementation Summary

EPIC-010 enables production-grade log observability via SigNoz using OTLP (OpenTelemetry Protocol). The implementation is **opt-in** and does not affect local/development environments.

### Completed Deliverables

| Deliverable | Location | Status |
|-------------|----------|--------|
| OTEL config settings | `apps/backend/src/config.py` | ✅ Complete |
| OTLP log export | `apps/backend/src/logger.py` | ✅ Complete |
| SSOT documentation | `docs/ssot/observability.md` | ✅ Complete |
| Environment docs | `.env.example` | ✅ Complete |
| Vault templates | `repo/finance_report/finance_report/10.app/secrets.ctmpl` | ✅ Complete |
| Infrastructure README | `repo/finance_report/finance_report/10.app/README.md` | ✅ Complete |
| Config hash for restarts | `repo/finance_report/finance_report/10.app/compose.yaml` | ✅ Complete |

---

## 🏗️ Architecture

### Log Flow

```
┌──────────────────┐     ┌──────────────────┐     ┌──────────────────┐
│  FastAPI App     │ --> │  OTLP Exporter   │ --> │    SigNoz        │
│  (Structured     │     │  (HTTP/gRPC)     │     │  (Aggregation)   │
│   JSON Logs)     │     │                  │     │                  │
└──────────────────┘     └──────────────────┘     └──────────────────┘
       │                                                   │
       │ (fallback if no OTEL)                            │
       ▼                                                   ▼
┌──────────────────┐                           ┌──────────────────┐
│   stdout/stderr  │                           │  SigNoz UI       │
│   (Local Dev)    │                           │  (Query Logs)    │
└──────────────────┘                           └──────────────────┘
```

### Key Design Decisions

1. **Opt-in Export**: OTEL export only activates when `OTEL_EXPORTER_OTLP_ENDPOINT` is set
2. **Graceful Degradation**: App starts normally if SigNoz is unavailable
3. **Structured Logs**: JSON format in non-debug modes
4. **No PII in Logs**: Sensitive data is never logged

---

## 📁 Implementation Details

### Configuration (`config.py`)

```python
class Settings(BaseSettings):
    # OpenTelemetry Configuration
    OTEL_EXPORTER_OTLP_ENDPOINT: str | None = None
    OTEL_EXPORTER_OTLP_HEADERS: str | None = None
    OTEL_SERVICE_NAME: str = "finance-report-backend"
    
    @property
    def otel_enabled(self) -> bool:
        """Check if OTEL export is configured."""
        return self.OTEL_EXPORTER_OTLP_ENDPOINT is not None
```

### Logger Setup (`logger.py`)

```python
def configure_logging():
    """Configure logging with optional OTLP export."""
    
    # Standard structured logging
    logging.basicConfig(
        level=logging.INFO,
        format='{"timestamp": "%(asctime)s", "level": "%(levelname)s", ...}'
    )
    
    # Add OTLP handler if configured
    if settings.otel_enabled:
        from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
        from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
        
        exporter = OTLPLogExporter(
            endpoint=f"{settings.OTEL_EXPORTER_OTLP_ENDPOINT}/v1/logs"
        )
        logger_provider.add_log_record_processor(
            BatchLogRecordProcessor(exporter)
        )
```

---

## 🔐 Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `OTEL_EXPORTER_OTLP_ENDPOINT` | No | None | SigNoz OTLP endpoint URL |
| `OTEL_EXPORTER_OTLP_HEADERS` | No | None | Auth headers (if needed) |
| `OTEL_SERVICE_NAME` | No | `finance-report-backend` | Service name in SigNoz |

### Example `.env` Configuration

```bash
# Local development (no OTEL)
# Leave these unset

# Staging/Production
OTEL_EXPORTER_OTLP_ENDPOINT=https://signoz.zitian.party
OTEL_EXPORTER_OTLP_HEADERS=Authorization=Bearer <token>
OTEL_SERVICE_NAME=finance-report-backend
```

---

## 🔧 Vault Template

### `secrets.ctmpl`

```hcl
{{- with secret "secret/data/finance_report/production/app" -}}
# Core Application
DATABASE_URL={{ .Data.data.DATABASE_URL }}
REDIS_URL={{ .Data.data.REDIS_URL }}

# OpenTelemetry (optional)
{{ if .Data.data.OTEL_EXPORTER_OTLP_ENDPOINT }}
OTEL_EXPORTER_OTLP_ENDPOINT={{ .Data.data.OTEL_EXPORTER_OTLP_ENDPOINT }}
{{ end }}
{{ if .Data.data.OTEL_EXPORTER_OTLP_HEADERS }}
OTEL_EXPORTER_OTLP_HEADERS={{ .Data.data.OTEL_EXPORTER_OTLP_HEADERS }}
{{ end }}
{{- end -}}
```

---

## 📊 SigNoz Query Examples

### Query Logs by Service

```
service_name = "finance-report-backend"
```

### Query Error Logs

```
service_name = "finance-report-backend" AND severity_text = "ERROR"
```

### Query by Trace ID

```
trace_id = "<trace-id>"
```

---

## 📏 Acceptance Criteria Status

### 🟢 Must Have

| Criterion | Status | Verification |
|-----------|--------|--------------|
| Backend starts without SigNoz | ✅ | Run app with no OTEL vars |
| Logs export to SigNoz | ✅ | Set OTEL vars, logs visible in UI |
| No sensitive data in logs | ✅ | Review log payloads |
| OTEL config documented | ✅ | `docs/ssot/observability.md` |
| Vault templates updated | ✅ | OTEL keys in `secrets.ctmpl` |

### 🌟 Nice to Have

| Criterion | Status | Notes |
|-----------|--------|-------|
| SigNoz dashboard | ⏳ | Saved view for backend logs |
| Error rate alerts | ⏳ | Basic alert on elevated errors |

---

## 🔗 References

### SSOT

- [observability.md](../ssot/observability.md) — OTEL configuration SSOT

### Related EPICs

- [EPIC-007.deployment.md](./EPIC-007.deployment.md) — Production deployment (prerequisite)

### External

- [SigNoz Documentation](https://signoz.io/docs/)
- [OpenTelemetry Python](https://opentelemetry-python.readthedocs.io/)

---

## ✅ Verification Commands

```bash
# Run backend tests
moon run backend:test

# Check environment consistency
python scripts/check_env_keys.py

# Check SigNoz status (from infra repo)
uv run invoke signoz.status

# Test trace export (from infra repo)
uv run invoke signoz.shared.test-trace --service-name=finance-report-backend

# Verify OTEL package in image
docker exec finance_report-backend python -c 'import opentelemetry'

# View logs in SigNoz UI
open https://signoz.zitian.party
# Query: service_name = "finance-report-backend"
```

---

## 📝 Known Issues

1. **Image Rebuild Required**: Log ingestion requires a backend image rebuild with `opentelemetry` package
2. **Template Helpers**: Replaced unsupported `default` helper with `printf` in Vault templates

---

*This file is auto-generated from EPIC-010 implementation. For goals and acceptance criteria, see [EPIC-010.signoz-logging.md](./EPIC-010.signoz-logging.md).*
