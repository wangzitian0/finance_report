---
name: deploy-evidence
description: Finance Report Deploy Evidence & Reality Guard. Automates Touch Reality verification and App-to-infra2 boundary checks before issue close.
---

# Finance Report Deploy Evidence & Reality Guard

> **Core Axiom (AGENTS.md Section 5)**:
> *"Closed means deployed, real, and physically verified. Code merge is not deployment. Staging deploy is tag-driven soak. Production deploy requires explicit owner authorization and Touch Reality physical proof."*

## 1. When to Activate This Skill
- Before you mark any deployment-related or service-touching issue as `Closed` or `Complete`.
- After you merge a PR that changes backend services, frontend apps, or deployment configs.
- When you verify staging soak or production promote reality.

## 2. Four-Phase Verification Protocol

### Phase 1: App-to-infra2 Deployment Request
Finance Report never checks out or runs infra2 source directly. Deployments cross the versioned request boundary:
1. `tools/app_deploy_request.py` renders a canonical `DeployRequest`.
2. `tools/app_deploy_transport.py` dispatches the request with `INFRA2_PAT`.
3. The transport waits for success and confirms the request id in logs.

### Phase 2: Staging Soak and Observability
Confirm the release tag triggered staging reconcile and passed soak:
1. Check staging deployment run status via `gh run list --workflow deploy.yml`.
2. Verify staging health endpoint:
```bash
curl -fsS https://report-staging.zitian.party/api/health
```
3. Walk the operator staging flows with real statements when the change touches extraction or reconciliation.

### Phase 3: Prod Gatekeeper Checkpoint
Report all three stage statuses before session close:
```text
[PROD GATEKEEPER CHECKPOINT]
- Stage 1 (Merge): Release tag vX.Y.Z = commit SHA <sha>
- Stage 2 (Staging Soak): Run URL <url>, Health: PASS
- Stage 3 (Prod Baseline): Image digest <digest>, Service Health: OK

Authorize production deployment of vX.Y.Z? (Reply "deploy" to authorize, or "hold" to keep unpromoted)
```

### Phase 4: Touch Reality Physical Probes
Do not declare success based only on GitHub green:
1. Verify container image digest on VPS matches the release tag.
2. Verify production public health endpoint:
```bash
curl -fsS https://report.zitian.party/api/health
```
3. Verify live database rows or statement parser results.

## 3. Red Lines (Instant Rejection)
- [REJECT] Code merged to `main` without deployed proof: **DO NOT CLOSE ISSUE**.
- [REJECT] GitHub Action green but public container digest unchanged: **REJECT EVIDENCE (GREEN-WHILE-STALE)**.
- [REJECT] Public health endpoint returns non-200: **REJECT EVIDENCE**.
- [REJECT] Using mock test data as deployment proof: **REJECT EVIDENCE**.
