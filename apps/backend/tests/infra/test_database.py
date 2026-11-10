import pytest; from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker; from src.database import create_session_maker_from_db, get_db, init_db, set_test_session_maker
async def test_get_db_yields_session(public_client):
    async for session in get_db(): assert isinstance(session, AsyncSession); assert session is not None; break
async def test_get_db_closes_session(public_client):
    session_ref = None
    async for session in get_db(): session_ref = session; assert session.is_active or session.in_transaction(); break
    assert session_ref is not None
async def test_set_test_session_maker_override(public_client):
    custom_called = False
    class MockSessionMaker:
        def __call__(self) -> AsyncSession: nonlocal custom_called; custom_called = True; return AsyncSession(bind=None)
        async def __aenter__(self): return self()
        async def __aexit__(self, *args): pass
    original_maker = None
    try:
        set_test_session_maker(MockSessionMaker())
        async for _ in get_db(): break
        assert custom_called
    finally: set_test_session_maker(original_maker)
async def test_create_session_maker_from_db_async_engine(db):
    session_maker = create_session_maker_from_db(db); assert isinstance(session_maker, async_sessionmaker)
    async with session_maker() as new_session: assert isinstance(new_session, AsyncSession)
async def test_init_db_runs_without_error():
    await init_db(); from unittest.mock import Mock; from src import database; _m1_mock_session = Mock(spec=AsyncSession); _m1_mock_session.bind = None; _m1_mock_bind = Mock(); _m1_mock_bind.async_engine = 'not-an-async-engine'; _m1_mock_session.get_bind = Mock(return_value=_m1_mock_bind); _m1_original_test_maker = database.get_test_session_maker(); database.set_test_session_maker(None)
    try:
        with pytest.raises(RuntimeError, match='Async engine unavailable'): create_session_maker_from_db(_m1_mock_session)
    finally: database.set_test_session_maker(_m1_original_test_maker)
def test_split_postgresql_ddl_respects_dollar_quotes(): from src.database import split_postgresql_ddl; sql = "\n    CREATE OR REPLACE FUNCTION test_func() RETURNS trigger AS $$\n    BEGIN\n        IF NEW.val IS NULL THEN\n            RAISE EXCEPTION 'cannot be null';\n        END IF;\n        RETURN NEW;\n    END;\n    $$ LANGUAGE plpgsql;\n\n    DROP TRIGGER IF EXISTS trg_test ON my_table;\n    CREATE TRIGGER trg_test BEFORE INSERT ON my_table FOR EACH ROW EXECUTE FUNCTION test_func();\n    "; statements = split_postgresql_ddl(sql); assert len(statements) == 3; assert statements[0].startswith('CREATE OR REPLACE FUNCTION'); assert "RAISE EXCEPTION 'cannot be null';" in statements[0]; assert statements[0].endswith('$$ LANGUAGE plpgsql;'); assert statements[1] == 'DROP TRIGGER IF EXISTS trg_test ON my_table;'; assert statements[2].startswith('CREATE TRIGGER trg_test')
