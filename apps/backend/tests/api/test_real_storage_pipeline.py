"""Real StorageService pipeline tests over moto's in-memory S3 (issue #1520).

Until now every counted test stubbed the storage seam (DummyStorage /
monkeypatched boto3), so a regression in the real ``StorageService`` wiring —
upload, persist, load-back — shipped undetected (EPIC-008 AC8.26). These tests
run the REAL service and the REAL upload→store→parse pipeline against an
in-memory S3: no stub, no monkeypatched StorageService, no service container.

The fixture is the same deterministic CSV the vision hard gate uploads in the
in-runner E2E (tests/e2e/fixtures/vision_hard_gate_statement.csv), so the same
known business numbers are proven here at the fast counted tier.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest
from moto import mock_aws

import src.routers.statements as statements_router
from src.config import settings
from src.extraction.orm.statement_enums import BankStatementStatus
from src.runtime import StorageService

REPO_ROOT = Path(__file__).resolve().parents[4]
CSV_FIXTURE = REPO_ROOT / "tests" / "e2e" / "fixtures" / "vision_hard_gate_statement.csv"

EXPECTED_TRANSACTION_COUNT = 6
EXPECTED_TOTAL_INCOME = Decimal("5600.00")
EXPECTED_TOTAL_EXPENSES = Decimal("5600.00")


@pytest.fixture
def real_s3(monkeypatch: pytest.MonkeyPatch):
    """moto-backed S3: the real boto3 client in StorageService hits an
    in-memory backend. Only env-level config is touched — the service itself
    is never stubbed or patched (AC8.26.1)."""
    monkeypatch.setattr(settings, "s3_endpoint", None)
    monkeypatch.setattr(settings, "s3_access_key", "testing")
    monkeypatch.setattr(settings, "s3_secret_key", "testing")
    monkeypatch.setattr(settings, "s3_bucket", "real-pipeline-test")
    # Same posture as docker-compose.ci-e2e.yml (#1592): placeholder provider
    # wiring with an unroutable base URL, so if any parse path falls back to
    # the AI leg it fails in milliseconds instead of retrying a live provider.
    monkeypatch.setattr(settings, "ai_api_key", "test-placeholder-key")
    monkeypatch.setattr(settings, "ai_base_url", "http://127.0.0.1:9/unroutable")
    # StorageService caches bucket existence at class level, but mock_aws
    # resets the in-memory backend per test — clear the cache so each test
    # re-creates its bucket instead of trusting a stale check (Copilot on
    # #1601: otherwise the second test in a worker is order-dependent).
    StorageService._checked_buckets.clear()
    with mock_aws():
        yield
    StorageService._checked_buckets.clear()


async def _upload_csv(db, test_user) -> statements_router.BankStatementResponse:
    from tests.api.test_statements_router import make_upload_file

    upload_file = make_upload_file("vision_hard_gate_statement.csv", CSV_FIXTURE.read_bytes())
    return await statements_router.upload_statement(
        file=upload_file,
        institution="Generic Vision Hard Gate",
        account_id=None,
        model=None,
        db=db,
        user_id=test_user.id,
    )


async def test_AC8_26_1_upload_parses_through_real_storage_round_trip(real_s3, db, test_user):
    """AC-runtime.23.1: AC8.26.1: the CSV fixture uploads through the real StorageService into
    in-memory S3, the pipeline parses it, and the stored object read back via
    the real get_object is byte-identical to the fixture."""
    user_id = test_user.id
    result = await _upload_csv(db, test_user)
    await statements_router.wait_for_parse_tasks()

    db.expire_all()
    statement = await statements_router._get_statement_or_404(db, result.id, user_id)
    assert statement.status == BankStatementStatus.PARSED, statement.validation_error

    # Functional round-trip (AC-2): bytes written == bytes read, via the REAL
    # service against the in-memory backend — not a call-assertion mock.
    key = statements_router.build_statement_storage_key(
        statement_id=result.id, file_hash=statement.file_hash, extension="csv"
    )
    stored = StorageService().get_object(key)
    assert stored == CSV_FIXTURE.read_bytes()

    # Business values, not just "it ran" (#1505): the same fixture numbers the
    # vision hard gate asserts end-to-end (5600 income + 5600 expenses), read
    # back the way the /transactions endpoint resolves them.
    txns = await statements_router.resolve_statement_transactions(db, statement)
    assert len(txns) == EXPECTED_TRANSACTION_COUNT
    gross = sum((abs(Decimal(str(t.amount))) for t in txns), Decimal("0"))
    assert gross == EXPECTED_TOTAL_INCOME + EXPECTED_TOTAL_EXPENSES


async def test_AC8_26_2_retry_loads_source_back_through_real_storage(real_s3, db, test_user):
    """AC-runtime.23.2: AC8.26.2: the retry path re-fetches the source document through the
    real get_object (the load-back leg the in-process first parse skips), and
    deleting the stored object makes retry fail — proving the pipeline truly
    reads storage, not a cached copy (the interception proof)."""
    user_id = test_user.id
    result = await _upload_csv(db, test_user)
    await statements_router.wait_for_parse_tasks()

    retried = await statements_router.retry_statement_parsing(
        statement_id=result.id, request=None, db=db, user_id=user_id
    )
    await statements_router.wait_for_parse_tasks()
    db.expire_all()
    statement = await statements_router._get_statement_or_404(db, retried.id, user_id)
    assert statement.status == BankStatementStatus.PARSED, statement.validation_error

    # Interception (AC-5): drop the stored object; the load-back path must
    # fail rather than parse a cached copy. The failure may surface as an
    # immediate error or as a non-PARSED terminal status from the background
    # task — either proves the pipeline truly reads storage.
    key = statements_router.build_statement_storage_key(
        statement_id=result.id, file_hash=statement.file_hash, extension="csv"
    )
    StorageService().delete_object(key)
    failed_fast = False
    try:
        await statements_router.retry_statement_parsing(statement_id=result.id, request=None, db=db, user_id=user_id)
    except Exception:
        failed_fast = True
    await statements_router.wait_for_parse_tasks()
    db.expire_all()
    refreshed = await statements_router._get_statement_or_404(db, result.id, user_id)
    assert failed_fast or refreshed.status != BankStatementStatus.PARSED, (
        "retry parsed successfully despite the source object being deleted — the pipeline is not reading real storage"
    )
