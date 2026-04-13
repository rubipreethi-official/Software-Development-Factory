"""
Shared pytest fixtures for the AI Control Plane test suite.
Provides in-memory database, sessions, and test data factories.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from datetime import datetime, timezone
from typing import AsyncGenerator

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

# ── Force test settings BEFORE any app imports ──────────────────────────────────
os.environ["CLAUDE_API_KEY"] = "mock"
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
os.environ["ENVIRONMENT"] = "development"
os.environ["LOG_LEVEL"] = "WARNING"

from config import get_settings, Settings
from database import Base

# Reset the cached settings so our env vars take effect
get_settings.cache_clear()


# ── Async mode config ──────────────────────────────────────────────────────────
# pytest-asyncio auto mode is configured via pyproject.toml or pytest.ini
# No custom event_loop fixture needed — pytest-asyncio handles it.


# ── Database engine & session ───────────────────────────────────────────────────

@pytest_asyncio.fixture
async def db_engine() -> AsyncGenerator[AsyncEngine, None]:
    """Create an in-memory SQLite engine for each test."""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        echo=False,
    )
    # Import all models so Base.metadata knows about them
    import models  # noqa: F401

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield engine

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(db_engine: AsyncEngine) -> AsyncGenerator[AsyncSession, None]:
    """
    Per-test transactional session.
    Rolls back all changes after each test for isolation.
    """
    session_factory = async_sessionmaker(
        bind=db_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    async with session_factory() as session:
        yield session
        await session.rollback()


# ── Test data factories ─────────────────────────────────────────────────────────

class PRDFactory:
    """Factory for creating test PRD objects."""

    @staticmethod
    async def create(session: AsyncSession, **overrides) -> "PRD":
        from models import PRD, PRDStatus
        defaults = {
            "title": "Test PRD — User Auth Service",
            "raw_content": (
                "# User Authentication Service\n\n"
                "## Overview\n"
                "Build a REST API for user authentication with JWT tokens.\n\n"
                "## Requirements\n"
                "- Users can register with email and password\n"
                "- Passwords must be hashed with bcrypt\n"
                "- Login returns JWT access and refresh tokens\n"
                "- Protected endpoints require valid JWT\n"
                "- Token refresh without re-authentication\n"
                "- Rate limiting on auth endpoints\n"
            ),
            "status": PRDStatus.VALIDATED,
            "word_count": 45,
        }
        defaults.update(overrides)
        prd = PRD(**defaults)
        session.add(prd)
        await session.flush()
        return prd


class SpecFactory:
    """Factory for creating test StructuredSpec objects."""

    @staticmethod
    async def create(session: AsyncSession, prd_id: str, **overrides) -> "StructuredSpec":
        from models import StructuredSpec, SpecStatus
        defaults = {
            "prd_id": prd_id,
            "version": 1,
            "status": SpecStatus.DRAFT,
            "content": {
                "title": "User Authentication Service",
                "overview": "A structured spec for user auth.",
                "functional_requirements": [
                    {
                        "id": "REQ-000001",
                        "description": "User registration with email and password",
                        "priority": "high",
                        "category": "authentication",
                        "acceptance_criteria": "Users can register with unique email",
                    },
                ],
                "non_functional_requirements": [],
                "api_endpoints": [],
                "data_models": [],
                "constraints": ["Must use Python 3.11+"],
                "assumptions": [],
                "out_of_scope": [],
            },
        }
        defaults.update(overrides)
        spec = StructuredSpec(**defaults)
        session.add(spec)
        await session.flush()
        return spec


class WorkflowFactory:
    """Factory for creating test WorkflowExecution objects."""

    @staticmethod
    async def create(session: AsyncSession, prd_id: str, **overrides) -> "WorkflowExecution":
        from models import WorkflowExecution, WorkflowState
        defaults = {
            "prd_id": prd_id,
            "state": WorkflowState.IDLE,
            "started_at": datetime.now(timezone.utc),
        }
        defaults.update(overrides)
        workflow = WorkflowExecution(**defaults)
        session.add(workflow)
        await session.flush()
        return workflow


@pytest.fixture
def prd_factory():
    return PRDFactory


@pytest.fixture
def spec_factory():
    return SpecFactory


@pytest.fixture
def workflow_factory():
    return WorkflowFactory
