"""Replay of a recorded model answer to the classification prompt that production sends (#3070, #3153).

Record again with: `LLM_API_KEY=<key> pytest --record-mode=rewrite tests/extraction/test_classification_replay.py`.
"""

from datetime import date
from decimal import Decimal
from uuid import UUID

import pytest

from src.extraction.base.source_vocabulary import TransactionDirection
from src.extraction.extension.transaction_classification import (
    POLICY_VERSIONS,
    TransactionCategory,
    _propose_batch,
    build_classification_prompt,
    policy_for,
)
from src.extraction.orm.layer2 import AtomicTransaction

ROWS = (
    ("ACME PTE LTD SALARY JAN", TransactionDirection.IN, "4200.00"),
    ("NTUC FAIRPRICE 0412 SINGAPORE", TransactionDirection.OUT, "63.40"),
    ("GRAB* A-5TZ8 RIDE", TransactionDirection.OUT, "14.80"),
    ("TRANSFER TO OWN SAVINGS 8841", TransactionDirection.OUT, "1000.00"),
    ("UNKNOWN MERCHANT 99", TransactionDirection.OUT, "7.00"),
)


def _transactions() -> list[AtomicTransaction]:
    return [
        AtomicTransaction(
            id=UUID(int=index + 1),
            user_id=UUID(int=99),
            txn_date=date(2026, 1, 2),
            amount=Decimal(amount),
            direction=direction,
            description=description,
            currency="SGD",
            dedup_hash=f"{index:064d}",
            source_documents=[],
        )
        for index, (description, direction, amount) in enumerate(ROWS)
    ]


def test_the_prompt_of_the_recording_is_the_prompt_that_production_sends() -> None:
    """The newest policy answers for every date; this is the prompt that a classify run builds for these rows."""
    prompt = build_classification_prompt(_transactions(), policy_for(date(2026, 6, 1)))
    assert policy_for(date(2026, 6, 1)) is POLICY_VERSIONS[-1]
    assert all(
        f'"index": {index}, "direction": "{direction.value}", "description": "{description}"' in prompt
        for index, (description, direction, _) in enumerate(ROWS)
    )


@pytest.mark.vcr
async def test_a_recorded_answer_parses_into_one_proposal_for_each_row(vcr_llm) -> None:
    """The real answer of the model to the indexed prompt: each row gets a known category and a 0-100 score."""
    proposals = await _propose_batch(_transactions(), POLICY_VERSIONS[-1])
    assert len(proposals) == len(ROWS) and all(proposal is not None for proposal in proposals)
    known = {category.value for category in TransactionCategory}
    assert all(proposal.category in known and 0 <= proposal.confidence <= 100 for proposal in proposals)
    # The recorded answer is fixed, so the categories of the rows are too: this pins the reader of the answer.
    assert [proposal.category for proposal in proposals] == [
        "SALARY",
        "GROCERIES",
        "TRANSPORT",
        "TRANSFER",
        "OTHER_EXPENSE",
    ]
