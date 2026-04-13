"""
main.py — Application Entry Point
===================================
Tasks: I-01, I-02
Initializes all components, starts background tasks,
configures the server, and handles graceful shutdown.
"""

from __future__ import annotations

import asyncio
import sys
from contextlib import asynccontextmanager
from datetime import datetime, timezone

import structlog
import uvicorn

from config import get_settings, get_policy_manager
from database import init_engine, create_all_tables, check_health, shutdown_engine
from observability import configure_logging, init_metrics


# Configure logging first (before any other imports that might log)
configure_logging()
logger = structlog.get_logger("main")


@asynccontextmanager
async def lifespan(app):
    """
    Application lifespan manager.
    Handles startup initialization and graceful shutdown.
    """
    settings = get_settings()
    startup_time = datetime.now(timezone.utc)

    # ── Startup ─────────────────────────────────────────
    logger.info("=" * 60)
    logger.info(
        "ai_control_plane_starting",
        version="0.1.0",
        environment=settings.environment.value,
        mock_mode=settings.is_mock_mode,
    )
    logger.info("=" * 60)

    # 1. Initialize database
    logger.info("initializing_database")
    await init_engine()

    # 2. Create tables (dev mode — production uses Alembic)
    if settings.is_development:
        logger.info("creating_tables_dev_mode")
        await create_all_tables()

    # 3. Health check
    health = await check_health()
    if health["status"] != "healthy":
        logger.error("database_health_check_failed", health=health)
        sys.exit(1)
    logger.info("database_healthy", **health)

    # 4. Load policies
    try:
        policy = get_policy_manager()
        logger.info(
            "policies_loaded",
            sections=list(policy.all_policies.keys()),
        )
    except FileNotFoundError as e:
        logger.warning("policy_file_missing", error=str(e))

    # 5. Initialize metrics
    init_metrics()
    logger.info("metrics_initialized")

    # 6. Check Claude API configuration
    if settings.is_mock_mode:
        logger.warning(
            "claude_mock_mode_active",
            message="Running with mock AI responses. Set CLAUDE_API_KEY in .env to use real Claude API.",
        )
    else:
        logger.info("claude_api_configured", model=settings.claude_model)

    # 7. Start background tasks
    background_tasks = []

    # Reconciliation loop
    from orchestrator import run_reconciliation_loop
    reconciliation_task = asyncio.create_task(run_reconciliation_loop())
    background_tasks.append(reconciliation_task)
    logger.info("background_task_started", task="reconciliation_loop")

    # Startup complete
    elapsed = (datetime.now(timezone.utc) - startup_time).total_seconds()
    logger.info(
        "startup_complete",
        elapsed_seconds=round(elapsed, 2),
        api_url=f"http://{settings.api_host}:{settings.api_port}",
        docs_url=f"http://{settings.api_host}:{settings.api_port}/docs",
    )

    yield  # ── Application is running ──

    # ── Shutdown ────────────────────────────────────────
    logger.info("shutdown_initiated")

    # Cancel background tasks
    for task in background_tasks:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    logger.info("background_tasks_cancelled")

    # Close database connections
    await shutdown_engine()
    logger.info("shutdown_complete")


def create_application():
    """Create the FastAPI application with lifespan."""
    from api import create_app
    app = create_app()
    app.router.lifespan_context = lifespan
    return app


# Create the app instance
app = create_application()


if __name__ == "__main__":
    settings = get_settings()

    uvicorn.run(
        "main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=settings.api_reload and settings.is_development,
        log_level=settings.log_level.lower(),
        access_log=settings.is_development,
    )
