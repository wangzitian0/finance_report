import asyncio; import logging; import os; import re; import sys; from pathlib import Path; from typing import Any; from unittest.mock import patch; from uuid import uuid4; from weakref import WeakSet; import pytest; import pytest_asyncio; import structlog; from httpx import ASGITransport, AsyncClient; from sqlalchemy import event, text; from sqlalchemy.engine.url import make_url; from sqlalchemy.exc import SQLAlchemyError; from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine; from sqlalchemy.orm import Session; from sqlalchemy.pool import NullPool; import src.orm_registry; from src.config import settings; from src.observability import get_logger; _REPO_ROOT = str(Path(__file__).resolve().parents[3]); sys.path.insert(0, _REPO_ROOT) if _REPO_ROOT not in sys.path else None; logger = get_logger(__name__)
_LIVE_APP_SESSIONS: WeakSet[Session] = WeakSet()
_LOCAL_TEST_HOSTS = frozenset({"", "test", "testserver", "localhost", "127.0.0.1"})


def _current_task_id() -> int | None:
    try:
        task = asyncio.current_task()
    except RuntimeError:
        return None
    return id(task) if task is not None else None


@event.listens_for(Session, "after_begin")
def _track_app_transaction(session: Session, _tx: Any, _conn: Any) -> None:
    if not session.info.get("test_arrange_session"):
        session.info["owner_task_id"] = _current_task_id()
        _LIVE_APP_SESSIONS.add(session)


def active_guarded_app_transactions(*, task_scoped: bool = True) -> int:
    current_task_id = _current_task_id()
    count = 0
    for session in list(_LIVE_APP_SESSIONS):
        if session.info.get("test_arrange_session") or not session.in_transaction():
            continue
        if task_scoped and current_task_id is not None and session.info.get("owner_task_id") != current_task_id:
            continue
        count += 1
    return count


def _assert_no_open_app_txn(operation: str) -> None:
    if active_guarded_app_transactions(task_scoped=True) > 0:
        raise RuntimeError(
            f"External I/O attempted while an application AsyncSession transaction is open ({operation})"
        )


@pytest.fixture(autouse=True)
def _guard_external_io_during_open_transaction():
    from functools import wraps
    from src.llm.extension import client as llm_client
    from src.runtime.extension.storage import StorageService

    import src.llm.extension.agent as llm_agent

    orig_agent = llm_agent._agent
    orig_stream_dispatch = llm_client._cassette_stream_dispatch
    orig_completion = llm_client.cassette_completion
    orig_run_s3 = StorageService._run_s3
    orig_httpx_send = AsyncClient.send

    @wraps(orig_stream_dispatch)
    async def guarded_stream_dispatch(*args, **kwargs):
        _assert_no_open_app_txn("LLM stream")
        async for chunk in orig_stream_dispatch(*args, **kwargs):
            yield chunk

    @wraps(orig_completion)
    async def guarded_completion(*args, **kwargs):
        _assert_no_open_app_txn("LLM completion")
        return await orig_completion(*args, **kwargs)

    @wraps(orig_agent)
    def guarded_agent(*args, **kwargs):
        # The SDK sends its HTTP through httpx2, which the patch of `AsyncClient.send` below does not cover, and a
        # fake model sends nothing. The entry point is the one place that each call passes, in the task of the caller.
        _assert_no_open_app_txn("LLM call")
        return orig_agent(*args, **kwargs)

    @wraps(orig_run_s3)
    def guarded_run_s3(self, *args, **kwargs):
        _assert_no_open_app_txn("S3 storage")
        return orig_run_s3(self, *args, **kwargs)

    @wraps(orig_httpx_send)
    async def guarded_httpx_send(self, request, *args, **kwargs):
        if (request.url.host or "") not in _LOCAL_TEST_HOSTS:
            _assert_no_open_app_txn(f"HTTP {request.method} {request.url.host}")
        return await orig_httpx_send(self, request, *args, **kwargs)

    with (
        patch.object(llm_client, "_cassette_stream_dispatch", guarded_stream_dispatch),
        patch.object(llm_client, "cassette_completion", guarded_completion),
        patch.object(llm_agent, "_agent", guarded_agent),
        patch.object(StorageService, "_run_s3", guarded_run_s3),
        patch.object(AsyncClient, "send", guarded_httpx_send),
    ):
        yield
def pytest_addoption(parser): parser.addoption('--llm-record', action='store_true', default=False, help='Re-record LLM cassettes (layer refresh knob; real provider call + write cassette).')
def pytest_configure(config):
    os.environ.setdefault('LLM_CASSETTE_ENGAGE', '1')
    if config.getoption('--llm-record'): os.environ['LLM_CASSETTE_REFRESH'] = '1'
