"""Finance Report Backend - FastAPI Application."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.database import get_db, init_db
from src.models import PingState


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


@app.get("/health")
async def health_check() -> dict[str, str]:
    """Health check endpoint."""
    return {"status": "healthy", "timestamp": datetime.now(UTC).isoformat()}


@app.get("/ping")
async def get_ping_state(db: AsyncSession = Depends(get_db)) -> dict:
    """Get current ping-pong state."""
    result = await db.execute(select(PingState).order_by(PingState.id.desc()).limit(1))
    state = result.scalar_one_or_none()

    if state is None:
        return {"state": "ping", "toggle_count": 0}

    return {
        "state": state.state,
        "toggle_count": state.toggle_count,
        "last_toggled": state.updated_at.isoformat() if state.updated_at else None,
    }


@app.post("/ping/toggle")
async def toggle_ping_state(db: AsyncSession = Depends(get_db)) -> dict:
    """Toggle between ping and pong state."""
    result = await db.execute(select(PingState).order_by(PingState.id.desc()).limit(1))
    state = result.scalar_one_or_none()

    if state is None:
        # Create initial state
        new_state = PingState(state="pong", toggle_count=1)
        db.add(new_state)
        await db.commit()
        await db.refresh(new_state)
        return {
            "state": new_state.state,
            "toggle_count": new_state.toggle_count,
            "last_toggled": new_state.updated_at.isoformat(),
        }

    # Toggle existing state
    state.state = "pong" if state.state == "ping" else "ping"
    state.toggle_count += 1
    # Let onupdate handle updated_at automatically
    await db.commit()
    await db.refresh(state)

    return {
        "state": state.state,
        "toggle_count": state.toggle_count,
        "last_toggled": state.updated_at.isoformat(),
    }
