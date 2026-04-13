"""
api.py — REST API Layer
========================
Tasks: S-06, D-24, D-25, D-26, D-27, D-28
PRD submission, execution monitoring, artifact retrieval,
human review endpoints, authentication, and rate limiting.
"""

from __future__ import annotations

import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import structlog
from fastapi import (
    FastAPI,
    HTTPException,
    Depends,
    Request,
    Response,
    UploadFile,
    File,
    BackgroundTasks,
    status,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import select, func, desc
from sqlalchemy.ext.asyncio import AsyncSession

from config import get_settings
from database import get_session_dependency
from models import (
    PRD, PRDStatus,
    StructuredSpec,
    WorkflowExecution, WorkflowState,
    AgentExecution,
    CodeArtifact,
    TestArtifact,
    ValidationResult,
    HumanReview, ReviewStatus,
    AuditLog,
)
from observability import TraceStore, get_metrics_output

logger = structlog.get_logger("api")


# ─── Request/Response Models ────────────────────────────────────────────────────

class PRDSubmitRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=500, description="PRD title")
    content: str = Field(..., min_length=10, description="PRD content text")
    metadata: Optional[dict] = Field(default=None, description="Optional source metadata")


class PRDSubmitResponse(BaseModel):
    execution_id: str
    prd_id: str
    status: str
    message: str
    monitor_url: str


class ExecutionStatusResponse(BaseModel):
    id: str
    prd_id: str
    state: str
    started_at: Optional[str]
    completed_at: Optional[str]
    error_message: Optional[str]
    spec_id: Optional[str]
    retry_count: int
    created_at: str


class ExecutionListResponse(BaseModel):
    items: list[ExecutionStatusResponse]
    total: int
    page: int
    limit: int


class ReviewResponse(BaseModel):
    id: str
    workflow_id: str
    review_type: str
    reason: str
    status: str
    priority: str
    context: Optional[dict]
    created_at: str
    resolved_at: Optional[str]
    resolved_by: Optional[str]


class ReviewActionRequest(BaseModel):
    comments: str = Field(..., min_length=1, description="Review comments")
    reviewer: str = Field(default="pilot_user", description="Reviewer identity")


class HealthResponse(BaseModel):
    status: str
    environment: str
    database: str
    mock_mode: bool
    timestamp: str
    version: str = "0.1.0"


class ErrorResponse(BaseModel):
    detail: str
    error_type: str = "api_error"
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


# ─── S-06 + D-28: FastAPI App & Middleware ──────────────────────────────────────

def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    settings = get_settings()

    app = FastAPI(
        title="AI Control Plane — Software Development Factory",
        description=(
            "Semi-Autonomous AI-driven software development orchestrator. "
            "Submit PRDs, monitor execution, retrieve artifacts, and manage human reviews."
        ),
        version="0.1.0",
        docs_url="/docs",
        redoc_url="/redoc",
    )

    # ── CORS Middleware ─────────────────────────────────
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # Restrict in production
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ── Request ID Middleware ───────────────────────────
    @app.middleware("http")
    async def add_request_context(request: Request, call_next):
        request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
        start_time = time.time()

        structlog.contextvars.bind_contextvars(request_id=request_id)

        response = await call_next(request)

        duration_ms = int((time.time() - start_time) * 1000)
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Response-Time-Ms"] = str(duration_ms)

        logger.info(
            "request_completed",
            method=request.method,
            path=request.url.path,
            status=response.status_code,
            duration_ms=duration_ms,
        )

        structlog.contextvars.unbind_contextvars("request_id")
        return response

    # ── Rate Limiting (Simple Token Bucket) ─────────────
    _rate_limits: dict[str, list[float]] = {}

    @app.middleware("http")
    async def rate_limit(request: Request, call_next):
        if request.url.path in ("/docs", "/redoc", "/openapi.json", "/metrics", "/api/v1/health"):
            return await call_next(request)

        client_ip = request.client.host if request.client else "unknown"
        now = time.time()
        window = 60  # 1 minute window

        if client_ip not in _rate_limits:
            _rate_limits[client_ip] = []

        # Clean old entries
        _rate_limits[client_ip] = [t for t in _rate_limits[client_ip] if t > now - window]

        if len(_rate_limits[client_ip]) >= settings.rate_limit_per_minute:
            return JSONResponse(
                status_code=429,
                content={"detail": "Rate limit exceeded"},
                headers={"Retry-After": str(window)},
            )

        _rate_limits[client_ip].append(now)
        return await call_next(request)

    # ── Global Exception Handler ────────────────────────
    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        logger.error(
            "unhandled_exception",
            error=str(exc),
            path=request.url.path,
            method=request.method,
        )
        return JSONResponse(
            status_code=500,
            content=ErrorResponse(
                detail="Internal server error",
                error_type=type(exc).__name__,
            ).model_dump(),
        )

    # ── Register Routes ─────────────────────────────────
    _register_routes(app)

    return app