def pytest_sessionfinish(session, exitstatus):
    from src.llm.extension.cassette import session_served_keys; served = session_served_keys()
    if not served: return
    out = Path(__file__).resolve().parents[1] / 'test-results'; out.mkdir(exist_ok=True); (out / f'served-cassettes-{os.getpid()}.txt').write_text(''.join((f'{k}\n' for k in sorted(served))), encoding='utf-8')
@pytest.fixture(autouse=True)
def mock_bootloader_checks():
    from src.boot import ServiceStatus
    async def ok_database(): return ServiceStatus('database', 'ok', 'Mocked for tests', 0.0)
    async def ok_s3(): return ServiceStatus('s3', 'ok', 'Mocked for tests', 0.0)
    with patch('src.boot.Bootloader._check_database', new=ok_database), patch('src.boot.Bootloader._check_s3', new=ok_s3): yield
@pytest.fixture(autouse=True)
def reset_rate_limiters(): from src.identity import auth_rate_limiter, register_rate_limiter; from src.main import api_rate_limiter; [limiter.clear() for limiter in (api_rate_limiter, auth_rate_limiter, register_rate_limiter)]; yield; [limiter.clear() for limiter in (api_rate_limiter, auth_rate_limiter, register_rate_limiter)]
@pytest.fixture(autouse=True)
def disable_external_market_data_fetch(monkeypatch): monkeypatch.setattr(settings, 'market_data_lazy_fetch_enabled', False, raising=False)
@pytest.fixture
def review_path(monkeypatch): monkeypatch.setattr(settings, 'auto_accept_ai_suggestions', False, raising=False)
@pytest.fixture(autouse=True)
def wire_advisor_app_reads(): from src.advisor import register_fx_pairs_read; from src.composition import observed_fx_pairs; register_fx_pairs_read(observed_fx_pairs)
def normalize_url(url: str | None) -> str | None:
    if url and 'localhost' in url: return url.replace('localhost', '127.0.0.1')
    return url
@pytest.fixture(scope='session')
def worker_id(request):
    if hasattr(request.config, 'workerinput'): return request.config.workerinput['workerid']
    return 'master'
def get_test_db_url(worker_id: str) -> str:
    from tests._support.test_isolation import get_namespace, get_test_db_name, sanitize_namespace; raw_namespace = os.environ.get('TEST_NAMESPACE'); namespace = sanitize_namespace(raw_namespace) if raw_namespace else get_namespace(); base_db_name = get_test_db_name(namespace); base_url = normalize_url(os.environ.get('DATABASE_URL', f'postgresql+asyncpg://postgres:postgres@127.0.0.1:5432/{base_db_name}')) or f'postgresql+asyncpg://postgres:postgres@127.0.0.1:5432/{base_db_name}'
    if raw_namespace: base_url = make_url(base_url).set(database=base_db_name).render_as_string(hide_password=False)
    if worker_id != 'master': url_obj = make_url(base_url); assert url_obj.database is not None; worker_suffix = f'_{worker_id}'; max_base_len = 63 - len(worker_suffix); worker_db_name = f'{url_obj.database[:max_base_len]}{worker_suffix}'; new_url = url_obj.set(database=worker_db_name); return new_url.render_as_string(hide_password=False)
    return base_url
@pytest.fixture(scope='session')
def test_database_url(worker_id): return get_test_db_url(worker_id)
TEST_DATABASE_URL = get_test_db_url('master'); os.environ['S3_ENDPOINT'] = normalize_url(os.environ.get('S3_ENDPOINT', 'http://127.0.0.1:9000')) or 'http://127.0.0.1:9000'; os.environ['ENVIRONMENT'] = 'testing'
@pytest.fixture(autouse=True, scope='session')
def configure_structlog_for_tests(): processors = [structlog.contextvars.merge_contextvars, structlog.processors.add_log_level, structlog.processors.format_exc_info, structlog.processors.TimeStamper(fmt='iso'), structlog.stdlib.ProcessorFormatter.wrap_for_formatter]; structlog.configure(processors=processors, logger_factory=structlog.stdlib.LoggerFactory(), cache_logger_on_first_use=False); formatter = structlog.stdlib.ProcessorFormatter(processor=structlog.dev.ConsoleRenderer(), foreign_pre_chain=processors[:-1]); root_logger = logging.getLogger(); [root_logger.removeHandler(handler) for handler in root_logger.handlers[:]]; handler = logging.StreamHandler(sys.stdout); handler.setFormatter(formatter); root_logger.addHandler(handler); root_logger.setLevel(logging.DEBUG); yield; structlog.reset_defaults()
async def ensure_database(db_url: str):
    url = make_url(db_url); db_name = url.database; default_url = url.set(database='postgres'); engine = create_async_engine(default_url, isolation_level='AUTOCOMMIT')
    try:
        async with engine.connect() as conn:
            result = await conn.execute(text(f"SELECT 1 FROM pg_database WHERE datname = '{db_name}'"))
            if not result.scalar(): print(f'Creating test database: {db_name}'); await conn.execute(text(f'CREATE DATABASE {db_name}'))
            else: print(f'Test database {db_name} already exists'); await conn.execute(text(f"SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '{db_name}' AND pid <> pg_backend_pid()"))
    except (SQLAlchemyError, Exception) as e:
        logger.error(f'Test database setup failed: {type(e).__name__}: {e}', extra={'database': db_name, 'error_type': type(e).__name__}) if isinstance(e, SQLAlchemyError) else None; print(f'Warning: Failed to ensure database exists: {e}')
        if isinstance(e, SQLAlchemyError): raise RuntimeError(f'Cannot proceed without test database: {e}') from e
    finally: await engine.dispose()
