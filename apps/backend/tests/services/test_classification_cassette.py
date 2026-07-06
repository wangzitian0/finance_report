"""Classify proposer vs the REAL GLM response shape (EPIC-018 AC18.15.3, #1560/#1597).

No mode forks and no cassette-file reading (#1597): the test simply calls the
proposer; the llm layer serves the committed frozen GLM response per request.
Deleting the cassette turns this RED in CI (hard miss) — never a skip. Re-record
with the layer refresh knob:

    AI_PROVIDER=zai AI_BASE_URL=https://api.z.ai/api/coding/paas/v4 \
    AI_API_KEY=$GLM_CODING_TOKEN PRIMARY_MODEL=glm-5.2 \
    make llm-record ARGS='tests/services/test_classification_cassette.py'
"""

from __future__ import annotations

import pytest

from src.services.transaction_classification import POLICY_VERSIONS, propose_categories
from tests.factories import AtomicTransactionFactory

# Deterministic inputs: the cassette fingerprint keys on the exact messages, so
# these MUST stay byte-stable (synthetic; no real financial data).
_FIXED_TXNS = [
    ("Monthly salary deposit ACME PTE LTD", "IN"),
    ("NTUC FairPrice groceries", "OUT"),
]
_POLICY = POLICY_VERSIONS[0]


def _fixed_transactions():
    from src.models.layer2 import TransactionDirection

    txns = []
    for desc, direction in _FIXED_TXNS:
        txn = AtomicTransactionFactory.build(user_id=None, description=desc)
        txn.direction = TransactionDirection.IN if direction == "IN" else TransactionDirection.OUT
        txns.append(txn)
    return txns


@pytest.mark.asyncio
async def test_AC18_15_3_real_provider_response_shape_parses():
    """AC18.15.3: the proposer handles the real provider's frozen response shape —
    served transparently by the llm layer (the test cannot tell real from frozen)."""
    proposals = await propose_categories(_fixed_transactions(), _POLICY)
    assert len(proposals) == 2
    assert any(p is not None for p in proposals), "the real provider response must parse"
    catalog = {c.value for c in _POLICY.catalog}
    for p in proposals:
        if p is not None:
            assert p.category in catalog
            assert 0 <= p.confidence <= 100
