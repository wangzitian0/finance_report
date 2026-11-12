'AC-extraction.123.2 AC-extraction.123.3'; from __future__ import annotations; from unittest.mock import AsyncMock, patch; import pytest; import structlog; from sqlalchemy import delete, select; from sqlalchemy.exc import PendingRollbackError; from src.extraction import BankStatementStatus, ParseJob, UploadedDocument; from src.extraction.extension.statement_parsing import _ensure_failed_document_lineage, handle_parse_failure; from src.extraction.orm.statement_summary import StatementSummary; from src.identity import User; from tests.factories import StatementSummaryFactory; pytestmark = pytest.mark.asyncio
from tests.statement_ingestion import run_for
async def test_AC13_23_2_failed_lineage_skips_when_user_deleted(db, test_user): 'AC-extraction.123.2'; statement = await StatementSummaryFactory.create_async(db, user_id=test_user.id, status=BankStatementStatus.PARSING); await db.commit(); file_hash = statement.file_hash; db.expunge(statement); await db.execute(delete(StatementSummary).where(StatementSummary.user_id == test_user.id)); await db.execute(delete(User).where(User.id == test_user.id)); await db.commit(); await _ensure_failed_document_lineage(db, statement, file_hash=file_hash, storage_key='statements/synthetic/synthetic.pdf', original_filename='synthetic.pdf'); leftover = (await db.execute(select(UploadedDocument).where(UploadedDocument.file_hash == file_hash))).scalar_one_or_none(); assert leftover is None
async def test_AC13_23_3_failure_handler_rolls_back_before_reading_orm(db, test_user):
    'AC-extraction.123.3'; statement = await StatementSummaryFactory.create_async(db, user_id=test_user.id, status=BankStatementStatus.PARSING); await db.commit(); real_id = statement.id; order: list[str] = []; original_rollback = db.rollback
    async def _tracking_rollback(): order.append('rollback'); await original_rollback()
    class _PoisonedStatement:
        user_id = statement.user_id
        @property
        def id(self):
            if 'rollback' not in order: raise PendingRollbackError('statement.id read before rollback')
            return real_id
    with patch.object(db, 'rollback', _tracking_rollback): await handle_parse_failure(_PoisonedStatement(), db, job=ParseJob(statement_id=real_id, run_id=await run_for(db, real_id), filename='statement.pdf', institution=statement.institution, user_id=statement.user_id, account_id=statement.account_id, file_hash=statement.file_hash, storage_key=f'statements/{real_id}/statement.pdf', model=None), message='Finalize failed: original boom')
    assert order == ['rollback']; refreshed = await db.get(StatementSummary, real_id); assert refreshed.status == BankStatementStatus.REJECTED
async def test_AC13_23_3_original_error_not_masked(db, test_user):
    'AC-extraction.123.3'; statement = await StatementSummaryFactory.create_async(db, user_id=test_user.id, status=BankStatementStatus.PARSING); await db.commit(); original_message = 'Parsing failed: synthetic original FK violation'
    with patch.object(db, 'get', new=AsyncMock(side_effect=PendingRollbackError('session still dirty'))), structlog.testing.capture_logs() as logs: await handle_parse_failure(statement, db, message=original_message)
    assert any((original_message in str(entry.values()) for entry in logs))