# ─── Route Registration ─────────────────────────────────────────────────────────

def _register_routes(app: FastAPI):

    # ── D-24: PRD Submission ────────────────────────────

    @app.post(
        "/api/v1/prd",
        response_model=PRDSubmitResponse,
        status_code=status.HTTP_202_ACCEPTED,
        tags=["PRD"],
        summary="Submit a PRD for processing",
    )
    async def submit_prd(
        request: PRDSubmitRequest,
        background_tasks: BackgroundTasks,
        session: AsyncSession = Depends(get_session_dependency),
    ):
        """
        Submit a Product Requirements Document for AI-driven processing.
        Returns immediately with an execution ID for monitoring.
        The workflow runs asynchronously in the background.
        """
        from spec_system import PRDProcessor

        # Ingest PRD
        prd = await PRDProcessor.ingest(
            title=request.title,
            raw_content=request.content,
            session=session,
            source_metadata=request.metadata,
        )

        if prd.status == PRDStatus.REJECTED:
            raise HTTPException(
                status_code=400,
                detail=f"PRD validation failed: {prd.validation_notes}",
            )

        # Create workflow and start async execution
        from orchestrator import WorkflowCoordinator

        workflow = WorkflowExecution(
            prd_id=prd.id,
            state=WorkflowState.IDLE,
            started_at=datetime.now(timezone.utc),
        )
        session.add(workflow)
        await session.flush()

        # Queue async workflow execution
        background_tasks.add_task(_run_workflow, workflow.id, prd.id)

        return PRDSubmitResponse(
            execution_id=workflow.id,
            prd_id=prd.id,
            status="accepted",
            message="PRD submitted successfully. Workflow execution started.",
            monitor_url=f"/api/v1/executions/{workflow.id}",
        )

    # ── D-25: Execution Monitoring ──────────────────────

    @app.get(
        "/api/v1/executions/{execution_id}",
        response_model=ExecutionStatusResponse,
        tags=["Executions"],
        summary="Get execution status",
    )
    async def get_execution(
        execution_id: str,
        session: AsyncSession = Depends(get_session_dependency),
    ):
        """Get the current status and details of a workflow execution."""
        workflow = await session.get(WorkflowExecution, execution_id)
        if not workflow:
            raise HTTPException(status_code=404, detail="Execution not found")

        return ExecutionStatusResponse(
            id=workflow.id,
            prd_id=workflow.prd_id,
            state=workflow.state,
            started_at=workflow.started_at.isoformat() if workflow.started_at else None,
            completed_at=workflow.completed_at.isoformat() if workflow.completed_at else None,
            error_message=workflow.error_message,
            spec_id=workflow.spec_id,
            retry_count=workflow.retry_count,
            created_at=workflow.created_at.isoformat(),
        )

    @app.get(
        "/api/v1/executions",
        response_model=ExecutionListResponse,
        tags=["Executions"],
        summary="List all executions",
    )
    async def list_executions(
        page: int = 1,
        limit: int = 20,
        state: Optional[str] = None,
        session: AsyncSession = Depends(get_session_dependency),
    ):
        """List all workflow executions with pagination and optional filtering."""
        query = select(WorkflowExecution)
        count_query = select(func.count()).select_from(WorkflowExecution)

        if state:
            query = query.where(WorkflowExecution.state == state)
            count_query = count_query.where(WorkflowExecution.state == state)

        total = (await session.execute(count_query)).scalar() or 0

        query = query.order_by(desc(WorkflowExecution.created_at))
        query = query.offset((page - 1) * limit).limit(limit)

        result = await session.execute(query)
        workflows = result.scalars().all()

        return ExecutionListResponse(
            items=[
                ExecutionStatusResponse(
                    id=w.id,
                    prd_id=w.prd_id,
                    state=w.state,
                    started_at=w.started_at.isoformat() if w.started_at else None,
                    completed_at=w.completed_at.isoformat() if w.completed_at else None,
                    error_message=w.error_message,
                    spec_id=w.spec_id,
                    retry_count=w.retry_count,
                    created_at=w.created_at.isoformat(),
                )
                for w in workflows
            ],
            total=total,
            page=page,
            limit=limit,
        )

    @app.get(
        "/api/v1/executions/{execution_id}/trace",
        tags=["Executions"],
        summary="Get execution trace",
    )
    async def get_execution_trace(
        execution_id: str,
        session: AsyncSession = Depends(get_session_dependency),
    ):
        """Get detailed execution trace for debugging and replay."""
        workflow = await session.get(WorkflowExecution, execution_id)
        if not workflow:
            raise HTTPException(status_code=404, detail="Execution not found")

        traces = await TraceStore.get_trace(execution_id, session)
        return {"execution_id": execution_id, "traces": traces, "count": len(traces)}

    # ── D-26: Artifact Retrieval ────────────────────────

    @app.get(
        "/api/v1/executions/{execution_id}/spec",
        tags=["Artifacts"],
        summary="Get generated specification",
    )
    async def get_spec(
        execution_id: str,
        session: AsyncSession = Depends(get_session_dependency),
    ):
        """Retrieve the generated structured specification."""
        workflow = await session.get(WorkflowExecution, execution_id)
        if not workflow:
            raise HTTPException(status_code=404, detail="Execution not found")
        if not workflow.spec_id:
            raise HTTPException(status_code=404, detail="Spec not yet generated")

        spec = await session.get(StructuredSpec, workflow.spec_id)
        if not spec:
            raise HTTPException(status_code=404, detail="Spec not found")

        return {
            "spec_id": spec.id,
            "version": spec.version,
            "status": spec.status,
            "quality_score": spec.quality_score,
            "completeness_score": spec.completeness_score,
            "contradiction_count": spec.contradiction_count,
            "content": spec.content,
            "created_at": spec.created_at.isoformat(),
        }

    @app.get(
        "/api/v1/executions/{execution_id}/code",
        tags=["Artifacts"],
        summary="Get generated code artifacts",
    )
    async def get_code_artifacts(
        execution_id: str,
        session: AsyncSession = Depends(get_session_dependency),
    ):
        """Retrieve all generated code artifacts."""
        result = await session.execute(
            select(CodeArtifact).where(CodeArtifact.workflow_id == execution_id)
        )
        artifacts = result.scalars().all()

        return {
            "execution_id": execution_id,
            "artifacts": [
                {
                    "id": a.id,
                    "file_path": a.file_path,
                    "file_name": a.file_name,
                    "language": a.language,
                    "content": a.content,
                    "line_count": a.line_count,
                    "validation_status": a.validation_status,
                    "created_at": a.created_at.isoformat(),
                }
                for a in artifacts
            ],
            "count": len(artifacts),
        }

    @app.get(
        "/api/v1/executions/{execution_id}/tests",
        tags=["Artifacts"],
        summary="Get generated test artifacts",
    )
    async def get_test_artifacts(
        execution_id: str,
        session: AsyncSession = Depends(get_session_dependency),
    ):
        """Retrieve all generated test artifacts."""
        result = await session.execute(
            select(TestArtifact).where(TestArtifact.workflow_id == execution_id)
        )
        tests = result.scalars().all()

        return {
            "execution_id": execution_id,
            "tests": [
                {
                    "id": t.id,
                    "test_type": t.test_type,
                    "file_name": t.file_name,
                    "content": t.content,
                    "pass_count": t.pass_count,
                    "fail_count": t.fail_count,
                    "coverage_percent": t.coverage_percent,
                    "created_at": t.created_at.isoformat(),
                }
                for t in tests
            ],
            "count": len(tests),
        }

    @app.get(
        "/api/v1/executions/{execution_id}/validation",
        tags=["Artifacts"],
        summary="Get validation results",
    )
    async def get_validation_results(
        execution_id: str,
        session: AsyncSession = Depends(get_session_dependency),
    ):
        """Retrieve validation results for an execution."""
        result = await session.execute(
            select(ValidationResult).where(ValidationResult.workflow_id == execution_id)
        )
        validations = result.scalars().all()

        return {
            "execution_id": execution_id,
            "validations": [
                {
                    "id": v.id,
                    "type": v.validation_type,
                    "gate_name": v.gate_name,
                    "passed": v.passed,
                    "severity": v.severity,
                    "score": v.score,
                    "findings": v.findings,
                    "recommendations": v.recommendations,
                    "created_at": v.created_at.isoformat(),
                }
                for v in validations
            ],
            "count": len(validations),
        }

    # ── D-27: Human Review Endpoints ────────────────────

    @app.get(
        "/api/v1/reviews",
        tags=["Reviews"],
        summary="List pending reviews",
    )
    async def list_reviews(
        status_filter: Optional[str] = None,
        page: int = 1,
        limit: int = 20,
        session: AsyncSession = Depends(get_session_dependency),
    ):
        """List human reviews, optionally filtered by status."""
        query = select(HumanReview)
        if status_filter:
            query = query.where(HumanReview.status == status_filter)
        query = query.order_by(desc(HumanReview.created_at))
        query = query.offset((page - 1) * limit).limit(limit)

        result = await session.execute(query)
        reviews = result.scalars().all()

        return {
            "reviews": [
                ReviewResponse(
                    id=r.id,
                    workflow_id=r.workflow_id,
                    review_type=r.review_type,
                    reason=r.reason,
                    status=r.status,
                    priority=r.priority,
                    context=r.context,
                    created_at=r.created_at.isoformat(),
                    resolved_at=r.resolved_at.isoformat() if r.resolved_at else None,
                    resolved_by=r.resolved_by,
                ).model_dump()
                for r in reviews
            ],
            "count": len(reviews),
        }

    @app.post(
        "/api/v1/reviews/{review_id}/approve",
        tags=["Reviews"],
        summary="Approve a pending review",
    )
    async def approve_review(
        review_id: str,
        action: ReviewActionRequest,
        session: AsyncSession = Depends(get_session_dependency),
    ):
        """Approve a pending human review and resume workflow."""
        from orchestrator import EscalationHandler
        review = await EscalationHandler.approve_review(
            review_id, action.reviewer, action.comments, session
        )
        return {"status": "approved", "review_id": review.id}

    @app.post(
        "/api/v1/reviews/{review_id}/reject",
        tags=["Reviews"],
        summary="Reject a pending review",
    )
    async def reject_review(
        review_id: str,
        action: ReviewActionRequest,
        session: AsyncSession = Depends(get_session_dependency),
    ):
        """Reject a pending human review."""
        from orchestrator import EscalationHandler
        review = await EscalationHandler.reject_review(
            review_id, action.reviewer, action.comments, session
        )
        return {"status": "rejected", "review_id": review.id}

    # ── Operations Endpoints ────────────────────────────

    @app.get("/metrics", tags=["Operations"], summary="Prometheus metrics")
    async def metrics():
        """Prometheus metrics endpoint."""
        output, content_type = get_metrics_output()
        return Response(content=output, media_type=content_type)

    @app.get(
        "/api/v1/health",
        response_model=HealthResponse,
        tags=["Operations"],
        summary="Health check",
    )
    async def health_check(
        session: AsyncSession = Depends(get_session_dependency),
    ):
        """Service health check — validates database connectivity."""
        from database import check_health

        settings = get_settings()
        db_health = await check_health()

        health = HealthResponse(
            status="healthy" if db_health["status"] == "healthy" else "degraded",
            environment=settings.environment.value,
            database=db_health["status"],
            mock_mode=settings.is_mock_mode,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )

        status_code = 200 if health.status == "healthy" else 503
        return JSONResponse(content=health.model_dump(), status_code=status_code)

    @app.post(
        "/api/v1/policies/reload",
        tags=["Operations"],
        summary="Hot-reload policies",
    )
    async def reload_policies():
        """Reload policy configuration from YAML without restart."""
        from config import reload_policies as _reload
        _reload()
        return {"status": "reloaded"}


