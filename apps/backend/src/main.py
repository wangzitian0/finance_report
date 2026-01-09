"""Finance Report Backend - FastAPI Application."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from tempfile import NamedTemporaryFile

from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.config import settings
from src.database import get_db, init_db
from src.models import PingState, Statement, StatementStatus
from src.routers import accounts, journal
from src.schemas import (
    PingStateResponse,
    ReviewDecision,
    StatementListResponse,
    StatementResponse,
)
from src.services import ExtractionError, ExtractionService


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Application lifespan - init DB on startup."""
    await init_db()
    yield


app = FastAPI(
    title="Finance Report API",
    description="Personal financial management system with double-entry bookkeeping",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS for frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH"],
    allow_headers=["Content-Type", "Authorization"],
)

# Include routers
app.include_router(accounts.router)
app.include_router(journal.router)


# --- Health & Demo Endpoints ---


@app.get("/health")
async def health_check() -> dict[str, str]:
    """Health check endpoint."""
    return {"status": "healthy", "timestamp": datetime.now(UTC).isoformat()}


@app.get("/ping", response_model=PingStateResponse)
async def get_ping_state(db: AsyncSession = Depends(get_db)) -> PingStateResponse:
    """Get current ping-pong state."""
    result = await db.execute(select(PingState).order_by(PingState.id.desc()).limit(1))
    state = result.scalar_one_or_none()

    if state is None:
        return PingStateResponse(state="ping", toggle_count=0, last_toggled=None)

    return PingStateResponse.model_validate(state)


@app.post("/ping/toggle", response_model=PingStateResponse)
async def toggle_ping_state(db: AsyncSession = Depends(get_db)) -> PingStateResponse:
    """Toggle between ping and pong state."""
    result = await db.execute(select(PingState).order_by(PingState.id.desc()).limit(1))
    state = result.scalar_one_or_none()

    if state is None:
        new_state = PingState(state="pong", toggle_count=1)
        db.add(new_state)
        await db.commit()
        await db.refresh(new_state)
        return PingStateResponse.model_validate(new_state)

    state.state = "pong" if state.state == "ping" else "ping"
    state.toggle_count += 1
    await db.commit()
    await db.refresh(state)

    return PingStateResponse.model_validate(state)


# --- Document Extraction Endpoints ---


@app.post("/statements/upload", response_model=StatementResponse)
async def upload_statement(
    file: UploadFile = File(...),
    institution: str = Form(...),
    db: AsyncSession = Depends(get_db),
) -> StatementResponse:
    """
    Upload and parse a financial statement.

    Supported file types: PDF, CSV, PNG, JPG
    """
    # Determine file type
    filename = file.filename or "unknown"
    extension = filename.rsplit(".", 1)[-1].lower() if "." in filename else "pdf"

    if extension not in ("pdf", "csv", "png", "jpg", "jpeg"):
        raise HTTPException(400, f"Unsupported file type: {extension}")

    # Save to temp file and process
    tmp_path = None
    try:
        content = await file.read()
        with NamedTemporaryFile(delete=False, suffix=f".{extension}") as tmp:
            tmp.write(content)
            tmp_path = Path(tmp.name)

        # Parse document
        service = ExtractionService()
        statement, events = await service.parse_document(
            file_path=tmp_path,
            institution=institution,
            file_type=extension,
        )

        # Update file path to use original filename
        statement.original_filename = filename
        statement.file_path = f"statements/{statement.id}/{filename}"

        # Save to database
        db.add(statement)
        for event in events:
            event.statement_id = statement.id
            db.add(event)

        await db.commit()
        await db.refresh(statement)

        # Reload with events
        result = await db.execute(
            select(Statement)
            .where(Statement.id == statement.id)
            .options(selectinload(Statement.events))
        )
        statement = result.scalar_one()

        return StatementResponse.model_validate(statement)

    except ExtractionError as e:
        raise HTTPException(422, str(e))
    finally:
        # Cleanup temp file
        if tmp_path:
            tmp_path.unlink(missing_ok=True)


@app.get("/statements/pending-review", response_model=StatementListResponse)
async def list_pending_review(
    db: AsyncSession = Depends(get_db),
) -> StatementListResponse:
    """List statements pending human review (confidence 60-84)."""
    result = await db.execute(
        select(Statement)
        .where(Statement.status == StatementStatus.PARSED)
        .where(Statement.confidence_score >= 60)
        .where(Statement.confidence_score < 85)
        .options(selectinload(Statement.events))
        .order_by(Statement.created_at.desc())
    )
    statements = result.scalars().all()

    # Also count total pending
    total_result = await db.execute(
        select(Statement).where(Statement.status == StatementStatus.PARSED)
    )
    total = len(total_result.scalars().all())

    return StatementListResponse(
        items=[StatementResponse.model_validate(s) for s in statements],
        total=total,
    )


@app.get("/statements/{statement_id}", response_model=StatementResponse)
async def get_statement(
    statement_id: str,
    db: AsyncSession = Depends(get_db),
) -> StatementResponse:
    """Get a statement with all its events."""
    result = await db.execute(
        select(Statement)
        .where(Statement.id == statement_id)
        .options(selectinload(Statement.events))
    )
    statement = result.scalar_one_or_none()

    if not statement:
        raise HTTPException(404, "Statement not found")

    return StatementResponse.model_validate(statement)


@app.post("/statements/{statement_id}/approve", response_model=StatementResponse)
async def approve_statement(
    statement_id: str,
    decision: ReviewDecision,
    db: AsyncSession = Depends(get_db),
) -> StatementResponse:
    """Approve or reject a statement after human review."""
    result = await db.execute(
        select(Statement)
        .where(Statement.id == statement_id)
        .options(selectinload(Statement.events))
    )
    statement = result.scalar_one_or_none()

    if not statement:
        raise HTTPException(404, "Statement not found")

    if decision.approved:
        statement.status = StatementStatus.APPROVED
    else:
        statement.status = StatementStatus.REJECTED
        if decision.notes:
            statement.validation_error = decision.notes

    await db.commit()
    await db.refresh(statement)

    return StatementResponse.model_validate(statement)
