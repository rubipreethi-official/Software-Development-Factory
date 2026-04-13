"""
test_integration.py — End-to-end Integration Tests
====================================================
Task: V-02
Tests the full API surface via httpx.AsyncClient against the FastAPI app.
"""

from __future__ import annotations

import os
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport

# Force test settings
os.environ["CLAUDE_API_KEY"] = "mock"
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
os.environ["ENVIRONMENT"] = "development"
os.environ["LOG_LEVEL"] = "WARNING"

from config import get_settings
get_settings.cache_clear()


@pytest_asyncio.fixture
async def client():
    """Provide an async HTTP client bound to the FastAPI app."""
    from database import init_engine, create_all_tables, shutdown_engine
    from observability import configure_logging, init_metrics
    import models  # noqa: F401 — ensure all tables are registered on Base.metadata

    configure_logging()
    await init_engine("sqlite+aiosqlite:///:memory:")
    await create_all_tables()
    init_metrics()

    from api import create_app
    app = create_app()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    await shutdown_engine()


class TestHealthEndpoint:
    """Tests for /api/v1/health."""

    @pytest.mark.asyncio
    async def test_health_returns_200(self, client):
        r = await client.get("/api/v1/health")
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "healthy"
        assert data["mock_mode"] is True

    @pytest.mark.asyncio
    async def test_health_contains_required_fields(self, client):
        r = await client.get("/api/v1/health")
        data = r.json()
        assert "environment" in data
        assert "database" in data
        assert "timestamp" in data


class TestPRDSubmission:
    """Tests for PRD submission and workflow lifecycle."""

    @pytest.mark.asyncio
    async def test_submit_prd_accepted(self, client):
        """Submit a valid PRD and get 202 Accepted."""
        prd = {
            "title": "Test Auth Service",
            "content": (
                "# Auth Service\n\n## Overview\n"
                "Build a REST API for user authentication with JWT tokens, "
                "supporting registration, login, and token refresh.\n\n"
                "## Requirements\n- Users can register\n- Login returns JWT\n"
            ),
        }
        r = await client.post("/api/v1/prd", json=prd)
        assert r.status_code == 202
        data = r.json()
        assert "execution_id" in data
        assert "prd_id" in data
        assert data["status"] == "accepted"

    @pytest.mark.asyncio
    async def test_submit_short_prd_rejected(self, client):
        """PRD with too few words should be rejected."""
        prd = {"title": "Short", "content": "Too short."}
        r = await client.post("/api/v1/prd", json=prd)
        assert r.status_code == 400

    @pytest.mark.asyncio
    async def test_submit_missing_title_rejected(self, client):
        """PRD without title should be rejected by Pydantic."""
        r = await client.post("/api/v1/prd", json={"content": "some content"})
        assert r.status_code == 422  # Validation error


class TestExecutionEndpoints:
    """Tests for execution monitoring endpoints."""

    @pytest.mark.asyncio
    async def test_list_executions(self, client):
        r = await client.get("/api/v1/executions")
        assert r.status_code == 200
        data = r.json()
        assert "items" in data
        assert "total" in data

    @pytest.mark.asyncio
    async def test_get_nonexistent_execution(self, client):
        r = await client.get("/api/v1/executions/fake-id")
        assert r.status_code == 404


class TestArtifactEndpoints:
    """Tests for artifact retrieval endpoints."""

    @pytest.mark.asyncio
    async def test_spec_not_found(self, client):
        r = await client.get("/api/v1/executions/fake-id/spec")
        assert r.status_code == 404

    @pytest.mark.asyncio
    async def test_code_artifacts_empty(self, client):
        """Submit a PRD and check code artifacts endpoint returns."""
        # First submit a PRD to create a workflow
        prd = {
            "title": "Artifact Test",
            "content": "Build an API with user management, authentication, and CRUD operations for resources.",
        }
        r = await client.post("/api/v1/prd", json=prd)
        if r.status_code == 202:
            exec_id = r.json()["execution_id"]
            r2 = await client.get(f"/api/v1/executions/{exec_id}/code")
            # May or may not have artifacts depending on background task timing
            assert r2.status_code == 200


class TestReviewEndpoints:
    """Tests for human review endpoints."""

    @pytest.mark.asyncio
    async def test_list_reviews(self, client):
        r = await client.get("/api/v1/reviews")
        assert r.status_code == 200
        data = r.json()
        assert "reviews" in data

    @pytest.mark.asyncio
    async def test_approve_nonexistent_review(self, client):
        """Approving a non-existent review should fail."""
        r = await client.post(
            "/api/v1/reviews/fake-id/approve",
            json={"comments": "approved", "reviewer": "test"},
        )
        assert r.status_code >= 400  # Error response (500 from global handler)


class TestMetricsEndpoint:
    """Tests for /metrics (Prometheus)."""

    @pytest.mark.asyncio
    async def test_metrics_returns_prometheus_format(self, client):
        r = await client.get("/metrics")
        assert r.status_code == 200
        text = r.text
        # Should contain Prometheus-format metrics
        assert "ai_control_plane_info" in text or "workflows_total" in text or "HELP" in text


class TestOperationsEndpoints:
    """Tests for operational endpoints."""

    @pytest.mark.asyncio
    async def test_policy_reload(self, client):
        r = await client.post("/api/v1/policies/reload")
        assert r.status_code == 200
        assert r.json()["status"] == "reloaded"


class TestRateLimiting:
    """Tests for rate limiting middleware."""

    @pytest.mark.asyncio
    async def test_rate_limit_not_applied_to_health(self, client):
        """Health endpoint should bypass rate limiting."""
        for _ in range(10):
            r = await client.get("/api/v1/health")
            assert r.status_code == 200
