"""FastAPI application — entry point, lifespan, and health endpoints."""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI

from agent.config import settings
from agent.logging import get_logger, setup_logging
from api.routes.admin import router as admin_router
from api.routes.webhooks import router as webhook_router
from db.connection import close_db, engine

setup_logging()
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup / shutdown lifecycle."""
    logger.info("agent_starting", env=settings.app_env)

    # Verify DB connectivity
    try:
        async with engine.connect() as conn:
            await conn.execute(
                __import__("sqlalchemy").text("SELECT 1")
            )
        logger.info("database_connected")
    except Exception as exc:
        logger.error("database_connection_failed", error=str(exc))

    yield

    # Shutdown
    await close_db()
    logger.info("agent_stopped")


app = FastAPI(
    title="Invoice-to-Accounting Agent",
    description="AI-powered invoice processing for hospitality group",
    version="0.1.0",
    lifespan=lifespan,
)

# ── Routes ─────────────────────────────────────────────────────────────────
app.include_router(webhook_router, prefix="/webhooks", tags=["webhooks"])
app.include_router(admin_router, prefix="/admin", tags=["admin"])


# ── Health checks ──────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {
        "status": "ok",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "version": "0.1.0",
    }


@app.get("/health/db")
async def health_db():
    try:
        async with engine.connect() as conn:
            await conn.execute(__import__("sqlalchemy").text("SELECT 1"))
        return {"status": "ok", "database": "connected"}
    except Exception as exc:
        return {"status": "error", "database": str(exc)}
