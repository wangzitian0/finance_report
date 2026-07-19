# `observability` — OTEL runtime contract, audit logging + OpenPanel CLI (infra)

> Model spec: [`../meta/readme.md`](../meta/readme.md). Machine
> contract: [`contract.py`](./contract.py). Worklist: [`todo.md`](./todo.md).

## What

## Bounded-context decision

`observability` owns cross-cutting telemetry and safe operational evidence, not
the business behavior it observes. It publishes request/metrics/logging language
and operator tooling while leaving financial policy, domain events, application
workflow, lifecycle operations, and product decisions to their owning contexts.
The machine-readable responsibility boundary is in
[`contract.py`](./contract.py).

Two cohesive surfaces under one `infra` package:

1. **Backend observability language** (BE implementation:
   `apps/backend/src/observability`) — the vendor-neutral OpenTelemetry runtime
   contract (`runtime.py`: status + startup readiness, FastAPI instrumentation
   state) and the shared structured audit/security logging helpers (`audit.py`:
   bounded safe error summaries, risky-field redaction, financial-mutation and
   security-warning emitters). This is the home #1428 relocates the shared
   logging helpers into (identity's `bind_authenticated_user_context` is folded
   in later).
2. **OpenPanel query CLI** (`openpanel_query.py`, here in `common/observability`)
   — a stdlib-only triage wrapper over the OpenPanel analytics export API, run
   via `tools/openpanel_query.py`, reading credentials from the environment.

## Shape

An `infra` package (L1), `tier=CODE-ONLY` (pure Python, no LLM). `depends_on=[]`:
the OTEL runtime reads the backend config singleton via its bare published root
(`import src.config`) — the app `Settings` module, unregistered backend
infrastructure rather than a governed cross-package edge (#1674). The formerly
flat `src.telemetry_metrics` and the PII detector (`src.services.pii_redaction`,
folded in per #1677) now live inside the package. Its published language —
`contract.interface` — equals `apps/backend/src/observability/__init__.__all__`,
validated by `tools/check_package_contract.py` (which also resolves the OpenPanel
api-key invariant to its test).