DISABLE_AUTOVACUUM_STATEMENTS = ("\nCREATE FUNCTION public.test_disable_autovacuum() RETURNS event_trigger\nLANGUAGE plpgsql AS $$\nDECLARE\n    created record;\nBEGIN\n    FOR created IN\n        SELECT d.objid\n        FROM pg_event_trigger_ddl_commands() AS d JOIN pg_class AS c ON c.oid = d.objid\n        WHERE d.object_type = 'table' AND d.schema_name = 'public' AND c.relkind = 'r'\n    LOOP\n        EXECUTE format('ALTER TABLE %s SET (autovacuum_enabled = false)', created.objid::regclass);\n    END LOOP;\nEND\n$$\n", "\nCREATE EVENT TRIGGER test_disable_autovacuum ON ddl_command_end\nWHEN TAG IN ('CREATE TABLE', 'CREATE TABLE AS', 'SELECT INTO')\nEXECUTE FUNCTION public.test_disable_autovacuum()\n", 'ALTER EVENT TRIGGER test_disable_autovacuum ENABLE ALWAYS')
async def _drop_test_database(db_url: str, db_name: str) -> None:
    admin_url = make_url(db_url).set(database='postgres')
    admin_engine = create_async_engine(admin_url, isolation_level='AUTOCOMMIT', poolclass=NullPool)
    try:
        async with admin_engine.connect() as conn:
            await conn.execute(text(f'DROP DATABASE IF EXISTS "{db_name}" WITH (FORCE)'))
    except (SQLAlchemyError, Exception) as exc:
        print(f'Warning: Failed to drop test database {db_name}: {exc}')
    finally:
        await admin_engine.dispose()
@pytest_asyncio.fixture(scope='session')
async def _schema_engine(test_database_url):
    import atexit
    from tests._support.test_isolation import get_namespace, is_droppable_test_db, register_namespace, sanitize_namespace, unregister_namespace
    raw_namespace = os.environ.get('TEST_NAMESPACE'); namespace = sanitize_namespace(raw_namespace) if raw_namespace else get_namespace()
    register_namespace(namespace); atexit.register(unregister_namespace, namespace)
    await ensure_database(test_database_url); import src.counter.extension.sql; import src.identity.extension.sql; import src.orm_registry; import src.platform.extension.sql; from src.database import Base, create_app_engine; engine = create_app_engine(test_database_url, echo=False, poolclass=NullPool)
    @event.listens_for(engine.sync_engine, 'before_cursor_execute')
    def _track_dirty_tables(conn, cursor, statement, parameters, context, executemany):
        stripped = statement.strip()
        if stripped[:10].upper().startswith(_WRITE_STMT_PREFIXES): match = _TABLE_EXTRACT_RE.search(stripped); _DIRTY_TABLES.add(match.group(1).lower()) if match else _DIRTY_TABLES.add('__ALL__')
    async with engine.begin() as conn:
        await conn.execute(text('DROP SCHEMA public CASCADE')); await conn.execute(text('CREATE SCHEMA public')); await conn.execute(text('GRANT ALL ON SCHEMA public TO postgres')); await conn.execute(text('GRANT ALL ON SCHEMA public TO public'))
        for statement in DISABLE_AUTOVACUUM_STATEMENTS: await conn.exec_driver_sql(statement)
        await conn.run_sync(Base.metadata.create_all)
    _DIRTY_TABLES.clear()
    try:
        yield engine
    finally:
        await engine.dispose()
        if os.environ.get('KEEP_TEST_DB') != '1':
            db_name = make_url(test_database_url).database
            if is_droppable_test_db(db_name):
                await _drop_test_database(test_database_url, db_name)
        unregister_namespace(namespace)
