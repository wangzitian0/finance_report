# Coverage Policy SSOT
> **SSOT Key**: `coverage` > **Version**: 3.0.0 > **Version scope**: Coverage policy semantics only. The former unified > coverage system (diff-coverage PR gate, no-regression baseline, Coveralls > upload) was retired in #2934 Wave A; its history is recoverable from git. This document defines the **coverage policy** for the Finance Report project.
## Surviving Coverage Floors
- **Backend**: `apps/backend/pyproject.toml` enforces `--cov-fail-under=96` (branch coverage, `source=src`, no broad omit) on local full runs. CI backend shards run with `--cov-fail-under=0` because each shard sees only partial coverage; the former merged no-regression gate retired with the `unified-coverage` job (#2934 Wave A). A future merge-side coverage gate is #2934 Wave B/D scope.
- **Frontend**: `apps/frontend/vitest.config.ts` enforces thresholds `lines/functions/statements 98`, `branches 84`.
## Source-Root Registration
`common/meta/extension/coverage/policy.py` defines the governed components (backend, frontend, common, tools) and their deny-list exempt patterns. `tools/check_ci_metrics_contract.py` discovers source roots and fails CI when a new `apps/*/src`, `packages/*/src`, or root shared source root is not represented in the policy. Coverage scope is deny-list based within each governed source root.
## Local Verification
```bash cd apps/backend && uv run pytest            # enforces the 96% branch floor via addopts cd apps/frontend && npx vitest run --coverage  # enforces the Vitest thresholds ```
## Invariants
- Coverage claims in docs must be backed by generated artifacts. - Coverage thresholds must be synchronized between CI config and this file. - Badge values must not be used as acceptance evidence. - Exempting a source tree from the policy requires an explicit, justified entry in `COVERAGE_EXEMPT_PATTERNS` — never a silent omission.
> **Owner**: Development Team > **Review cycle owner**: Track review cadence outside this prose file; this > document owns policy semantics, not live review status.
