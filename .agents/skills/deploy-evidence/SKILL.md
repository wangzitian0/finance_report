---
name: deploy-evidence
description: Finance Report Deploy Evidence & Reality Guard. Verifies Staging and Production deployments across the App-to-infra2 release boundary.
---

# Finance Report Deploy Evidence & Reality Guard

> **Core Axiom (`AGENTS.md` & `close` skill)**:
> *"Stage 1 merge closes the sub-issue once a `smoke` reality probe passes; Staging deploy is tag-driven via `infra2`; claiming any release is deployed on Staging or Production requires Touch Reality physical proof."*

## 1. When to Activate This Skill
- When verifying Staging soak or Production promotion reality after an `infra2` release tag (`vX.Y.Z`).
- When verifying `runtime-hooks.manifest.json` or live service endpoints (`report-staging.zitian.party` / `report.zitian.party`).
- Stage 1 sub-issue closure follows `smoke` + `close`; Staging batching and `[PROD GATEKEEPER]` (`deploy vX.Y.Z`) belong to `infra2` `release-train` + `close` §3.

## 2. Three-Phase Deployment Verification Protocol

### Phase 1: App-to-infra2 Release Coordinate and Runtime Hooks
Finance Report never checks out or runs infra2 source directly. Deployments cross the versioned release train and hook manifest boundary:
1. `runtime-hooks.manifest.json` (schema version 3) declares checks across `stages.yaml` cells (`preview.operation`, `preview.post`, `staging.operation`, `staging.post`, `prod.operation`, `prod.post`, `scheduled_audit`), executed via `run_cell`.
2. `common/runtime/deployment.md` documents the release tag coordinate in infra2.
3. Verify the hook manifest locally with `python -m infra2_sdk.delivery check-hooks runtime-hooks.manifest.json`.

### Phase 2: Staging Soak and Observability
Confirm the release tag triggered staging reconcile and passed soak:
1. Check staging reconcile run status in infra2 (`reconcile-iac-inputs.yml`).
2. Verify staging health endpoint:
```bash
curl -fsS "https://report-staging.zitian.party/api/health?full=1"
```
3. Walk the operator staging flows with real statements when the change touches extraction or reconciliation.
4. Check quality dashboard freshness at https://wangzitian0.github.io/finance_report/board/ (`FRESH` status and non-empty `scheduled_audit` verdicts).

### Phase 3: Touch Reality Physical Probes (Staging / Production)
Do not declare a release deployed based only on GitHub green:
1. Verify container image digest on VPS matches the release tag.
2. Verify public health endpoint:
```bash
curl -fsS "https://report.zitian.party/api/health?full=1"
```
3. Verify live database rows or statement parser results.
4. Production promotion follows `infra2` `release-train` + `close` §3 (`[PROD GATEKEEPER]`, requiring explicit `deploy vX.Y.Z`).

## 3. Red Lines (Instant Rejection)
- [REJECT] Claiming Staging or Production deployment from a `main` merge without matching release tag/promote proof: **REJECT DEPLOYMENT EVIDENCE**.
- [REJECT] GitHub Action green but public container digest unchanged: **REJECT EVIDENCE (GREEN-WHILE-STALE)**.
- [REJECT] Public health endpoint returns non-200: **REJECT EVIDENCE**.
- [REJECT] Using mock test data as Staging/Production deployment proof: **REJECT EVIDENCE**.
