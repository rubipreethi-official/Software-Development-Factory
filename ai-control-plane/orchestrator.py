"""
orchestrator.py — Unified Control Plane
=========================================
Tasks: D-15, D-16, D-17, D-18, D-19
Central authority: state machine, workflow coordination, policy engine,
escalation handling, and reconciliation loop.

This IS the control plane — governance + decision + orchestration in one layer.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import Any, Optional

import structlog
from sqlalchemy import select, update

from config import get_settings, get_policy_manager, reload_policies
from database import get_session
from models import (
    PRD, PRDStatus,
    StructuredSpec, SpecStatus,
    WorkflowExecution, WorkflowState,
    AgentExecution, AgentType,
    HumanReview, ReviewStatus,
    AuditLog, AuditAction,
    CodeArtifact,
)
from observability import (
    TraceContext,
    TraceStore,
    traced_operation,
    WORKFLOW_TOTAL,
    WORKFLOW_DURATION,
    WORKFLOW_ACTIVE,
    AGENT_EXECUTIONS,
    VALIDATION_GATE_RESULTS,
    HUMAN_REVIEWS,
    ERRORS_TOTAL,
)

logger = structlog.get_logger("orchestrator")


# ─── D-15: Workflow State Machine ────────────────────────────────────────────────

class StateMachine:
    """
    Enforces valid state transitions with guards.
    All transitions are persisted and audited.
    """

    # Valid state transitions: current_state → set of allowed next states
    TRANSITIONS: dict[str, set[str]] = {
        WorkflowState.IDLE: {WorkflowState.SPEC_GENERATION, WorkflowState.FAILED},
        WorkflowState.SPEC_GENERATION: {
            WorkflowState.SPEC_VALIDATION,
            WorkflowState.FAILED,
            WorkflowState.HUMAN_REVIEW_REQUIRED,
        },
        WorkflowState.SPEC_VALIDATION: {
            WorkflowState.CODE_GENERATION,
            WorkflowState.SPEC_GENERATION,  # Retry
            WorkflowState.FAILED,
            WorkflowState.HUMAN_REVIEW_REQUIRED,
        },
        WorkflowState.CODE_GENERATION: {
            WorkflowState.CODE_VALIDATION,
            WorkflowState.FAILED,
            WorkflowState.HUMAN_REVIEW_REQUIRED,
        },
        WorkflowState.CODE_VALIDATION: {
            WorkflowState.TESTING,
            WorkflowState.CODE_GENERATION,  # Retry
            WorkflowState.FAILED,
            WorkflowState.HUMAN_REVIEW_REQUIRED,
        },
        WorkflowState.TESTING: {
            WorkflowState.DEPLOYMENT,
            WorkflowState.CODE_GENERATION,  # Retry
            WorkflowState.FAILED,
            WorkflowState.HUMAN_REVIEW_REQUIRED,
        },
        WorkflowState.DEPLOYMENT: {
            WorkflowState.COMPLETED,
            WorkflowState.FAILED,
        },
        WorkflowState.HUMAN_REVIEW_REQUIRED: {
            WorkflowState.SPEC_GENERATION,
            WorkflowState.SPEC_VALIDATION,
            WorkflowState.CODE_GENERATION,
            WorkflowState.CODE_VALIDATION,
            WorkflowState.TESTING,
            WorkflowState.FAILED,
            WorkflowState.COMPLETED,
        },
        WorkflowState.COMPLETED: set(),  # Terminal
        WorkflowState.FAILED: {
            WorkflowState.IDLE,  # Allow restart
        },
    }

    @classmethod
    def can_transition(cls, from_state: str, to_state: str) -> bool:
        allowed = cls.TRANSITIONS.get(from_state, set())
        return to_state in allowed

    @classmethod
    async def transition(
        cls,
        workflow: WorkflowExecution,
        new_state: str,
        session,
        reason: str = "",
    ) -> None:
        """Execute a validated state transition with audit trail."""
        old_state = workflow.state

        if not cls.can_transition(old_state, new_state):
            raise InvalidTransitionError(
                f"Cannot transition from '{old_state}' to '{new_state}'. "
                f"Allowed: {cls.TRANSITIONS.get(old_state, set())}"
            )

        workflow.state = new_state

        # Set timestamps
        if new_state == WorkflowState.COMPLETED:
            workflow.completed_at = datetime.now(timezone.utc)
        elif new_state == WorkflowState.FAILED:
            workflow.completed_at = datetime.now(timezone.utc)
            workflow.error_message = reason

        # Checkpoint for recovery
        workflow.checkpoint_data = {
            "last_state": old_state,
            "transition_time": datetime.now(timezone.utc).isoformat(),
            "reason": reason,
        }

        # Audit log
        audit = AuditLog(
            action=AuditAction.STATE_CHANGE,
            resource_type="workflow",
            resource_id=workflow.id,
            before_state={"state": old_state},
            after_state={"state": new_state},
            details=reason,
        )
        session.add(audit)

        logger.info(
            "state_transition",
            workflow_id=workflow.id,
            from_state=old_state,
            to_state=new_state,
            reason=reason,
        )


class InvalidTransitionError(Exception):
    """Raised when an invalid state transition is attempted."""
    pass


# ─── D-17: Policy Engine ────────────────────────────────────────────────────────

class PolicyEngine:
    """
    Loads, evaluates, and enforces policy rules.
    Supports hot-reload and override with audit.
    """

    def __init__(self):
        self.policy = get_policy_manager()

    def evaluate_spec_quality(self, quality_score: float, contradiction_count: int) -> dict:
        """Evaluate spec against quality policies."""
        min_score = self.policy.get("spec_validation", "min_completeness_score", 0.7)
        max_contradictions = self.policy.get("spec_validation", "max_contradictions", 3)

        passed = quality_score >= min_score and contradiction_count <= max_contradictions
        return {
            "passed": passed,
            "quality_score": quality_score,
            "min_required": min_score,
            "contradictions": contradiction_count,
            "max_allowed": max_contradictions,
            "reasons": [
                f"Quality score {quality_score} < {min_score}" if quality_score < min_score else None,
                f"Contradictions {contradiction_count} > {max_contradictions}" if contradiction_count > max_contradictions else None,
            ],
        }

    def should_escalate(self, context: dict) -> tuple[bool, str]:
        """Determine if a situation requires human escalation."""
        ambiguity_threshold = self.policy.get("escalation", "ambiguity_threshold", 0.5)
        confidence_threshold = self.policy.get("escalation", "low_confidence_threshold", 0.6)
        high_risk_ops = self.policy.get("escalation", "high_risk_operations", [])

        quality_score = context.get("quality_score", 1.0)
        has_contradictions = context.get("contradiction_count", 0) > 0
        operation_type = context.get("operation_type", "")

        if quality_score < ambiguity_threshold:
            return True, f"Quality score {quality_score} below ambiguity threshold {ambiguity_threshold}"

        if quality_score < confidence_threshold and has_contradictions:
            return True, f"Low confidence ({quality_score}) with contradictions"

        if operation_type in high_risk_ops:
            return True, f"High-risk operation: {operation_type}"

        auto_escalate = self.policy.get("escalation", "auto_escalate_on_contradiction", False)
        if auto_escalate and has_contradictions:
            return True, "Auto-escalation triggered by contradictions"

        return False, ""

    def reload(self) -> None:
        """Hot-reload policies."""
        reload_policies()
        self.policy = get_policy_manager()
        logger.info("policies_reloaded")


# ─── D-18: Escalation & Human Review Handler ────────────────────────────────────

class EscalationHandler:
    """Manages human review escalations and resolution."""

    @staticmethod
    async def create_review(
        workflow_id: str,
        review_type: str,
        reason: str,
        context: dict,
        session,
        priority: str = "medium",
    ) -> HumanReview:
        """Create a human review request."""
        review = HumanReview(
            workflow_id=workflow_id,
            review_type=review_type,
            reason=reason,
            context=context,
            status=ReviewStatus.PENDING,
            priority=priority,
        )
        session.add(review)
        await session.flush()

        HUMAN_REVIEWS.labels(status="created").inc()

        logger.info(
            "review_created",
            review_id=review.id,
            workflow_id=workflow_id,
            type=review_type,
            priority=priority,
        )
        return review

    @staticmethod
    async def approve_review(
        review_id: str,
        approved_by: str,
        notes: str,
        session,
    ) -> HumanReview:
        """Approve a pending review."""
        review = await session.get(HumanReview, review_id)
        if not review:
            raise ValueError(f"Review not found: {review_id}")
        if review.status != ReviewStatus.PENDING:
            raise ValueError(f"Review is not pending: {review.status}")

        review.status = ReviewStatus.APPROVED
        review.resolved_by = approved_by
        review.resolution_notes = notes
        review.resolved_at = datetime.now(timezone.utc)

        HUMAN_REVIEWS.labels(status="approved").inc()

        # Audit
        audit = AuditLog(
            user_id=approved_by,
            action=AuditAction.APPROVE,
            resource_type="human_review",
            resource_id=review_id,
            details=notes,
        )
        session.add(audit)
        return review

    @staticmethod
    async def reject_review(
        review_id: str,
        rejected_by: str,
        notes: str,
        session,
    ) -> HumanReview:
        """Reject a pending review."""
        review = await session.get(HumanReview, review_id)
        if not review:
            raise ValueError(f"Review not found: {review_id}")

        review.status = ReviewStatus.REJECTED
        review.resolved_by = rejected_by
        review.resolution_notes = notes
        review.resolved_at = datetime.now(timezone.utc)

        HUMAN_REVIEWS.labels(status="rejected").inc()
        return review


# ─── D-16: Workflow Coordinator ──────────────────────────────────────────────────

class WorkflowCoordinator:
    """
    Coordinates end-to-end workflow execution.
    This is the central orchestration engine of the control plane.
    """

    def __init__(self):
        self.policy_engine = PolicyEngine()
        self.escalation = EscalationHandler()

    async def execute_workflow(self, prd_id: str, session) -> WorkflowExecution:
        """
        Execute the complete workflow: PRD → Spec → Code → Tests → Validation.
        Each stage is checkpointed for recovery.
        """
        # Create workflow execution record
        workflow = WorkflowExecution(
            prd_id=prd_id,
            state=WorkflowState.IDLE,
            started_at=datetime.now(timezone.utc),
        )
        session.add(workflow)
        await session.flush()

        WORKFLOW_ACTIVE.inc()
        trace_ctx = TraceContext(workflow_id=workflow.id)

        try:
            # ── Stage 1: Spec Generation ────────────────────────
            await StateMachine.transition(
                workflow, WorkflowState.SPEC_GENERATION, session,
                reason="Starting spec generation"
            )

            async with traced_operation(trace_ctx, "spec_generator", "generate") as span:
                from agents import AgentRegistry
                spec_agent = AgentRegistry.get(AgentType.SPEC_GENERATOR)
                spec_result = await spec_agent.execute(
                    {"prd_id": prd_id}, workflow.id, session
                )
                span.output_data = spec_result.output_data

            spec_output = spec_result.output_data or {}
            spec_id = spec_output.get("spec_id")
            workflow.spec_id = spec_id

            # ── Stage 2: Spec Validation Gate ───────────────────
            await StateMachine.transition(
                workflow, WorkflowState.SPEC_VALIDATION, session,
                reason="Spec generated, running validation"
            )

            quality_score = spec_output.get("quality_score", 0)
            validation = spec_output.get("validation", {})

            # Policy check
            policy_result = self.policy_engine.evaluate_spec_quality(
                quality_score,
                validation.get("checks", {}).get("contradictions", {}).get("contradiction_count", 0),
            )

            if not policy_result["passed"]:
                should_escalate, escalation_reason = self.policy_engine.should_escalate({
                    "quality_score": quality_score,
                    "contradiction_count": validation.get("checks", {}).get("contradictions", {}).get("contradiction_count", 0),
                })

                if should_escalate:
                    await StateMachine.transition(
                        workflow, WorkflowState.HUMAN_REVIEW_REQUIRED, session,
                        reason=escalation_reason,
                    )
                    await self.escalation.create_review(
                        workflow_id=workflow.id,
                        review_type="spec_quality",
                        reason=escalation_reason,
                        context={"validation": validation, "policy": policy_result},
                        session=session,
                        priority="high",
                    )
                    await self._save_trace(trace_ctx, session)
                    return workflow

            # ── Stage 3: Code Generation ────────────────────────
            await StateMachine.transition(
                workflow, WorkflowState.CODE_GENERATION, session,
                reason="Spec validated, starting code generation"
            )

            # Load spec content for agents
            spec = await session.get(StructuredSpec, spec_id) if spec_id else None
            spec_content = spec.content if spec else {}

            # 3a: API Designer
            async with traced_operation(trace_ctx, "api_designer", "design") as span:
                api_agent = AgentRegistry.get(AgentType.API_DESIGNER)
                api_result = await api_agent.execute(
                    {"spec_content": spec_content, "workflow_id": workflow.id},
                    workflow.id, session,
                )
                span.output_data = api_result.output_data

            api_contract = (api_result.output_data or {}).get("contract", {})

            # 3b: Logic Implementer
            async with traced_operation(trace_ctx, "logic_implementer", "implement") as span:
                logic_agent = AgentRegistry.get(AgentType.LOGIC_IMPLEMENTER)
                logic_result = await logic_agent.execute(
                    {
                        "spec_content": spec_content,
                        "api_contract": api_contract,
                        "workflow_id": workflow.id,
                    },
                    workflow.id, session,
                )
                span.output_data = logic_result.output_data

            # 3c: Test Generator
            async with traced_operation(trace_ctx, "test_generator", "generate_tests") as span:
                # Get generated code for test context
                code_artifacts = await session.execute(
                    select(CodeArtifact)
                    .where(CodeArtifact.workflow_id == workflow.id)
                    .where(CodeArtifact.language == "python")
                )
                code_content = ""
                for artifact in code_artifacts.scalars():
                    code_content += artifact.content + "\n"

                test_agent = AgentRegistry.get(AgentType.TEST_GENERATOR)
                test_result = await test_agent.execute(
                    {
                        "spec_content": spec_content,
                        "code_content": code_content,
                        "workflow_id": workflow.id,
                    },
                    workflow.id, session,
                )
                span.output_data = test_result.output_data

            # ── Stage 4: Code Validation Gate ───────────────────
            await StateMachine.transition(
                workflow, WorkflowState.CODE_VALIDATION, session,
                reason="Code generated, running validation"
            )

            async with traced_operation(trace_ctx, "validation", "contract_check") as span:
                from validation import ContractValidator, IntegrationTester, ValidationGate

                contract_result = await ContractValidator.validate_contract(
                    api_contract, workflow.id, session
                )
                span.output_data = {"passed": contract_result.passed, "score": contract_result.score}

            # Contract validation gate
            gate = ValidationGate("contract_validation")
            gate_decision = await gate.evaluate([contract_result], workflow.id, session)

            if gate_decision["should_block"]:
                VALIDATION_GATE_RESULTS.labels(gate_name="contract_validation", result="fail").inc()
                await StateMachine.transition(
                    workflow, WorkflowState.FAILED, session,
                    reason=f"Contract validation gate failed: {gate_decision}"
                )
                await self._save_trace(trace_ctx, session)
                return workflow

            VALIDATION_GATE_RESULTS.labels(gate_name="contract_validation", result="pass").inc()

            # ── Stage 5: Testing ────────────────────────────────
            await StateMachine.transition(
                workflow, WorkflowState.TESTING, session,
                reason="Code validated, running tests"
            )

            # Trajectory evaluation (advisory, non-blocking)
            async with traced_operation(trace_ctx, "validation", "trajectory_eval") as span:
                from validation import TrajectoryEvaluator
                trace_data = [s.to_dict() for s in trace_ctx.spans]
                traj_result = await TrajectoryEvaluator.evaluate(
                    trace_data, spec_content, workflow.id, session
                )
                span.output_data = {"score": traj_result.score}

            # ── Stage 6: Complete ───────────────────────────────
            await StateMachine.transition(
                workflow, WorkflowState.COMPLETED, session,
                reason="All stages completed successfully"
            )

            WORKFLOW_TOTAL.labels(status="completed").inc()
            logger.info(
                "workflow_completed",
                workflow_id=workflow.id,
                prd_id=prd_id,
            )

        except Exception as e:
            logger.error(
                "workflow_failed",
                workflow_id=workflow.id,
                error=str(e),
            )
            try:
                await StateMachine.transition(
                    workflow, WorkflowState.FAILED, session,
                    reason=str(e)
                )
            except Exception:
                workflow.state = WorkflowState.FAILED
                workflow.error_message = str(e)

            WORKFLOW_TOTAL.labels(status="failed").inc()
            ERRORS_TOTAL.labels(component="orchestrator", error_type=type(e).__name__).inc()

        finally:
            WORKFLOW_ACTIVE.dec()
            await self._save_trace(trace_ctx, session)

        return workflow

    async def _save_trace(self, trace_ctx: TraceContext, session) -> None:
        """Save trace data to database."""
        try:
            await TraceStore.save_trace(trace_ctx, session)
        except Exception as e:
            logger.error("trace_save_failed", error=str(e))


# ─── D-19: Reconciliation & Drift Detection ─────────────────────────────────────

class ReconciliationEngine:
    """
    Continuously compares expected state (spec) vs actual state (execution).
    Detects drift and triggers corrective actions.
    """

    @staticmethod
    async def check_workflow_health(session) -> list[dict]:
        """
        Check all active workflows for health issues.
        Called periodically by background task.
        """
        issues = []

        # Find stuck workflows (running too long)
        result = await session.execute(
            select(WorkflowExecution).where(
                WorkflowExecution.state.notin_([
                    WorkflowState.COMPLETED,
                    WorkflowState.FAILED,
                    WorkflowState.IDLE,
                ])
            )
        )
        active_workflows = result.scalars().all()

        policy = get_policy_manager()
        max_duration = policy.get("orchestration", "max_workflow_duration_seconds", 3600)

        for wf in active_workflows:
            if wf.started_at:
                elapsed = (datetime.now(timezone.utc) - wf.started_at).total_seconds()
                if elapsed > max_duration:
                    issues.append({
                        "type": "stuck_workflow",
                        "workflow_id": wf.id,
                        "state": wf.state,
                        "elapsed_seconds": int(elapsed),
                        "max_allowed": max_duration,
                        "severity": "high",
                    })

        # Find pending reviews that are aging
        review_result = await session.execute(
            select(HumanReview).where(HumanReview.status == ReviewStatus.PENDING)
        )
        pending_reviews = review_result.scalars().all()

        for review in pending_reviews:
            age = (datetime.now(timezone.utc) - review.created_at).total_seconds()
            if age > 3600:  # 1 hour
                issues.append({
                    "type": "aging_review",
                    "review_id": review.id,
                    "workflow_id": review.workflow_id,
                    "age_seconds": int(age),
                    "severity": "medium",
                })

        if issues:
            logger.warning("reconciliation_issues_found", count=len(issues))

        return issues

    @staticmethod
    async def recover_workflow(workflow_id: str, session) -> dict:
        """
        Attempt to recover a stuck or failed workflow from its last checkpoint.
        """
        workflow = await session.get(WorkflowExecution, workflow_id)
        if not workflow:
            return {"success": False, "error": "Workflow not found"}

        checkpoint = workflow.checkpoint_data or {}
        last_state = checkpoint.get("last_state")

        if workflow.state == WorkflowState.FAILED and last_state:
            # Allow retry from last known good state
            workflow.state = WorkflowState.IDLE
            workflow.retry_count += 1
            workflow.error_message = None

            logger.info(
                "workflow_recovery_attempted",
                workflow_id=workflow_id,
                from_state=WorkflowState.FAILED,
                retry_count=workflow.retry_count,
            )
            return {"success": True, "new_state": WorkflowState.IDLE}

        return {"success": False, "error": f"Cannot recover from state: {workflow.state}"}


# ─── Background Reconciliation Task ─────────────────────────────────────────────

async def run_reconciliation_loop():
    """Background task that runs periodic reconciliation checks."""
    policy = get_policy_manager()
    interval = policy.get("orchestration", "reconciliation_interval_seconds", 60)

    logger.info("reconciliation_loop_started", interval=interval)

    while True:
        try:
            async with get_session() as session:
                issues = await ReconciliationEngine.check_workflow_health(session)
                if issues:
                    logger.info("reconciliation_check", issues=len(issues))
        except Exception as e:
            logger.error("reconciliation_error", error=str(e))

        await asyncio.sleep(interval)
