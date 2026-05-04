import pytest

from src.services.correction_service import (
    clear_all_correction_cache,
    get_few_shot_examples,
    record_correction,
)
from tests.factories import BankStatementFactory, BankStatementTransactionFactory


@pytest.fixture(autouse=True)
def _clear():
    clear_all_correction_cache()
    yield
    clear_all_correction_cache()


async def test_get_few_shot_examples_cache_hit_and_limit(db, test_user):
    """AC4.7.2: get_few_shot_examples respects default limit and caches results."""
    stmt = await BankStatementFactory.create_async(db, user_id=test_user.id)

    for i in range(12):
        txn = await BankStatementTransactionFactory.create_async(
            db,
            statement_id=stmt.id,
            description=f"Txn {i}",
            suggested_category=f"Cat{i % 3}",
        )
        await record_correction(
            db,
            user_id=test_user.id,
            transaction_id=txn.id,
            corrected_category=f"Corrected{i % 5}",
        )
    await db.commit()

    examples = await get_few_shot_examples(db, user_id=test_user.id)
    assert len(examples) == 10

    examples2 = await get_few_shot_examples(db, user_id=test_user.id)
    assert examples2 == examples
