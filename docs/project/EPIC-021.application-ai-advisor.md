# EPIC-021: Application-Layer AI Advisor

> **Status**: Deferred (post-Usable)
> **Vision Anchor**: `decision-filter-accuracy-auditability`

Defines AI Advisor as a read-only application layer consuming deterministic facts ([common/advisor/readme.md](../../common/advisor/readme.md)).

## MECE Application Architecture & Boundaries

| Lane | Direction | Owner | Relationship |
|---|---|---|---|
| Source coverage & parsing | Evidence-to-fact | EPIC-003 / EPIC-013 | Consumes `SourceCapability` and parser confidence |
| Manual evidence & assets | User evidence-to-fact | EPIC-011 / EPIC-005 | manual evidence intake stays in EPIC-011 / EPIC-005 (#706) |
| Report package snapshots & exports | Fact-to-report | EPIC-005 / EPIC-008 | report package snapshots and export scale stay in EPIC-005 / EPIC-008 (#705) |
| Portfolio & market facts | Fact maintenance | EPIC-017 / EPIC-011 | Consumes holdings, valuations, freshness |
| AI pipeline capability | Processing capability | EPIC-018 / EPIC-006 | Consumes provider/OCR/chat foundation |
| Advisor Brief & next actions | Application guidance | EPIC-021 | Read-only application guidance only |

Package specifications live in [common/advisor/readme.md](../../common/advisor/readme.md).
