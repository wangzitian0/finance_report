# EPIC-024: Frontend Browser Observability

> **Status**: 🚧 In Progress
> **Vision Anchor**: `decision-7-tech-stack`
> **Owner**: Frontend / Platform
> **Phase**: Hardening
> **Dependencies**: EPIC-010 (Observability Logging), EPIC-022 (Everyday-User IA)

---

## 🎯 Objective

Give the browser the same the observability backend observability the backend already has
(EPIC-010), so frontend latency, web-vitals, and uncaught errors are traceable
per environment — while keeping local / preview-without-config runs completely
inert and never letting telemetry break the app.

Browser tracing ships via OTLP/HTTP to the observability backend, mirroring the
"config-gated, non-blocking, never breaks the app" contract of the existing
OpenPanel product-analytics wrapper (`components/Analytics.tsx`). A companion
OpenPanel query CLI lets us pull frontend product-analytics events/funnels when
triaging issues.

---

## 🧭 Plan (STAR)

### Situation
- **Anchor**: Platform observability (EPIC-010 backend → the observability backend) and the
  everyday-user IA (EPIC-022) shipping real frontend traffic.
- **Gap**: The backend exports traces/logs to the observability backend; the browser does not, so
  client-side latency, web-vitals, and JS errors are invisible.

### Tasks
- **Frontend**: Add a config-gated browser OTel module + a client mount.
- **Tooling**: Add a stdlib-only OpenPanel query CLI for FE issue triage.
- **Docs**: Document the new `NEXT_PUBLIC_OTEL_*` / `OPENPANEL_API_KEY` env vars.

### Actions
1. Add `src/lib/otel.ts` (OTLP/HTTP trace exporter, web-vitals, error capture)
   gated entirely on `NEXT_PUBLIC_OTEL_EXPORTER_OTLP_ENDPOINT`.
2. Mount it once via a `"use client"` `FrontendTelemetry` component next to
   `<Analytics>` in the root layout, keeping the SDK out of the server bundle.
3. Scrub PII (query strings, fragments, emails/amounts/account numbers) from
   all captured URLs and span attributes via pure, unit-tested helpers.
4. Add `tools/openpanel_query.py` (events/funnels, `--env`).
5. Document env vars; actual per-env ingest endpoint + DNS land in infra2.

### Result
- Browser OTel is opt-in: a complete no-op until the OTLP endpoint is set, so
  local / preview stay inert.
- Telemetry failures are swallowed; render is never blocked (BatchSpanProcessor,
  no awaited export, try/catch around init).
- PII never leaves the browser.

---

## ✅ Scope

- **Browser trace export** via OTLP/HTTP when configured.
- **Opt-in by default**: no endpoint → no SDK behavior.
- **PII scrubbing** of URLs and attributes.
- **OpenPanel query CLI** for frontend product-analytics triage.
- **Automated emission proof** that, when configured, browser OTel spans are
  actually exported to `/v1/traces` and OpenPanel events are actually dispatched
  (hermetic: collector + OpenPanel stubbed).

---

## ✅ Must Have

- The OTel module is a complete no-op until the OTLP endpoint env var is set.
- Init is non-blocking and can never throw into the app's critical path.
- Captured URLs are stripped of query strings and fragments; sensitive
  attributes (emails, amounts, account numbers) are never attached.
- Uncaught errors and unhandled rejections are captured as span exceptions.
- An OpenPanel query CLI exists and reads its API key from the environment.

---

## 🌟 Nice to Have

- A the observability backend dashboard / saved view for frontend traces and web-vitals.
- Session/route correlation between OpenPanel analytics and OTel traces.

---

## 📋 Task Checklist

### Frontend
- [x] Add `apps/frontend/src/lib/otel.ts` (config-gated, non-blocking).
- [x] Mount once via `apps/frontend/src/components/FrontendTelemetry.tsx`.
- [x] Wire into `apps/frontend/src/app/layout.tsx` next to `<Analytics>`.

### Tooling
- [x] Add `tools/openpanel_query.py` (events/funnels, `--env`).

### Documentation
- [x] Document `NEXT_PUBLIC_OTEL_*` and `OPENPANEL_API_KEY` env vars (PR body).

### Emission Proof (#1169)
- [x] Hermetic integration test driving the real exporter + `track()` and
  asserting the span reaches `OTLPTraceExporter.export()` (the in-browser POST
  origin) and the OpenPanel `window.op` dispatch fires
  (`src/__tests__/telemetryEmission.test.ts`).
