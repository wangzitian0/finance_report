"""Finance Report Backend - FastAPI Application."""

from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import get_db, init_db
from src.models import PingState


@asynccontextmanager
async def lifespan(app: FastAPI):
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
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "timestamp": datetime.now(timezone.utc).isoformat()}


@app.get("/ping")
async def get_ping_state(db: AsyncSession = Depends(get_db)):
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
async def toggle_ping_state(db: AsyncSession = Depends(get_db)):
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
    state.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(state)
    
    return {
        "state": state.state,
        "toggle_count": state.toggle_count,
        "last_toggled": state.updated_at.isoformat(),
    }
