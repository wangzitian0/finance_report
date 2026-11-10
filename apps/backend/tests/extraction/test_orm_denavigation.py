import src.orm_registry; from src.database import Base; EXTRACTION_FAMILY = {'UploadedDocument', 'AtomicTransaction', 'AtomicPosition', 'AtomicTransactionSourceDocument', 'AtomicPositionSourceDocument', 'ClassificationRule', 'TransactionClassification', 'ManagedPosition', 'ManualValuationSnapshot', 'CorrectionLog', 'EvidenceNode', 'EvidenceEdge', 'StatementSummary'}; FOREIGN_DOMAIN_MODELS = {'User', 'Account', 'JournalEntry', 'JournalLine'}
def test_extraction_orm_family_has_no_cross_domain_relationship():
    'AC-meta.txn.3'; Base.registry.configure(); seen: set[str] = set(); offenders: list[str] = []
    for mapper in Base.registry.mappers:
        cls_name = mapper.class_.__name__
        if cls_name not in EXTRACTION_FAMILY: continue
        seen.add(cls_name)
        for rel in mapper.relationships: target = rel.mapper.class_.__name__; offenders.append(f'{cls_name}.{rel.key} -> {target}') if target in FOREIGN_DOMAIN_MODELS else None
    missing = EXTRACTION_FAMILY - seen; assert not missing, f'family models not registered/inspected: {sorted(missing)}'; assert not offenders, f'cross-domain relationship() navigation must be replaced by id columns + explicit interface reads (#1675 D4): {sorted(offenders)}'
