"""Finance Report Backend - FastAPI Application."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime

from fastapi import Depends, FastAPI
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.database import get_db, init_db
from src.models import PingState
from src.routers import accounts, auth, chat, journal, reports, statements, users
from src.routers.reconciliation import router as reconciliation_router
from src.schemas import PingStateResponse


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


@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    """Global exception handler to ensure JSON response."""
    import traceback

    traceback.print_exc()
    return JSONResponse(
        status_code=500,
        content={"detail": str(exc)},
    )

# CORS for frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH"],
    allow_headers=["Content-Type", "Authorization", "X-User-Id"],
)

# Include routers
app.include_router(auth.router)
app.include_router(accounts.router)
app.include_router(chat.router)
app.include_router(journal.router)
app.include_router(reports.router)
app.include_router(statements.router)
app.include_router(reconciliation_router)
app.include_router(users.router)


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
        return PingStateResponse(state="ping", toggle_count=0, updated_at=None)

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
