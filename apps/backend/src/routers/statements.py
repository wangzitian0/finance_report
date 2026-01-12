"""Statement extraction API router."""

import hashlib
import mimetypes
from pathlib import Path
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.auth import get_current_user_id
from src.database import get_db
from src.models import BankStatement, BankStatementStatus
from src.schemas import (
    BankStatementListResponse,
    BankStatementResponse,
    BankStatementTransactionListResponse,
    BankStatementTransactionResponse,
    StatementDecisionRequest,
)
from src.services import ExtractionError, ExtractionService, StorageError, StorageService

router = APIRouter(prefix="/api/statements", tags=["statements"])

MAX_UPLOAD_BYTES = 10 * 1024 * 1024


@router.post("/upload", response_model=BankStatementResponse)
async def upload_statement(
    file: UploadFile = File(...),
    institution: str = Form(...),
    account_id: UUID | None = Form(None),
    db: AsyncSession = Depends(get_db),
    user_id: UUID = Depends(get_current_user_id),
) -> BankStatementResponse:
    """
    Upload and parse a financial statement.

    Supported file types: PDF, CSV, PNG, JPG
    """
    filename = Path(file.filename or "unknown").name or "unknown"
    extension = filename.rsplit(".", 1)[-1].lower() if "." in filename else "pdf"

    if extension not in ("pdf", "csv", "png", "jpg", "jpeg"):
        raise HTTPException(400, f"Unsupported file type: {extension}")

    content = await file.read()
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="File exceeds 10MB limit",
        )

    file_hash = hashlib.sha256(content).hexdigest()
    duplicate = await db.execute(
        select(BankStatement.id)
        .where(BankStatement.user_id == user_id)
        .where(BankStatement.file_hash == file_hash)
    )
    if duplicate.scalar_one_or_none():
        raise HTTPException(status.HTTP_409_CONFLICT, "Duplicate statement upload")

    try:
        statement_id = uuid4()
        storage_key = f"statements/{statement_id}/{filename}"
        content_type = (
            file.content_type or mimetypes.guess_type(filename)[0] or "application/octet-stream"
        )

        storage = StorageService()
        await run_in_threadpool(
            storage.upload_bytes,
            key=storage_key,
            content=content,
            content_type=content_type,
        )
        file_url = await run_in_threadpool(storage.generate_presigned_url, key=storage_key)

        service = ExtractionService()
        statement, transactions = await service.parse_document(
            file_path=Path(filename),
            institution=institution,
            user_id=user_id,
            file_type=extension,
            account_id=account_id,
            file_content=content,
            file_hash=file_hash,
            file_url=file_url,
            original_filename=filename,
        )

        statement.id = statement_id
        statement.original_filename = filename
        statement.file_path = storage_key
        statement.transactions = transactions

        db.add(statement)
        await db.commit()
        await db.refresh(statement)

        result = await db.execute(
            select(BankStatement)
            .where(BankStatement.id == statement.id)
            .options(selectinload(BankStatement.transactions))
        )
        statement = result.scalar_one()
        return BankStatementResponse.model_validate(statement)

    except ExtractionError as e:
        raise HTTPException(422, str(e))
    except StorageError as e:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(e))


@router.get("", response_model=BankStatementListResponse)
async def list_statements(
    db: AsyncSession = Depends(get_db),
    user_id: UUID = Depends(get_current_user_id),
) -> BankStatementListResponse:
    """List all statements for the current user."""
    result = await db.execute(
        select(BankStatement)
        .where(BankStatement.user_id == user_id)
        .options(selectinload(BankStatement.transactions))
        .order_by(BankStatement.created_at.desc())
    )
    statements = result.scalars().all()

    total_result = await db.execute(
        select(func.count()).select_from(BankStatement).where(BankStatement.user_id == user_id)
    )
    total = total_result.scalar() or 0

    return BankStatementListResponse(
        items=[BankStatementResponse.model_validate(s) for s in statements],
        total=total,
    )