# ─── Background Workflow Runner ──────────────────────────────────────────────────

async def _run_workflow(workflow_id: str, prd_id: str):
    """Run workflow in background. Uses its own session."""
    from database import get_session
    from orchestrator import WorkflowCoordinator

    async with get_session() as session:
        # Load the existing workflow
        workflow = await session.get(WorkflowExecution, workflow_id)
        if not workflow:
            logger.error("workflow_not_found", workflow_id=workflow_id)
            return

        coordinator = WorkflowCoordinator()

        # Instead of creating a new workflow, execute using the existing one
        try:
            from orchestrator import StateMachine, WorkflowState
            from observability import TraceContext, traced_operation, TraceStore

            trace_ctx = TraceContext(workflow_id=workflow.id)

            # Run the pipeline
            from orchestrator import WORKFLOW_ACTIVE, WORKFLOW_TOTAL
            WORKFLOW_ACTIVE.inc()

            try:
                # Stage 1: Spec Generation
                await StateMachine.transition(
                    workflow, WorkflowState.SPEC_GENERATION, session,
                    reason="Starting spec generation"
                )

                async with traced_operation(trace_ctx, "spec_generator", "generate") as span:
                    from agents import AgentRegistry
                    from models import AgentType
                    spec_agent = AgentRegistry.get(AgentType.SPEC_GENERATOR)
                    spec_result = await spec_agent.execute(
                        {"prd_id": prd_id}, workflow.id, session
                    )
                    span.output_data = spec_result.output_data

                spec_output = spec_result.output_data or {}
                spec_id = spec_output.get("spec_id")
                workflow.spec_id = spec_id

                # Stage 2: Spec Validation
                await StateMachine.transition(
                    workflow, WorkflowState.SPEC_VALIDATION, session,
                    reason="Spec generated, validating"
                )

                # Stage 3: Code Generation
                await StateMachine.transition(
                    workflow, WorkflowState.CODE_GENERATION, session,
                    reason="Spec validated, generating code"
                )

                spec = await session.get(StructuredSpec, spec_id) if spec_id else None
                spec_content = spec.content if spec else {}

                # API Designer
                async with traced_operation(trace_ctx, "api_designer", "design") as span:
                    api_agent = AgentRegistry.get(AgentType.API_DESIGNER)
                    api_result = await api_agent.execute(
                        {"spec_content": spec_content, "workflow_id": workflow.id},
                        workflow.id, session,
                    )
                    span.output_data = api_result.output_data

                api_contract = (api_result.output_data or {}).get("contract", {})

                # Logic Implementer
                async with traced_operation(trace_ctx, "logic_implementer", "implement") as span:
                    logic_agent = AgentRegistry.get(AgentType.LOGIC_IMPLEMENTER)
                    await logic_agent.execute(
                        {"spec_content": spec_content, "api_contract": api_contract, "workflow_id": workflow.id},
                        workflow.id, session,
                    )

                # Test Generator
                async with traced_operation(trace_ctx, "test_generator", "generate_tests") as span:
                    test_agent = AgentRegistry.get(AgentType.TEST_GENERATOR)
                    await test_agent.execute(
                        {"spec_content": spec_content, "code_content": "", "workflow_id": workflow.id},
                        workflow.id, session,
                    )

                # Stage 4: Validation
                await StateMachine.transition(
                    workflow, WorkflowState.CODE_VALIDATION, session,
                    reason="Code generated, validating"
                )

                from validation import ContractValidator
                await ContractValidator.validate_contract(api_contract, workflow.id, session)

                # Stage 5: Testing
                await StateMachine.transition(
                    workflow, WorkflowState.TESTING, session,
                    reason="Running tests"
                )

                # Stage 6: Deployment
                await StateMachine.transition(
                    workflow, WorkflowState.DEPLOYMENT, session,
                    reason="Tests passed, deploying artifacts"
                )

                # Stage 7: Completed
                await StateMachine.transition(
                    workflow, WorkflowState.COMPLETED, session,
                    reason="All stages completed"
                )

                WORKFLOW_TOTAL.labels(status="completed").inc()

            except Exception as e:
                logger.error("workflow_execution_failed", error=str(e), workflow_id=workflow.id)
                try:
                    await StateMachine.transition(
                        workflow, WorkflowState.FAILED, session, reason=str(e)
                    )
                except Exception:
                    workflow.state = WorkflowState.FAILED
                    workflow.error_message = str(e)
                WORKFLOW_TOTAL.labels(status="failed").inc()

            finally:
                WORKFLOW_ACTIVE.dec()
                try:
                    await TraceStore.save_trace(trace_ctx, session)
                except Exception as e:
                    logger.error("trace_save_failed", error=str(e))

        except Exception as e:
            logger.error("background_workflow_error", error=str(e))
