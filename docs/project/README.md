# Project EPIC Index

This directory contains the detailed EPIC documents that sit below the root
project entry point.

The project hierarchy is:

```text
README.md -> docs/project/EPIC-*.md -> docs/*_registry.yaml -> tests
```

Use the root [README](../../README.md) for stable project entry points and links
to generated proof reports. GitHub issue state, generated coverage numbers, and
other live values should not be duplicated by hand in this directory index.

## Source Rules

- EPIC scope lives in `docs/project/EPIC-*.md`.
- AC definitions are discovered from EPIC documents and generated into
  `docs/ac_registry.yaml` and `docs/infra_registry.yaml`.
- Test proof is reported by `docs/analysis/test-ac-coverage-report.md`.
- Current AC traceability follows this live chain:
  `README.md` -> `docs/project/EPIC-*.md` -> `docs/*_registry.yaml` ->
  tests -> CI artifact. Do not commit generated audit snapshots in routine
  feature PRs; removed archive inventory is retained in
  [issue #548](https://github.com/wangzitian0/finance_report/issues/548).
- Coverage policy is owned by `common/coverage/policy.py`.
- Project status metrics should be generated or validated, not hand-maintained.
  See [issue #455](https://github.com/wangzitian0/finance_report/issues/455).

## Do Not Hand-Maintain

Long-lived project documents should not duplicate mutable facts. Link to the
owning source instead of copying:

- GitHub issue or PR open/closed/merged state.
- CI, deployment, or Coveralls pass/fail status.
- AC totals, coverage percentages, test counts, or stub counts.
- Dependency, runtime, model, or image versions already owned by lockfiles,
  config, Dockerfiles, or CI.
- Test function inventories unless the matrix is parseable and mechanically
  validated.

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
| [DELIVERY_ENGINE_RECOMMENDATIONS.md](./DELIVERY_ENGINE_RECOMMENDATIONS.md) | Remaining CI/post-merge delivery-engine optimization recommendations |
| [../analysis/test-ac-coverage-report.md](../analysis/test-ac-coverage-report.md) | Current generated AC-to-test coverage report |
| [../analysis/traceability-exceptions.md](../analysis/traceability-exceptions.md) | Classified helper/SSOT tests and source surfaces that are not AC proof |

## Active Non-EPIC Documentation Ownership

These documents are important enough to stay outside archive, but they are not
project truth owners. Their EPIC owners must reference them and keep them in
sync with ACs and tests.

| Documentation surface | Owner EPIC | Role |
|---|---|---|
| [../../README.md](../../README.md) | Root project entry point | Status/proof summary generated or validated from registries and reports |
| [../../vision.md](../../vision.md) and [../target.md](../target.md) | Vision layer | Decision filter, not implementation status |
| [../index.md](../index.md) | EPIC-001 | Documentation site navigation |
| [../user-guide/getting-started.md](../user-guide/getting-started.md) | EPIC-001 | First-use guide and onboarding route |
| [../../apps/backend/README.md](../../apps/backend/README.md) | EPIC-001 | Backend module entry point |
| [../../apps/frontend/README.md](../../apps/frontend/README.md) | EPIC-001 | Frontend module entry point |
| [../../apps/backend/tests/README.md](../../apps/backend/tests/README.md) | EPIC-008 / EPIC-014 | Test-suite navigation and domain mapping |
| [../agents/orchestration.md](../agents/orchestration.md), [../agents/red-lines.md](../agents/red-lines.md), and [../contributing/branch-policy.md](../contributing/branch-policy.md) | EPIC-014 | Agent and contributor workflow governance |
| [../../.github/copilot-instructions.md](../../.github/copilot-instructions.md), [../../.github/instructions/frontend.instructions.md](../../.github/instructions/frontend.instructions.md), [../../.github/instructions/python.instructions.md](../../.github/instructions/python.instructions.md), and [../../.github/pull_request_template.md](../../.github/pull_request_template.md) | EPIC-014 | GitHub contributor and assistant workflow surfaces |
| [../ssot/README.md](../ssot/README.md) and [../ssot/*.md](../ssot/README.md) | SSOT manifest + related EPICs | Rationale, code-owner links, and proof references |
| [../user-guide/accounts.md](../user-guide/accounts.md) and [../reference/api-accounts.md](../reference/api-accounts.md) | EPIC-002 | Account user/API surface |
| [../user-guide/journal-entries.md](../user-guide/journal-entries.md) and [../reference/api-journal.md](../reference/api-journal.md) | EPIC-002 | Journal user/API surface |
| [../user-guide/reconciliation.md](../user-guide/reconciliation.md) | EPIC-003 / EPIC-004 | Upload, parsing, matching, and review user flow |
| [../reference/api-reconciliation.md](../reference/api-reconciliation.md) | EPIC-004 | Reconciliation API surface |
| [../user-guide/reports.md](../user-guide/reports.md) | EPIC-005 | Reporting user surface |
| [../user-guide/ai-advisor.md](../user-guide/ai-advisor.md) and [../reference/api-chat.md](../reference/api-chat.md) | EPIC-006 | AI advisor user/API surface |
| [../reference/api-overview.md](../reference/api-overview.md) | EPIC-001 | API conventions and auth entry point |
| [../../tools/_lib/pdf_fixtures/README.md](../../tools/_lib/pdf_fixtures/README.md) and [../../tools/_lib/pdf_fixtures/FONT_HANDLING.md](../../tools/_lib/pdf_fixtures/FONT_HANDLING.md) | EPIC-009 | PDF fixture tool documentation |
| [AUDITS.md](./AUDITS.md) and [AC-AUDIT-2026-05-04.md](./AC-AUDIT-2026-05-04.md) | EPIC-014 | Current and historical audit surfaces |
| [DECISIONS.md](./DECISIONS.md) and [DECISIONS_ZH.md](./DECISIONS_ZH.md) | EPIC-014 | Project decision logs |

## Known Documentation Debt

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
