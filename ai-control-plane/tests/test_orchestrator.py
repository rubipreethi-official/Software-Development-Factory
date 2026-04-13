"""
test_orchestrator.py — Unit tests for orchestrator.py
======================================================
Task: V-01
Tests state machine, policy engine, escalation handler, and reconciliation.
"""

import pytest
from datetime import datetime, timezone, timedelta


class TestStateMachine:
    """Tests for StateMachine transitions."""

    def test_valid_transition_idle_to_spec_gen(self):
        from orchestrator import StateMachine
        from models import WorkflowState
        assert StateMachine.can_transition(WorkflowState.IDLE, WorkflowState.SPEC_GENERATION) is True

    def test_valid_transition_spec_gen_to_validation(self):
        from orchestrator import StateMachine
        from models import WorkflowState
        assert StateMachine.can_transition(WorkflowState.SPEC_GENERATION, WorkflowState.SPEC_VALIDATION) is True

    def test_invalid_transition_idle_to_completed(self):
        from orchestrator import StateMachine
        from models import WorkflowState
        assert StateMachine.can_transition(WorkflowState.IDLE, WorkflowState.COMPLETED) is False

    def test_invalid_transition_completed_to_anything(self):
        from orchestrator import StateMachine
        from models import WorkflowState
        # Completed is terminal — no outgoing transitions
        assert StateMachine.can_transition(WorkflowState.COMPLETED, WorkflowState.IDLE) is False
        assert StateMachine.can_transition(WorkflowState.COMPLETED, WorkflowState.SPEC_GENERATION) is False

    def test_failed_can_restart_to_idle(self):
        from orchestrator import StateMachine
        from models import WorkflowState
        assert StateMachine.can_transition(WorkflowState.FAILED, WorkflowState.IDLE) is True

    @pytest.mark.asyncio
    async def test_transition_updates_state(self, db_session, prd_factory, workflow_factory):
        from orchestrator import StateMachine
        from models import WorkflowState
        prd = await prd_factory.create(db_session)
        wf = await workflow_factory.create(db_session, prd_id=prd.id)

        await StateMachine.transition(
            wf, WorkflowState.SPEC_GENERATION, db_session,
            reason="Test transition"
        )
        assert wf.state == WorkflowState.SPEC_GENERATION

    @pytest.mark.asyncio
    async def test_transition_to_completed_sets_timestamp(self, db_session, prd_factory, workflow_factory):
        from orchestrator import StateMachine
        from models import WorkflowState
        prd = await prd_factory.create(db_session)
        wf = await workflow_factory.create(db_session, prd_id=prd.id)

        # Walk through to COMPLETED
        await StateMachine.transition(wf, WorkflowState.SPEC_GENERATION, db_session)
        await StateMachine.transition(wf, WorkflowState.SPEC_VALIDATION, db_session)
        await StateMachine.transition(wf, WorkflowState.CODE_GENERATION, db_session)
        await StateMachine.transition(wf, WorkflowState.CODE_VALIDATION, db_session)
        await StateMachine.transition(wf, WorkflowState.TESTING, db_session)
        await StateMachine.transition(wf, WorkflowState.DEPLOYMENT, db_session)
        await StateMachine.transition(wf, WorkflowState.COMPLETED, db_session)

        assert wf.completed_at is not None

    @pytest.mark.asyncio
    async def test_invalid_transition_raises(self, db_session, prd_factory, workflow_factory):
        from orchestrator import StateMachine, InvalidTransitionError
        from models import WorkflowState
        prd = await prd_factory.create(db_session)
        wf = await workflow_factory.create(db_session, prd_id=prd.id)

        with pytest.raises(InvalidTransitionError):
            await StateMachine.transition(wf, WorkflowState.COMPLETED, db_session)


class TestPolicyEngine:
    """Tests for PolicyEngine."""

    def test_evaluate_spec_quality_pass(self):
        from orchestrator import PolicyEngine
        engine = PolicyEngine()
        result = engine.evaluate_spec_quality(quality_score=0.9, contradiction_count=0)
        assert result["passed"] is True

    def test_evaluate_spec_quality_fail_low_score(self):
        from orchestrator import PolicyEngine
        engine = PolicyEngine()
        result = engine.evaluate_spec_quality(quality_score=0.1, contradiction_count=0)
        assert result["passed"] is False

    def test_evaluate_spec_quality_fail_contradictions(self):
        from orchestrator import PolicyEngine
        engine = PolicyEngine()
        result = engine.evaluate_spec_quality(quality_score=0.9, contradiction_count=100)
        assert result["passed"] is False

    def test_should_escalate_low_quality(self):
        from orchestrator import PolicyEngine
        engine = PolicyEngine()
        should, reason = engine.should_escalate({"quality_score": 0.1})
        assert should is True
        assert "threshold" in reason.lower() or "quality" in reason.lower()

    def test_should_not_escalate_high_quality(self):
        from orchestrator import PolicyEngine
        engine = PolicyEngine()
        should, _ = engine.should_escalate({"quality_score": 0.95})
        assert should is False


class TestEscalationHandler:
    """Tests for EscalationHandler."""

    @pytest.mark.asyncio
    async def test_create_review(self, db_session, prd_factory, workflow_factory):
        from orchestrator import EscalationHandler
        prd = await prd_factory.create(db_session)
        wf = await workflow_factory.create(db_session, prd_id=prd.id)

        review = await EscalationHandler.create_review(
            workflow_id=wf.id,
            review_type="test_review",
            reason="Test escalation",
            context={"test": True},
            session=db_session,
        )
        assert review.id is not None
        assert review.status == "pending"
        assert review.priority == "medium"

    @pytest.mark.asyncio
    async def test_approve_review(self, db_session, prd_factory, workflow_factory):
        from orchestrator import EscalationHandler
        prd = await prd_factory.create(db_session)
        wf = await workflow_factory.create(db_session, prd_id=prd.id)

        review = await EscalationHandler.create_review(
            wf.id, "test", "reason", {}, db_session
        )
        approved = await EscalationHandler.approve_review(
            review.id, "test_user", "Looks good", db_session
        )
        assert approved.status == "approved"
        assert approved.resolved_by == "test_user"

    @pytest.mark.asyncio
    async def test_reject_review(self, db_session, prd_factory, workflow_factory):
        from orchestrator import EscalationHandler
        prd = await prd_factory.create(db_session)
        wf = await workflow_factory.create(db_session, prd_id=prd.id)

        review = await EscalationHandler.create_review(
            wf.id, "test", "reason", {}, db_session
        )
        rejected = await EscalationHandler.reject_review(
            review.id, "test_user", "Not acceptable", db_session
        )
        assert rejected.status == "rejected"

    @pytest.mark.asyncio
    async def test_approve_nonexistent_raises(self, db_session):
        from orchestrator import EscalationHandler
        with pytest.raises(ValueError, match="not found"):
            await EscalationHandler.approve_review(
                "fake-id", "user", "notes", db_session
            )


class TestReconciliationEngine:
    """Tests for ReconciliationEngine."""

    @pytest.mark.asyncio
    async def test_check_workflow_health_no_issues(self, db_session):
        from orchestrator import ReconciliationEngine
        issues = await ReconciliationEngine.check_workflow_health(db_session)
        assert isinstance(issues, list)

    @pytest.mark.asyncio
    async def test_recover_nonexistent_workflow(self, db_session):
        from orchestrator import ReconciliationEngine
        result = await ReconciliationEngine.recover_workflow("fake-id", db_session)
        assert result["success"] is False
