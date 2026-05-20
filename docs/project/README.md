# Project EPIC Index

This directory contains the detailed EPIC documents that sit below the root
project entry point.

The project hierarchy is:

```text
README.md -> docs/project/EPIC-*.md -> docs/*_registry.yaml -> tests
```

Use the root [README](../../README.md) for current project status, EPIC proof
summary, coverage baseline, and active blockers. This file is only the detailed
EPIC directory index.

## Source Rules

- EPIC scope lives in `docs/project/EPIC-*.md`.
- AC definitions are discovered from EPIC documents and generated into
  `docs/ac_registry.yaml` and `docs/infra_registry.yaml`.
- Test proof is reported by `docs/analysis/test-ac-coverage-report.md`.
- Coverage policy is owned by `scripts/coverage_policy.py`.
- Project status metrics should be generated or validated, not hand-maintained.
  See [issue #455](https://github.com/wangzitian0/finance_report/issues/455).

## EPIC Documents

| EPIC | Scope |
|---|---|
| [EPIC-001](./EPIC-001.phase0-setup.md) | Infrastructure & authentication |
| [EPIC-002](./EPIC-002.double-entry-core.md) | Double-entry bookkeeping core |
| [EPIC-003](./EPIC-003.statement-parsing.md) | Statement parsing |
| [EPIC-004](./EPIC-004.reconciliation-engine.md) | Reconciliation engine |
| [EPIC-005](./EPIC-005.reporting-visualization.md) | Reports & visualization |
| [EPIC-006](./EPIC-006.ai-advisor.md) | AI advisor |
| [EPIC-007](./EPIC-007.deployment.md) | Deployment |
| [EPIC-008](./EPIC-008.testing-strategy.md) | Testing strategy & E2E gates |
| [EPIC-009](./EPIC-009.pdf-fixture-generation.md) | PDF fixture generation |
| [EPIC-010](./EPIC-010.signoz-logging.md) | SigNoz logging |
| [EPIC-011](./EPIC-011.asset-lifecycle.md) | Asset lifecycle |
| [EPIC-012](./EPIC-012.foundation-libs.md) | Foundation libraries |
| [EPIC-013](./EPIC-013.statement-parsing-v2.md) | Statement parsing v2 |
| [EPIC-014](./EPIC-014.ttd-transformation.md) | TDD/TTD transformation |
| [EPIC-015](./EPIC-015.processing-account.md) | Processing account |
| [EPIC-016](./EPIC-016.two-stage-review-ui.md) | Two-stage review UI |
| [EPIC-017](./EPIC-017.portfolio-management.md) | Portfolio management |
| [EPIC-018](./EPIC-018.ai-driven-pipeline.md) | AI-driven pipeline |

## Current Audit Reports

| Report | Purpose |
|---|---|
| [AUDITS.md](./AUDITS.md) | Audit index |
| [AC-AUDIT-2026-05-04.md](./AC-AUDIT-2026-05-04.md) | Historical vision -> EPIC -> AC consistency audit |
| [../analysis/test-ac-coverage-report.md](../analysis/test-ac-coverage-report.md) | Current generated AC-to-test coverage report |

## Known Documentation Debt

- Harden AC traceability semantics:
  [#452](https://github.com/wangzitian0/finance_report/issues/452)
- Move code-owned SSOT facts into common/generated contracts:
  [#453](https://github.com/wangzitian0/finance_report/issues/453)
- Convert manual-verification ACs into automated tests or explicit manual gates:
  [#454](https://github.com/wangzitian0/finance_report/issues/454)
- Generate README EPIC status from registries and test reports:
  [#455](https://github.com/wangzitian0/finance_report/issues/455)
- Fix AC-to-EPIC mismatch and invalid test references:
  [#456](https://github.com/wangzitian0/finance_report/issues/456)

## Related

- [Project vision](../../vision.md)
- [SSOT index](../ssot/README.md)
- [Agent orchestration](../agents/orchestration.md)
