"""
test_models.py — Unit tests for models.py
==========================================
Task: V-01
Tests ORM model CRUD, UUID generation, timestamps, and relationships.
"""

import pytest
import pytest_asyncio
from datetime import datetime, timezone
from sqlalchemy import select


class TestPRD:
    """Tests for the PRD model."""

    @pytest.mark.asyncio
    async def test_create_prd(self, db_session, prd_factory):
        prd = await prd_factory.create(db_session)
        assert prd.id is not None
        assert len(prd.id) == 36  # UUID format
        assert prd.title == "Test PRD — User Auth Service"
        assert prd.status == "validated"

    @pytest.mark.asyncio
    async def test_prd_timestamps(self, db_session, prd_factory):
        prd = await prd_factory.create(db_session)
        assert prd.created_at is not None
        assert prd.updated_at is not None
        assert prd.is_deleted is False

    @pytest.mark.asyncio
    async def test_prd_word_count(self, db_session, prd_factory):
        prd = await prd_factory.create(db_session, word_count=100)
        assert prd.word_count == 100


class TestStructuredSpec:
    """Tests for the StructuredSpec model."""

    @pytest.mark.asyncio
    async def test_create_spec(self, db_session, prd_factory, spec_factory):
        prd = await prd_factory.create(db_session)
        spec = await spec_factory.create(db_session, prd_id=prd.id)
        assert spec.id is not None
        assert spec.prd_id == prd.id
        assert spec.version == 1
        assert spec.status == "draft"

    @pytest.mark.asyncio
    async def test_spec_content_is_json(self, db_session, prd_factory, spec_factory):
        prd = await prd_factory.create(db_session)
        spec = await spec_factory.create(db_session, prd_id=prd.id)
        assert isinstance(spec.content, dict)
        assert "title" in spec.content
        assert "functional_requirements" in spec.content


class TestWorkflowExecution:
    """Tests for WorkflowExecution model."""

    @pytest.mark.asyncio
    async def test_create_workflow(self, db_session, prd_factory, workflow_factory):
        prd = await prd_factory.create(db_session)
        wf = await workflow_factory.create(db_session, prd_id=prd.id)
        assert wf.id is not None
        assert wf.state == "idle"
        assert wf.retry_count == 0

    @pytest.mark.asyncio
    async def test_workflow_state_update(self, db_session, prd_factory, workflow_factory):
        prd = await prd_factory.create(db_session)
        wf = await workflow_factory.create(db_session, prd_id=prd.id)
        wf.state = "spec_generation"
        await db_session.flush()
        assert wf.state == "spec_generation"


class TestCodeArtifact:
    """Tests for CodeArtifact model."""

    @pytest.mark.asyncio
    async def test_create_code_artifact(self, db_session, prd_factory, workflow_factory):
        from models import CodeArtifact
        prd = await prd_factory.create(db_session)
        wf = await workflow_factory.create(db_session, prd_id=prd.id)
        artifact = CodeArtifact(
            workflow_id=wf.id,
            file_path="src/app.py",
            file_name="app.py",
            language="python",
            content="print('hello')",
            line_count=1,
        )
        db_session.add(artifact)
        await db_session.flush()
        assert artifact.id is not None
        assert artifact.line_count == 1


class TestAuditLog:
    """Tests for AuditLog model."""

    @pytest.mark.asyncio
    async def test_create_audit(self, db_session):
        from models import AuditLog, AuditAction
        audit = AuditLog(
            action=AuditAction.CREATE,
            resource_type="test",
            resource_id="test-id",
            details="Test audit entry",
        )
        db_session.add(audit)
        await db_session.flush()
        assert audit.id is not None
        assert audit.action == "create"


class TestHumanReview:
    """Tests for HumanReview model."""

    @pytest.mark.asyncio
    async def test_create_review(self, db_session, prd_factory, workflow_factory):
        from models import HumanReview, ReviewStatus
        prd = await prd_factory.create(db_session)
        wf = await workflow_factory.create(db_session, prd_id=prd.id)
        review = HumanReview(
            workflow_id=wf.id,
            review_type="spec_quality",
            reason="Test escalation",
            status=ReviewStatus.PENDING,
            priority="high",
        )
        db_session.add(review)
        await db_session.flush()
        assert review.id is not None
        assert review.status == "pending"