- [x] Real-browser Playwright smoke asserting the actual outbound `POST
  /v1/traces` (and OpenPanel dispatch) end-to-end against a stubbed collector +
  OpenPanel script (`playwright/telemetry-emission.spec.ts`).

---

## 🧪 Test Cases

> **Test Organization**: Tests organized by feature blocks using ACx.y.z numbering.
> **Coverage**: See `apps/frontend/src/__tests__/otel.test.ts`,
> `apps/frontend/src/__tests__/frontendTelemetry.test.tsx`,
> `apps/frontend/src/__tests__/telemetryEmission.test.ts`,
> `apps/frontend/playwright/telemetry-emission.spec.ts`, and
> `tests/tooling/test_openpanel_query.py`.

### AC24.1: Browser OTel + OpenPanel Query CLI

| ID | Requirement | Test Function | File | Priority |
|----|-------------|---------------|------|----------|
| AC24.1.1 | The browser OTel module is config-gated (complete no-op until `NEXT_PUBLIC_OTEL_EXPORTER_OTLP_ENDPOINT` is set), non-blocking, idempotent, and swallows SDK errors so it never throws into the app | `otel.test.ts`, `frontendTelemetry.test.tsx` | P1 |
| AC24.1.2 | The PII scrub strips query strings and fragments from captured URLs and drops sensitive attributes (emails, amounts, account numbers) before any span is emitted | `otel.test.ts` | P1 |
| AC24.1.3 | Uncaught errors (`window.onerror`) and unhandled promise rejections are captured as span exceptions with a scrubbed page URL | `otel.test.ts` | P1 |
| AC24.1.4 | The OpenPanel query CLI exists, reads its API key from `OPENPANEL_API_KEY` (never a CLI flag), and supports events/funnels with an `--env` filter | `test_openpanel_query.py` | P1 |

### AC24.2: FE Telemetry + Analytics Emission Is Proven by an Automated Test

The AC24.1 tests verify the *wiring contract* against a mocked SDK (no span
ever leaves the exporter, no event ever reaches OpenPanel). AC24.2 closes that
gap with an end-to-end emission proof: when telemetry is configured, the
browser OTel exporter actually POSTs an OTLP payload to the `/v1/traces`
endpoint, and the analytics layer actually dispatches an OpenPanel
event/page-view — both asserted hermetically (collector + OpenPanel stubbed, no
real the observability backend/OpenPanel contacted).

| ID | Requirement | Test Function | File | Priority |
|----|-------------|---------------|------|----------|
| AC24.2.1 | With the OTLP endpoint configured, the real browser OTel exporter emits a span (span actually exported, not merely wired): the vitest proof asserts the span reaches `OTLPTraceExporter.export()`, and the Playwright spec asserts the actual outbound `POST /v1/traces` over the wire; both hermetic against a stubbed collector | vitest `emits a finished browser OTel span to the real OTLP exporter's export() (AC24.2.1)` + Playwright `POST /v1/traces` spec | `playwright/telemetry-emission.spec.ts`, `src/__tests__/telemetryEmission.test.ts` | P1 |
| AC24.2.2 | With the OpenPanel client id configured, the analytics layer actually dispatches an OpenPanel event/page-view (`window.op('track'\|'screenView', …)` invoked); asserted against a stubbed `window.op`/endpoint so the test is hermetic | `dispatches an OpenPanel event via window.op when configured (AC24.2.2)` | `playwright/telemetry-emission.spec.ts`, `src/__tests__/telemetryEmission.test.ts` | P1 |

---

## 📏 Acceptance Criteria

### 🟢 Must Have

| Standard | Verification | Status |
|----------|--------------|--------|
| Browser OTel is a no-op without config | Run with no `NEXT_PUBLIC_OTEL_*` vars | ✅ |
| Telemetry never breaks the app | Init swallows errors; export is batched/async | ✅ |
| No PII leaves the browser | URL/attribute scrub unit-tested | ✅ |
| OpenPanel query CLI exists | `--help` smoke + payload tests | ✅ |

### 🚫 Not Acceptable

- The app behaves differently (or breaks) when the OTLP endpoint is unset.
- Query strings, emails, amounts, or account numbers reach the collector.
- The OpenPanel API key is accepted as a CLI argument.

---

## 🔗 References

- SSOT Observability: [../ssot/observability.md](../ssot/observability.md)
- Backend observability logging: [EPIC-010.observability-logging.md](EPIC-010.observability-logging.md)
- Product analytics wrapper: `apps/frontend/src/components/Analytics.tsx`