_WRITE_STMT_PREFIXES = ('INSERT', 'UPDATE', 'DELETE', 'TRUNCATE'); _TABLE_EXTRACT_RE = re.compile('(?:INSERT\\s+INTO|UPDATE|DELETE\\s+FROM|TRUNCATE(?:\\s+TABLE)?)\\s+[\\"\'\\`]?([a-zA-Z0-9_]+)[\\"\'\\`]?', re.IGNORECASE); _DIRTY_TABLES: set[str] = set()
async def _cleanup_dirty_tables(engine) -> None:
    global _DIRTY_TABLES
    if not _DIRTY_TABLES: return
    from src.database import Base; sorted_tables = Base.metadata.sorted_tables; to_delete = [t.name for t in reversed(sorted_tables)] if '__ALL__' in _DIRTY_TABLES else [t.name for t in reversed(sorted_tables) if t.name.lower() in _DIRTY_TABLES]
    if to_delete:
        async with engine.begin() as conn:
            await conn.execute(text("SET session_replication_role = 'replica'"))
            for table_name in to_delete: await conn.execute(text(f'DELETE FROM "{table_name}"'))
            await conn.execute(text("SET session_replication_role = 'origin'"))
    _DIRTY_TABLES.clear()
_DB_FIXTURES = {'db', 'db_engine', 'client', 'public_client', 'test_user', 'test_user_id', 'db_session'}
@pytest_asyncio.fixture(scope='function')
async def db_engine(request, _schema_engine):
    if request.node.get_closest_marker('no_db'): yield None; return
    if not (_DB_FIXTURES.intersection(request.fixturenames) or request.node.get_closest_marker('db')): yield None; return
    await _cleanup_dirty_tables(_schema_engine); yield _schema_engine
@pytest_asyncio.fixture(scope='function', autouse=True)
async def patch_database_connection(db_engine):
    if db_engine is None: yield; return
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker; from src import database; test_maker = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False); database.set_test_session_maker(test_maker); yield; database.set_test_session_maker(None)
@pytest_asyncio.fixture(scope='function')
async def db(db_engine):
    async_session = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)
    async with async_session() as session:
        session.info['test_arrange_session'] = True
        yield session
        await session.rollback()
@pytest_asyncio.fixture(scope='function')
async def test_user(db: AsyncSession): from src.identity import User; user = User(id=uuid4(), email=f'test-{uuid4()}@example.com', hashed_password='hashed'); db.add(user); await db.commit(); return user
@pytest.fixture(scope='function')
def test_user_id(test_user): return test_user.id
@pytest_asyncio.fixture(scope='function')
async def client(db_engine, test_user, test_database_url):
    os.environ['DATABASE_URL'] = test_database_url; from src.identity import create_access_token; from src.main import app; token = create_access_token(data={'sub': str(test_user.id)})
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url='http://test', headers={'Authorization': f'Bearer {token}'}) as client: yield client
    finally: pass
@pytest_asyncio.fixture(scope='function')
async def public_client(db_engine, test_database_url):
    os.environ['DATABASE_URL'] = test_database_url; test_maker = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False); from src import database; database.set_test_session_maker(test_maker); from src.main import app
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url='http://test') as client: yield client
    finally: database.set_test_session_maker(None)
@pytest.fixture(scope='session')
def openapi_schema() -> dict[str, Any]: from src.main import app; return app.openapi()


# --- Model calls in tests (#3153) ---------------------------------------------------------------------------
# No test reaches a provider. A test gives a fake model (`fake_llm`), or replays a recording
# (`@pytest.mark.vcr` with `vcr_llm`; `pytest --record-mode=rewrite <test>` records it again).
from pydantic_ai import models as _pydantic_ai_models  # noqa: E402

_pydantic_ai_models.ALLOW_MODEL_REQUESTS = False
# litellm downloads its price table on import. A recording must hold the model request only. This line goes
# away with litellm (#3153).
os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")


def pytest_recording_configure(config: Any, vcr: Any) -> None:
    from tests._support.llm_replay import llm_body_matches

    vcr.register_matcher("llm_body", llm_body_matches)


@pytest.fixture(scope="module")
def vcr_config() -> dict[str, Any]:
    from tests._support.llm_replay import llm_vcr_config

    return llm_vcr_config()


@pytest.fixture
def vcr_llm(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch):
    """Allow the model request of a replay test. `LLM_API_KEY` is needed only to record."""
    from infra2_sdk.runtime import allow_vcr_model_requests

    from src.config import settings
    from tests._support.llm_replay import require_vcr_marker

    require_vcr_marker(request)
    monkeypatch.setattr(settings, "ai_api_key", os.environ.get("LLM_API_KEY") or "replay-key")
    with allow_vcr_model_requests():
        yield


@pytest.fixture
def fake_llm(monkeypatch: pytest.MonkeyPatch):
    """Return a function that installs a fake model: `fake_llm(lambda prompt: "reply")` returns what was sent.

    See `tests/_support/fake_llm.py`. A test without a fixture argument calls `install_fake_model` itself.
    """
    from tests._support.fake_llm import install_fake_model

    return lambda reply: install_fake_model(monkeypatch, reply)