@router.get("/pending-review", response_model=BankStatementListResponse)
async def list_pending_review(
    db: AsyncSession = Depends(get_db),
    user_id: UUID = Depends(get_current_user_id),
) -> BankStatementListResponse:
    """List statements pending human review (confidence 60-84)."""
    result = await db.execute(
        select(BankStatement)
        .where(BankStatement.user_id == user_id)
        .where(BankStatement.status == BankStatementStatus.PARSED)
        .where(BankStatement.confidence_score >= 60)
        .where(BankStatement.confidence_score < 85)
        .options(selectinload(BankStatement.transactions))
        .order_by(BankStatement.created_at.desc())
    )
    statements = result.scalars().all()

    total_result = await db.execute(
        select(func.count())
        .select_from(BankStatement)
        .where(BankStatement.user_id == user_id)
        .where(BankStatement.status == BankStatementStatus.PARSED)
        .where(BankStatement.confidence_score >= 60)
        .where(BankStatement.confidence_score < 85)
    )
    total = total_result.scalar() or 0

    return BankStatementListResponse(
        items=[BankStatementResponse.model_validate(s) for s in statements],
        total=total,
    )


@router.get("/{statement_id}", response_model=BankStatementResponse)
async def get_statement(
    statement_id: UUID,
    db: AsyncSession = Depends(get_db),
    user_id: UUID = Depends(get_current_user_id),
) -> BankStatementResponse:
    """Get a statement with all its transactions."""
    result = await db.execute(
        select(BankStatement)
        .where(BankStatement.id == statement_id)
        .where(BankStatement.user_id == user_id)
        .options(selectinload(BankStatement.transactions))
    )
    statement = result.scalar_one_or_none()

    if not statement:
        raise HTTPException(404, "Statement not found")

    return BankStatementResponse.model_validate(statement)


@router.get("/{statement_id}/transactions", response_model=BankStatementTransactionListResponse)
async def list_statement_transactions(
    statement_id: UUID,
    db: AsyncSession = Depends(get_db),
    user_id: UUID = Depends(get_current_user_id),
) -> BankStatementTransactionListResponse:
    """List transactions for a statement."""
    result = await db.execute(
        select(BankStatement)
        .where(BankStatement.id == statement_id)
        .where(BankStatement.user_id == user_id)
        .options(selectinload(BankStatement.transactions))
    )
    statement = result.scalar_one_or_none()

    if not statement:
        raise HTTPException(404, "Statement not found")

    items = [BankStatementTransactionResponse.model_validate(t) for t in statement.transactions]
    return BankStatementTransactionListResponse(items=items, total=len(items))


@router.post("/{statement_id}/approve", response_model=BankStatementResponse)
async def approve_statement(
    statement_id: UUID,
    decision: StatementDecisionRequest,
    db: AsyncSession = Depends(get_db),
    user_id: UUID = Depends(get_current_user_id),
) -> BankStatementResponse:
    """Approve a statement after human review."""
    result = await db.execute(
        select(BankStatement)
        .where(BankStatement.id == statement_id)
        .where(BankStatement.user_id == user_id)
        .options(selectinload(BankStatement.transactions))
    )
    statement = result.scalar_one_or_none()

    if not statement:
        raise HTTPException(404, "Statement not found")

    statement.status = BankStatementStatus.APPROVED
    if decision.notes:
        statement.validation_error = decision.notes

    await db.commit()
    await db.refresh(statement)

    return BankStatementResponse.model_validate(statement)


@router.post("/{statement_id}/reject", response_model=BankStatementResponse)
async def reject_statement(
    statement_id: UUID,
    decision: StatementDecisionRequest,
    db: AsyncSession = Depends(get_db),
    user_id: UUID = Depends(get_current_user_id),
) -> BankStatementResponse:
    """Reject a statement after human review."""
    result = await db.execute(
        select(BankStatement)
        .where(BankStatement.id == statement_id)
        .where(BankStatement.user_id == user_id)
        .options(selectinload(BankStatement.transactions))
    )
    statement = result.scalar_one_or_none()

    if not statement:
        raise HTTPException(404, "Statement not found")

    statement.status = BankStatementStatus.REJECTED
    if decision.notes:
        statement.validation_error = decision.notes

    await db.commit()
    await db.refresh(statement)

    return BankStatementResponse.model_validate(statement)
