from __future__ import annotations

import inspect
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import Request
from httpx import AsyncClient


async def test_health_healthy_and_503_failures(client: AsyncClient, public_client: AsyncClient, monkeypatch) -> None:
    from src.boot import Bootloader, ServiceStatus
    from src.database import get_db
    from src.main import app

    monkeypatch.setattr(Bootloader, "_check_s3", AsyncMock(return_value=ServiceStatus("s3", "ok", "Reachable")))
    ok = await client.get("/health?full=1")
    d = ok.json()
    assert ok.status_code == 200 and {"status", "timestamp", "checks"} <= set(d) and (d["checks"]["database"]["status"], d["checks"]["object_storage"]["status"]) == ("present", "present")

    async def bad_db():
        s = MagicMock()
        s.execute.side_effect = Exception("DB Down")
        yield s

    app.dependency_overrides[get_db] = bad_db
    try:
        r_db = await public_client.get("/health?full=1")
    finally:
        app.dependency_overrides.clear()
    assert (r_db.status_code, r_db.json()["status"], r_db.json()["checks"]["database"]["status"]) == (503, "unhealthy", "absent")

    monkeypatch.setattr(Bootloader, "_check_s3", AsyncMock(return_value=ServiceStatus("minio", "error", "Bucket missing")))
    r_s3 = await public_client.get("/health?full=1")
    assert (r_s3.status_code, r_s3.json()["status"], r_s3.json()["checks"]["object_storage"]["status"]) == (503, "unhealthy", "absent")


async def test_statement_routes_smoke_and_contracts(client: AsyncClient, monkeypatch) -> None:
    from infra2_sdk.runtime.llm import LlmSettings
    from src import main as main_module
    from src.config import Settings
    from src.database import Base, get_db
    from src.extraction import BankStatementStatus, UploadedDocument
    from src.extraction.orm.layer2 import AtomicTransaction
    from src.extraction.orm.statement_summary import StatementSummary
    from src.observability import ErrorIds
    from src.schemas.extraction import StatementDecisionRequest

    assert (await client.get("/statements/00000000-0000-0000-0000-000000000000")).status_code == 404
    pending = await client.get("/statements/pending-review")
    assert pending.status_code == 200 and (pending.json()["items"], pending.json()["total"]) == ([], 0)
    assert (await client.post("/statements", data={"institution": "DBS"})).status_code == 422

    assert StatementDecisionRequest().notes is None and StatementDecisionRequest(notes="x").notes == "x"
    assert (BankStatementStatus.UPLOADED.value, BankStatementStatus.PARSED.value, BankStatementStatus.APPROVED.value) == ("uploaded", "parsed", "approved")
    assert Base.metadata is not None and inspect.isasyncgenfunction(get_db)
    assert (StatementSummary.__tablename__, AtomicTransaction.__tablename__, UploadedDocument.__tablename__) == ("statement_summaries", "atomic_transactions", "uploaded_documents")
    assert all(hasattr(StatementSummary, a) for a in ("uploaded_document_id", "file_hash", "status")) and all(hasattr(AtomicTransaction, a) for a in ("dedup_hash", "source_documents", "balance_after"))

    for key in ("S3_BUCKET", "LARGE_MODEL", "SMALL_MODEL", "MULTIMODAL_MODEL"):
        monkeypatch.delenv(key, raising=False)
    s, sdk = Settings(_env_file=None), LlmSettings()
    assert (s.ai_provider, s.s3_bucket, s.large_model, s.small_model, s.multimodal_model) == ("zai", "statements", sdk.role_model("large"), sdk.role_model("small"), sdk.role_model("multimodal"))
    assert "postgresql" in Settings().database_url or "sqlite" in Settings().database_url

    mock_logger = MagicMock()
    monkeypatch.setattr(main_module, "logger", mock_logger)
    req = MagicMock(spec=Request, state=MagicMock(request_id="req-123"))
    resp = await main_module.global_exception_handler(req, RuntimeError("boom"))
    assert (resp.status_code, resp.headers["X-Request-ID"], mock_logger.exception.call_args.kwargs.get("error_id")) == (500, "req-123", ErrorIds.UNHANDLED_EXCEPTION)
