# Runtime Incident Response SSOT

> **SSOT Key**: `runtime_incident_response`
> **Core Definition**: App-side entry point for diagnosing Finance Report
> runtime incidents and proving service stability after deploy or recovery.

This SSOT owns the shared language for "the service is down again" triage.
It does not replace the deployment, CI/CD, environment, or infra2 documents;
it routes an incident to the right owner without copying the same playbook into
every document.

---

## Source of Truth

| Area | Owner |
|---|---|
| App deployment model and release flow | `common/runtime/deployment.md` |
| CI, preview, staging, and production gate semantics | `common/testing/ci-cd.md` (CI pipeline), `common/runtime/ci-cd.md` (deploy) |
| Boot/runtime health validation | `common/runtime/readme.md`, `apps/backend/src/boot.py`, `apps/backend/src/main.py` |
| App observability runtime contract | `common/observability/observability.md`, `apps/backend/src/observability/runtime.py` |
| Staging/production health and version smoke | `tools/health_check.sh`, `tools/production_infra_smoke.py`, `common/runtime/production_infra_smoke.py` |
| Delivery-engine evidence and optimization recommendations | `docs/project/DELIVERY_ENGINE_RECOMMENDATIONS.md` |
| Infra alerting, Lark delivery, watchdogs | [infra2 alerting SSOT](https://github.com/wangzitian0/infra2/blob/main/docs/ssot/ops.alerting.md) |
| Availability history and stability windows | [infra2 availability ledger](https://github.com/wangzitian0/infra2/blob/main/docs/ssot/ops.availability-ledger.md) |
| Infra recovery and backup restoration | [infra2 recovery SSOT](https://github.com/wangzitian0/infra2/blob/main/docs/ssot/ops.recovery.md) |

## Ownership Boundary

Finance Report owns:
- App health response semantics, including status, dependency checks, version,
  and redacted observability fields.
- Release-gate interpretation for `/api/health`, `/api/ping`, frontend
  reachability, deployed SHA/version, and production smoke output.
- App-side triage labels: `route`, `dependency`, `observability`, `secrets`,
  `stale-version`, and `flapping`.
- The proof that a recovered app version is the intended version and passes
  the expected smoke gates.

Infra2 owns:
- Vault, Traefik, Dokploy host scheduling, the observability backend platform health, Lark bridge
  delivery, watchdog implementation, availability-ledger storage, and backup
  recovery.
- Platform evidence such as restart counts, watchdog samples, route materialized
  state, and cross-service availability windows.

## Triage Entry Points

Start from the user-visible symptom, then move left to right. Do not start by
rewriting docs or rerunning broad test suites.

| Symptom | First proof | Failure domain | Owner |
|---|---|---|---|
| HTTP `000`, timeout, or DNS/TLS failure | `tools/health_check.sh` route probes and infra alert samples | `route` | Deployment + infra alerting |
| Repeated `/api/health` `404` | Health script `route_probe` output for `/api/health`, `/api/ping`, and `/` | `route` | Deployment routing |
| `502 Bad Gateway` | Backend container state, startup checkpoint logs, and `/api/ping` reachability | `crash` | App startup/deploy |
| `/api/health` returns `503` | Health payload `checks` object and Bootloader mode | `dependency` | App dependency config, then infra service |
| App is healthy but `git_sha` or `version` is old | `/api/health.git_sha`, release image tag, Dokploy effective env diff | `stale-version` | Deploy workflow/Dokploy/image routing |
| Logs or alerts missing while app serves traffic | `/health.observability` service name + OTEL exporter flags, observability backend health (infra2) | `observability` | App OTEL contract + infra2 backend/alerting |
| Startup waits for secrets or exits before CHECKPOINT-2 | Vault sidecar output, rendered secret freshness, Bootloader protected-runtime checks | `secrets` | Infra2 Vault + app boot validation |
| Alternating healthy/unhealthy samples, repeat restarts, or repeated alerts | Watchdog samples, restart counts, availability ledger | `flapping` | Infra watchdog + app incident owner |

## Failure Domain Routing

Use one domain for the first response. Split only after the first domain has a
specific proof gap.

| Domain | Definition | Primary evidence | Escalate when |
|---|---|---|---|
| `route` | Public route cannot reach the intended app endpoint | Health script route probes, Traefik/Dokploy route state | The backend is healthy internally but public routes fail |
| `dependency` | App is reachable but a required dependency is unhealthy | `/api/health.checks`, Bootloader logs, smoke output | The dependency container/service itself is unavailable |
| `observability` | App serves but logs/traces export or observability-backend/Lark delivery is broken | `/health.observability` OTEL exporter flags + resource attributes, observability backend health (infra2) | the observability backend or Lark platform health is degraded |
| `secrets` | Protected runtime lacks usable runtime secrets | Vault sidecar render, secret file freshness, Bootloader config failure | Vault token or template state must be repaired in infra2 |
| `stale-version` | Public app answers but not with the requested SHA/version | `/api/health.git_sha`, `IMAGE_TAG`, `GIT_COMMIT_SHA`, Dokploy env diff | Dokploy materialized a previous image/env after a successful trigger |
| `flapping` | Recovered service does not stay recovered | Availability ledger, watchdog samples, restart counts | The app passes one smoke check but fails the stability window |

## Stability Proof

An incident is closed only after the recovered runtime has both point-in-time
health and short-window stability.

Required app-side proof:
- `/api/health` is healthy for the target environment.
- `/api/health.git_sha` or `/api/health.version` matches the intended
  deployment target.
- Required dependency checks in `/api/health.checks` are green.
- Production release recovery runs `production_infra_smoke.py` or records why
  the production smoke result is not applicable.
- App observability fields match `common/observability/observability.md`: service
  `finance-report-backend`, alert rule `FinanceReportBackendErrorLogs`, and
  no secret collector or webhook fields in health output.

Required stability-window proof:
- No repeated stale SHA/version after the deploy-health window.
- No recent public route failure for `/api/health` or `/api/ping`.
- No unhealthy required dependency sample.
- No watchdog or availability-ledger evidence of `flapping`.

The hard production release gate is still the production release workflow and
`production_infra_smoke.py`. The infra2 availability ledger and watchdog are
the positive stability proof for repeated incidents. If that proof is not yet
automated in a release lane, capture it as manual incident-closure evidence
instead of duplicating the procedure in app docs.

## Playbooks

### Stale Version

1. Compare requested tag/SHA with `/api/health.git_sha` or `/api/health.version`.
2. Check the allowlisted Dokploy env diff for `IMAGE_TAG`, `GIT_COMMIT_SHA`,
   `IAC_CONFIG_HASH`, `ENV_SUFFIX`, and `COMPOSE_PROFILES`.
3. If Dokploy reports success but the public route remains old, classify as
   `stale-version` and inspect route/materialized deployment state before
   rerunning business E2E.

### Crash or 502

1. Confirm whether `/api/ping` and `/api/health` fail the same way.
2. Inspect backend startup checkpoints and container state.
3. If startup fails before app readiness, route to deployment/boot validation.
   If the app starts and then crashes repeatedly, add `flapping` evidence.

### Dependency 503

1. Read `/api/health.checks`; do not infer from the HTTP code alone.
2. For database failures, compare Bootloader startup logs with migration proof.
3. For S3/Redis failures, route to the owning dependency after proving the app
   config points at the intended endpoint.

### Observability Missing

1. Check `/health.observability` or `/api/health.observability` for the redacted
   app contract.
2. Confirm observability backend health/version through production smoke or the observability backend UI.
3. Use the [infra2 alerting SSOT](https://github.com/wangzitian0/infra2/blob/main/docs/ssot/ops.alerting.md) for shared alert rule, bridge, and Lark
   delivery automation. The app doc owns only service metadata and log shape.

### Secret Startup Failure

1. Confirm the failure is in protected runtime boot validation or secret render.
2. Use `common/runtime/deployment.md` for Finance Report's Vault token boundary.
3. Use the [infra2 recovery SSOT](https://github.com/wangzitian0/infra2/blob/main/docs/ssot/ops.recovery.md) for infra recovery if Vault or backup
   state is degraded.

### Flapping

1. Require more than one sample; one green smoke is not recovery proof.
2. Check availability-ledger and watchdog samples for repeated failures or
   restarts.
3. Close the incident only when the stability window is clean for the target
   runtime.

## Caller Document Rules

Other docs should link here instead of copying these playbooks:
- `common/runtime/deployment.md` owns deployment architecture, release flow, Vault
  token boundaries, and Dokploy safety rules.
- `common/observability/observability.md` owns structured logging, OTEL config, and
  redacted app observability fields.
- `common/testing/ci-cd.md` (CI pipeline) and `common/runtime/ci-cd.md`
  (deploy) own gate placement, workflow semantics, and required checks.
- `common/runtime/readme.md` (the `runtime` package) owns Bootloader gate
  definitions and smoke-test rationale (the Three Gates).
- `docs/project/DELIVERY_ENGINE_RECOMMENDATIONS.md` may record historical
  delivery evidence, but runtime incident categories and closure proof still
  link back here.
- The infra2 alerting, availability-ledger, and recovery SSOT documents own platform-side alerting, availability,
  and recovery facts.

## Proof

The documentation contract is enforced by
`tests/tooling/test_runtime_incident_response_ssot.py`.
