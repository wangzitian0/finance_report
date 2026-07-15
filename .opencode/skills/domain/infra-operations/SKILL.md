---
name: infra-operations
description: Operate Finance Report's versioned App-to-infra2 deployment boundary.
---

# Infrastructure Operations

Finance Report never checks out or executes infra2 source. Fixed staging,
Production, and rollback deployments cross the versioned request boundary:

1. `tools/app_deploy_request.py` renders a canonical `DeployRequest`.
2. `tools/app_deploy_transport.py` dispatches it with `INFRA2_PAT`.
3. The transport watermarks receiver runs, requires one new run, waits for
   success, and verifies the exact request id in receiver logs.
4. App-owned health, smoke, and E2E gates verify the public result.

Use [`infra2`](https://github.com/wangzitian0/infra2) directly for Vault,
Dokploy, compose, recovery, alerting, or IaC changes. Such work requires an
independent infra2 PR; never reintroduce a source checkout or direct Dokploy
credential into Finance Report workflows.

Canonical references:

- [Operations standards](https://github.com/wangzitian0/infra2/blob/main/docs/ssot/ops.standards.md)
- [Pipeline SSOT](https://github.com/wangzitian0/infra2/blob/main/docs/ssot/ops.pipeline.md)
- [Recovery SSOT](https://github.com/wangzitian0/infra2/blob/main/docs/ssot/ops.recovery.md)
