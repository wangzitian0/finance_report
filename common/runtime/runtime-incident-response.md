# Runtime Incident Response SSOT

> **SSOT Key**: `runtime_incident_response` | App-side runtime failure triage and stability-proof routing (502/503, missing logs, stale version, secrets, flapping).

## Ownership Split

- `infra2`: Dokploy rollout, Traefik routing, Vault secret templates, host Docker hygiene, and Alerting/Lark channels ([infra2 observability SSOT](https://github.com/wangzitian0/infra2/blob/main/docs/ssot/ops.observability.md)).
- `finance_report`: Application health (`tools/smoke_test.sh`, `/api/health` -> `git_sha` / `version`), OTEL emission (`observability.md`), and deploy gates (`common/runtime/ci-cd.md`). Historical delivery metrics: [`docs/project/DELIVERY_ENGINE_RECOMMENDATIONS.md`](../../docs/project/DELIVERY_ENGINE_RECOMMENDATIONS.md).

## Triage Sequence

1. Check `/api/health` (`git_sha`, dependency states, `503` vs Traefik `404`/`502`).
2. Compare deployed `git_sha` with target `version_ref` and verify `CONFIGURATION_SHA256` stability via `infra2`.
3. Inspect logs filtered by `deployment.environment` in the observability backend without logging secrets or raw API payloads.
4. Escalate failed rollout or Vault drift by re-running the fixed `infra2` `deploy_v2` workflow after remediation.
