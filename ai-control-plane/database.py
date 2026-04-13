"""
database.py — Database Connection Management & ORM Setup
=========================================================
Task: S-03
Provides async SQLAlchemy engine, session factory, connection health checks,
and migration support. Uses SQLite for development, PostgreSQL for production.
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator

import structlog
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy import DateTime, Boolean, func
from datetime import datetime, timezone
import uuid

from config import get_settings

logger = structlog.get_logger("database")


# ─── Base Model ─────────────────────────────────────────────────────────────────

class Base(DeclarativeBase):
    """Base class for all ORM models with common audit fields."""
    pass


class TimestampMixin:
    """Mixin providing created_at, updated_at, and soft-delete fields."""
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    is_deleted: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )


# ─── Engine & Session Factory ───────────────────────────────────────────────────

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def _build_engine_kwargs(database_url: str) -> dict:
    """Build engine kwargs appropriate for the database backend."""
    kwargs = {
        "echo": get_settings().is_development,
    }

    if "sqlite" in database_url:
        # SQLite-specific: ensure the data directory exists
        db_path = database_url.split("///")[-1] if "///" in database_url else None
        if db_path and db_path != ":memory:":
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    else:
        # PostgreSQL / production: connection pooling
        kwargs.update({
            "pool_size": 10,
            "max_overflow": 20,
            "pool_timeout": 30,
            "pool_recycle": 1800,
            "pool_pre_ping": True,
        })

    return kwargs


async def init_engine(database_url: str | None = None) -> AsyncEngine:
    """
    Initialize the async database engine.
    Call once at application startup.
    """
    global _engine, _session_factory

    url = database_url or get_settings().database_url
    kwargs = _build_engine_kwargs(url)

    _engine = create_async_engine(url, **kwargs)

    # Enable WAL mode for SQLite (better concurrency)
    if "sqlite" in url:
        @event.listens_for(_engine.sync_engine, "connect")
        def set_sqlite_pragma(dbapi_conn, connection_record):
            cursor = dbapi_conn.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    _session_factory = async_sessionmaker(
        bind=_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    logger.info("database_engine_initialized", url=url.split("@")[-1])  # Hide credentials
    return _engine


def get_engine() -> AsyncEngine:
    """Get the initialized engine. Raises if not initialized."""
    if _engine is None:
        raise RuntimeError(
            "Database engine not initialized. Call init_engine() first."
        )
    return _engine


# ─── Session Management ─────────────────────────────────────────────────────────

@asynccontextmanager
async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """
    Provide a transactional database session.
    Commits on success, rolls back on exception, always closes.
    """
    if _session_factory is None:
        raise RuntimeError("Database not initialized. Call init_engine() first.")

    session = _session_factory()
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


async def get_session_dependency() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency injection for database sessions."""
    async with get_session() as session:
        yield session


# ─── Health Check ────────────────────────────────────────────────────────────────

async def check_health() -> dict:
    """
    Validate database connectivity. Returns health status dict.
    Used by startup validation and /health endpoint.
    """
    try:
        async with get_session() as session:
            result = await session.execute(text("SELECT 1"))
            row = result.scalar()
            if row != 1:
                return {"status": "unhealthy", "error": "Unexpected query result"}
        return {"status": "healthy", "database": "connected"}
    except Exception as e:
        logger.error("database_health_check_failed", error=str(e))
        return {"status": "unhealthy", "error": str(e)}


# ─── Schema Creation (Dev Mode) ─────────────────────────────────────────────────

async def create_all_tables() -> None:
    """
    Create all tables from ORM models.
    Used in development; production uses Alembic migrations.
    """
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("database_tables_created")


async def drop_all_tables() -> None:
    """Drop all tables. USE WITH CAUTION."""
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    logger.warning("database_tables_dropped")


# ─── Shutdown ────────────────────────────────────────────────────────────────────

async def shutdown_engine() -> None:
    """Gracefully close all database connections."""
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
        _engine = None
        _session_factory = None
        logger.info("database_engine_shutdown")
