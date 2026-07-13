"""#1675 D4 — the extraction-owned ORM family carries no cross-domain ``relationship()``.

Per the 2026-07-11 cross-domain reference policy (#1675, codified in
``common/meta/migration-standard.md``): a bare cross-domain ``ForeignKey``
column is allowed (DB-level referential integrity), but ``relationship()``
navigation across domain boundaries is banned — the object-graph edge is the
real coupling. Consumers resolve the id column via an explicit query or the
owning package's published reads instead (behavior pinned by the existing
``account_name`` assertions in ``tests/assets/test_assets_router.py``,
``tests/assets/test_assets_router_edge_cases.py`` and
``tests/portfolio/test_portfolio_service.py``).

Intra-family navigation (extraction ↔ extraction, e.g.
``TransactionClassification.atomic_transaction``) stays allowed.
"""

import src.orm_registry  # noqa: F401  (eager mapper registration)
from src.database import Base

# The extraction-owned ORM family (#1675 ownership map): layer1-4 + the
# statement envelope + evidence graph + correction log. Statement enums carry
# no mappers; StatementSummary/UploadedDocument have no relationships at all
# but are asserted too so a future edge cannot sneak in.
EXTRACTION_FAMILY = {
    "UploadedDocument",
    "AtomicTransaction",
    "AtomicPosition",
    "AtomicTransactionSourceDocument",
    "AtomicPositionSourceDocument",
    "ClassificationRule",
    "TransactionClassification",
    "ManagedPosition",
    "ManualValuationSnapshot",
    "ReportSnapshot",
    "CorrectionLog",
    "EvidenceNode",
    "EvidenceEdge",
    "StatementSummary",
}

# Models owned by other domains: navigating to any of these from the family is
# the banned cross-domain object-graph edge (identity owns User; ledger owns
# Account/JournalEntry/JournalLine).
FOREIGN_DOMAIN_MODELS = {"User", "Account", "JournalEntry", "JournalLine"}


def test_extraction_orm_family_has_no_cross_domain_relationship():
    """No mapper in the extraction family may declare a relationship whose
    target model belongs to another domain (AC-meta.txn.3 shape, applied to
    the #1675 D4 family before/after its move into ``extraction/orm``)."""
    Base.registry.configure()
    seen: set[str] = set()
    offenders: list[str] = []
    for mapper in Base.registry.mappers:
        cls_name = mapper.class_.__name__
        if cls_name not in EXTRACTION_FAMILY:
            continue
        seen.add(cls_name)
        for rel in mapper.relationships:
            target = rel.mapper.class_.__name__
            if target in FOREIGN_DOMAIN_MODELS:
                offenders.append(f"{cls_name}.{rel.key} -> {target}")

    # Anti-vacuity: every family model must have been inspected.
    missing = EXTRACTION_FAMILY - seen
    assert not missing, f"family models not registered/inspected: {sorted(missing)}"
    assert not offenders, (
        "cross-domain relationship() navigation must be replaced by id columns "
        f"+ explicit interface reads (#1675 D4): {sorted(offenders)}"
    )
