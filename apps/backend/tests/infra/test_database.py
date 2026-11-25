from __future__ import annotations

from unittest.mock import Mock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src import database
from src.database import create_session_maker_from_db, get_db, init_db, set_test_session_maker, split_postgresql_ddl


async def test_get_db_create_session_maker_and_init_db(public_client, db):
    async for s in get_db():
        assert isinstance(s, AsyncSession) and (s.is_active or s.in_transaction())
        break

    called = False

    class _Maker:
        def __call__(self):
            nonlocal called
            called = True
            return AsyncSession(bind=None)

        async def __aenter__(self):
            return self()

        async def __aexit__(self, *_a):
            pass

    orig = database.get_test_session_maker()
    try:
        set_test_session_maker(_Maker())
        async for _ in get_db():
            break
        assert called

        set_test_session_maker(orig)
        maker = create_session_maker_from_db(db)
        assert isinstance(maker, async_sessionmaker)
        async with maker() as ns:
            assert isinstance(ns, AsyncSession)
        await init_db()

        mock_s = Mock(spec=AsyncSession, bind=None, get_bind=Mock(return_value=Mock(async_engine="bad")))
        database.set_test_session_maker(None)
        with pytest.raises(RuntimeError, match="Async engine unavailable"):
            create_session_maker_from_db(mock_s)
    finally:
        database.set_test_session_maker(orig)


def test_split_postgresql_ddl_respects_dollar_quotes():
    sql = "CREATE OR REPLACE FUNCTION f() RETURNS trigger AS $$\nBEGIN\n IF NEW.val IS NULL THEN RAISE EXCEPTION 'cannot be null'; END IF;\n RETURN NEW;\nEND;\n$$ LANGUAGE plpgsql;\nDROP TRIGGER IF EXISTS trg_test ON my_table;\nCREATE TRIGGER trg_test BEFORE INSERT ON my_table FOR EACH ROW EXECUTE FUNCTION f();"
    stmts = split_postgresql_ddl(sql)
    assert (
        len(stmts) == 3
        and stmts[0].startswith("CREATE OR REPLACE FUNCTION")
        and "RAISE EXCEPTION 'cannot be null';" in stmts[0]
        and stmts[0].endswith("$$ LANGUAGE plpgsql;")
    )
    assert stmts[1] == "DROP TRIGGER IF EXISTS trg_test ON my_table;" and stmts[2].startswith("CREATE TRIGGER trg_test")
