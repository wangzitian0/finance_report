"""A lookup of classification rows by row id reads only the rows of that user (#2994, migration 0076).

The live unique key is a partial index. A query with no status, or with a bound status, cannot use it, so the
table keeps a plain index on the same columns. Without that index each lookup reads every row of every user.
"""

from __future__ import annotations

from sqlalchemy import select, text

from src.extraction import ClassificationStatus
from src.extraction.extension import transaction_classification as tc
from src.extraction.orm.layer2 import AtomicTransaction
from src.extraction.orm.layer3 import TransactionClassification
from tests.query_budget import rows_read_by, seed_other_tenants, seed_tenant_rows

OWN_TRANSACTIONS = 60
OTHER_TENANTS = 100
OTHER_TRANSACTIONS = 10


async def test_AC_extraction_2994_151_a_lookup_by_row_reads_only_the_rows_of_that_user(db, db_engine, test_user):
    await seed_tenant_rows(db, test_user.id, entries=1, transactions=OWN_TRANSACTIONS)
    await seed_other_tenants(db, count=OTHER_TENANTS, entries=1, transactions=OTHER_TRANSACTIONS)
    policy = tc.POLICY_VERSIONS[0]
    rule = await tc._ensure_policy_rule(db, test_user.id, policy)
    txn_ids = list(
        (await db.execute(select(AtomicTransaction.id).where(AtomicTransaction.user_id == test_user.id))).scalars()
    )
    db.add_all(
        TransactionClassification(atomic_txn_id=txn_id, rule_version_id=rule.id, status=ClassificationStatus.APPLIED)
        for txn_id in txn_ids
    )
    await db.commit()
    async with db_engine.connect() as connection:  # fresh statistics without polluting unrelated worker tables
        await (await connection.execution_options(isolation_level="AUTOCOMMIT")).execute(
            text("ANALYZE transaction_classification, classification_rules, atomic_transactions")
        )
    stored = await db.scalar(text("SELECT count(*) FROM transaction_classification"))
    own = await db.scalar(
        text("SELECT count(*) FROM transaction_classification WHERE atomic_txn_id = ANY(:ids)"), {"ids": txn_ids}
    )

    reads, answered = await rows_read_by(
        db_engine, lambda: tc._already_classified_ids(db, test_user.id, policy.version, txn_ids)
    )

    assert answered == set(txn_ids), "the lookup found the answer of every row of the user"
    assert stored >= 5 * own > 0, "the table must hold the rows of the other users, or the check proves nothing"
    assert 0 < reads["transaction_classification"] <= own, reads
