'AC18.15.3 EPIC-018'; from __future__ import annotations; import pytest; from src.extraction.extension.transaction_classification import POLICY_VERSIONS, propose_categories; from tests.factories import AtomicTransactionFactory; _FIXED_TXNS = [('Monthly salary deposit ACME PTE LTD', 'IN'), ('NTUC FairPrice groceries', 'OUT')]; _POLICY = POLICY_VERSIONS[0]
def _fixed_transactions():
    from src.extraction import TransactionDirection; txns = []
    for (desc, direction) in _FIXED_TXNS: txn = AtomicTransactionFactory.build(user_id=None, description=desc); txn.direction = TransactionDirection.IN if direction == 'IN' else TransactionDirection.OUT; txns.append(txn)
    return txns
async def test_AC18_15_3_real_provider_response_shape_parses():
    'AC18.15.3'; proposals = await propose_categories(_fixed_transactions(), _POLICY); assert len(proposals) == 2; assert any((p is not None for p in proposals)), 'the real provider response must parse'; catalog = {c.value for c in _POLICY.catalog}
    for p in proposals:
        if p is not None: assert p.category in catalog; assert 0 <= p.confidence <= 100
