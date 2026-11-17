# Project EPIC Index

Package contract roadmaps (`common/<pkg>/contract.py`) own migrated `AC-<pkg>.*` criteria. `docs/project/EPIC-*.md` holds only horizontal/FE residue marked with `<!-- epic-owned: fe-only|fe-half|horizontal|pending-package -->` or `<!-- epic-file: design-doc|goal-stub -->` (`tests/tooling/test_epic_residue_ratchet.py`, `tests/tooling/test_terminal_centers_allowlist.py`). Live status lives in GitHub issues and CI outputs.

## Current Milestone: Usable

Tracked by [milestone "Usable: a year of real data on prod"](https://github.com/wangzitian0/finance_report/milestone/1) (G1 prod safety, G2 year ingest, G3 trustworthy numbers, G4 everyday IA).

## EPIC Documents

| EPIC | Scope |
|---|---|
| [EPIC-001](./EPIC-001.phase0-setup.md) | Infrastructure & authentication |
| [EPIC-002](./EPIC-002.double-entry-core.md) | Double-entry bookkeeping |
| [EPIC-003](./EPIC-003.statement-parsing.md) | Statement parsing |
| [EPIC-004](./EPIC-004.reconciliation-engine.md) | Reconciliation engine |
| [EPIC-005](./EPIC-005.reporting-visualization.md) | Reports & visualization |
| [EPIC-006](./EPIC-006.ai-advisor.md) | AI advisor |
| [EPIC-007](./EPIC-007.deployment.md) | Deployment |
| [EPIC-008](./EPIC-008.testing-strategy.md) | Testing strategy & E2E gates |
| [EPIC-010](./EPIC-010.observability-logging.md) | Observability logging |
| [EPIC-011](./EPIC-011.asset-lifecycle.md) | Asset lifecycle |
| [EPIC-012](./EPIC-012.foundation-libs.md) | Foundation libraries |
| [EPIC-013](./EPIC-013.statement-parsing-v2.md) | Statement parsing v2 |
| [EPIC-014](./EPIC-014.ttd-transformation.md) | TTD transformation |
| [EPIC-015](./EPIC-015.processing-account.md) | Processing account |
| [EPIC-016](./EPIC-016.two-stage-review-ui.md) | Two-stage review UI |
| [EPIC-017](./EPIC-017.portfolio-management.md) | Portfolio management |
| [EPIC-018](./EPIC-018.ai-driven-pipeline.md) | AI-driven pipeline |
| [EPIC-019](./EPIC-019.event-driven-upload-to-report-ux.md) | Upload-to-report UX |
| [EPIC-020](./EPIC-020.framework-aware-personal-reporting.md) | Framework reporting |
| [EPIC-021](./EPIC-021.application-ai-advisor.md) | Application-layer AI advisor (`EPIC-021.application-ai-advisor.md`) |
| [EPIC-022](./EPIC-022.everyday-user-ia.md) | Everyday-user IA |
| [EPIC-023](./EPIC-023.llm-provider-abstraction.md) | LLM provider abstraction |
| [EPIC-024](./EPIC-024.frontend-observability.md) | Frontend observability |
| [EPIC-025](./EPIC-025.dry-ssot-simplification.md) | DRY/SSOT simplification |
| [EPIC-026](./EPIC-026.ac-authority-tiers.md) | AC authority tiers |

## Reports & Governance

- [AUDITS.md](./AUDITS.md) · [DELIVERY_ENGINE_RECOMMENDATIONS.md](./DELIVERY_ENGINE_RECOMMENDATIONS.md) · [traceability-exceptions.md](./traceability-exceptions.md)
- [Project vision](../target.md) · [common/meta/data/MANIFEST.yaml](../../common/meta/data/MANIFEST.yaml) · [orchestration.md](../agents/orchestration.md)
