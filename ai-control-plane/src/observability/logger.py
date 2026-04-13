"""
observability.py — Tracing, Logging, Metrics & Replay Engine
=============================================================
Tasks: S-05, D-20, D-21, D-22, D-23
Provides structured logging configuration, distributed trace context,
event collection, Prometheus metrics, and deterministic replay.
"""

from __future__ import annotations

import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, AsyncGenerator, Optional

import structlog
from prometheus_client import (
    Counter,
    Gauge,
    Histogram,
    Info,
    generate_latest,
    CONTENT_TYPE_LATEST,
)
from sqlalchemy import select, desc

from config import get_settings


# ─── S-05: Structured Logging Configuration ─────────────────────────────────────

def configure_logging() -> None:
    """
    Configure structlog with JSON output for production,
    colored console output for development.
    """
    settings = get_settings()

    shared_processors = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.UnicodeDecoder(),
    ]

    if settings.is_production:
        renderer = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer(colors=True)

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    import logging

    formatter = structlog.stdlib.ProcessorFormatter(
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
    )

    handler = logging.StreamHandler()
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(getattr(logging, settings.log_level))

    # Quiet noisy libraries
    for lib in ("uvicorn.access", "sqlalchemy.engine", "httpx", "httpcore"):
        logging.getLogger(lib).setLevel(logging.WARNING)


logger = structlog.get_logger("observability")


# ─── D-20: Trace Context Management ─────────────────────────────────────────────

class TraceContext:
    """
    Manages distributed trace context for a single workflow execution.
    Thread-safe via structlog contextvars.
    """

    def __init__(
        self,
        workflow_id: str,
        trace_id: str | None = None,
    ):
        self.workflow_id = workflow_id
        self.trace_id = trace_id or str(uuid.uuid4())
        self.spans: list[SpanRecord] = []
        self._active_spans: dict[str, SpanRecord] = {}

    def start_span(
        self,
        component: str,
        event_type: str,
        parent_span_id: str | None = None,
        input_data: dict | None = None,
    ) -> "SpanRecord":
        """Start a new span within this trace."""
        span = SpanRecord(
            span_id=str(uuid.uuid4()),
            trace_id=self.trace_id,
            workflow_id=self.workflow_id,
            parent_span_id=parent_span_id,
            component=component,
            event_type=event_type,
            start_time=datetime.now(timezone.utc),
            input_data=input_data,
        )
        self._active_spans[span.span_id] = span
        self.spans.append(span)

        logger.debug(
            "span_started",
            trace_id=self.trace_id,
            span_id=span.span_id,
            component=component,
            event_type=event_type,
        )
        return span

    def end_span(
        self,
        span_id: str,
        output_data: dict | None = None,
        status: str = "success",
        error: str | None = None,
    ) -> None:
        """Complete a span with output data."""
        span = self._active_spans.pop(span_id, None)
        if span is None:
            logger.warning("span_not_found", span_id=span_id)
            return

        span.end_time = datetime.now(timezone.utc)
        span.duration_ms = int(
            (span.end_time - span.start_time).total_seconds() * 1000
        )
        span.output_data = output_data
        span.status = status
        span.error = error

        logger.debug(
            "span_ended",
            trace_id=self.trace_id,
            span_id=span_id,
            status=status,
            duration_ms=span.duration_ms,
        )


class SpanRecord:
    """A single span within a trace."""

    def __init__(
        self,
        span_id: str,
        trace_id: str,
        workflow_id: str,
        parent_span_id: str | None,
        component: str,
        event_type: str,
        start_time: datetime,
        input_data: dict | None = None,
    ):
        self.span_id = span_id
        self.trace_id = trace_id
        self.workflow_id = workflow_id
        self.parent_span_id = parent_span_id
        self.component = component
        self.event_type = event_type
        self.start_time = start_time
        self.end_time: datetime | None = None
        self.duration_ms: int | None = None
        self.input_data = input_data
        self.output_data: dict | None = None
        self.status: str | None = None
        self.error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "span_id": self.span_id,
            "trace_id": self.trace_id,
            "workflow_id": self.workflow_id,
            "parent_span_id": self.parent_span_id,
            "component": self.component,
            "event_type": self.event_type,
            "start_time": self.start_time.isoformat(),
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "duration_ms": self.duration_ms,
            "status": self.status,
            "error": self.error,
            "input_data": self.input_data,
            "output_data": self.output_data,
        }


@asynccontextmanager
async def traced_operation(
    trace_ctx: TraceContext,
    component: str,
    event_type: str,
    parent_span_id: str | None = None,
    input_data: dict | None = None,
) -> AsyncGenerator[SpanRecord, None]:
    """
    Context manager that automatically tracks a span.

    Usage:
        async with traced_operation(ctx, "spec_system", "generate") as span:
            result = await generate_spec(...)
            span.output_data = {"spec_id": result.id}
    """
    span = trace_ctx.start_span(component, event_type, parent_span_id, input_data)
    try:
        yield span
        trace_ctx.end_span(span.span_id, span.output_data, "success")
    except Exception as e:
        trace_ctx.end_span(span.span_id, None, "error", str(e))
        raise


# ─── D-21: Trace Storage ────────────────────────────────────────────────────────

class TraceStore:
    """
    Persists trace data to the database for querying and replay.
    """

    @staticmethod
    async def save_trace(trace_ctx: TraceContext, session) -> None:
        """Persist all spans from a trace context to the database."""
        from models import ExecutionTrace

        for span in trace_ctx.spans:
            record = ExecutionTrace(
                workflow_id=span.workflow_id,
                trace_id=span.trace_id,
                parent_span_id=span.parent_span_id,
                span_id=span.span_id,
                event_type=span.event_type,
                component=span.component,
                timestamp=span.start_time,
                input_snapshot=span.input_data,
                output_snapshot=span.output_data,
                duration_ms=span.duration_ms,
                status=span.status,
                metadata_={"error": span.error} if span.error else None,
            )
            session.add(record)

        logger.info(
            "trace_saved",
            trace_id=trace_ctx.trace_id,
            span_count=len(trace_ctx.spans),
        )

    @staticmethod
    async def get_trace(workflow_id: str, session) -> list[dict]:
        """Retrieve all trace events for a workflow."""
        from models import ExecutionTrace

        result = await session.execute(
            select(ExecutionTrace)
            .where(ExecutionTrace.workflow_id == workflow_id)
            .order_by(ExecutionTrace.timestamp)
        )
        traces = result.scalars().all()
        return [
            {
                "id": t.id,
                "trace_id": t.trace_id,
                "span_id": t.span_id,
                "parent_span_id": t.parent_span_id,
                "event_type": t.event_type,
                "component": t.component,
                "timestamp": t.timestamp.isoformat(),
                "duration_ms": t.duration_ms,
                "status": t.status,
                "input": t.input_snapshot,
                "output": t.output_snapshot,
            }
            for t in traces
        ]


# ─── D-22: Replay Engine ────────────────────────────────────────────────────────

class ReplayEngine:
    """
    Deterministic replay: reload a trace and compare re-execution
    results to detect non-determinism or regressions.
    """

    @staticmethod
    async def load_replay_data(workflow_id: str, session) -> dict:
        """Load full trace data needed for replay."""
        trace_data = await TraceStore.get_trace(workflow_id, session)
        return {
            "workflow_id": workflow_id,
            "spans": trace_data,
            "span_count": len(trace_data),
        }

    @staticmethod
    def detect_divergence(
        original_spans: list[dict],
        replay_spans: list[dict],
    ) -> list[dict]:
        """
        Compare original and replayed spans to find divergences.
        Returns list of divergence records.
        """
        divergences = []

        orig_by_component = {
            (s["component"], s["event_type"]): s for s in original_spans
        }
        replay_by_component = {
            (s["component"], s["event_type"]): s for s in replay_spans
        }

        # Check for missing spans
        for key in orig_by_component:
            if key not in replay_by_component:
                divergences.append({
                    "type": "missing_span",
                    "component": key[0],
                    "event_type": key[1],
                    "severity": "high",
                })

        # Check for output differences
        for key, orig in orig_by_component.items():
            replay = replay_by_component.get(key)
            if replay and orig.get("output") != replay.get("output"):
                divergences.append({
                    "type": "output_mismatch",
                    "component": key[0],
                    "event_type": key[1],
                    "original_output": orig.get("output"),
                    "replay_output": replay.get("output"),
                    "severity": "medium",
                })

        return divergences


# ─── D-23: Prometheus Metrics ────────────────────────────────────────────────────

# System info
SYSTEM_INFO = Info("ai_control_plane", "AI Control Plane system information")

# Workflow metrics
WORKFLOW_TOTAL = Counter(
    "workflows_total",
    "Total workflow executions",
    ["status"],
)
WORKFLOW_DURATION = Histogram(
    "workflow_duration_seconds",
    "Workflow execution duration in seconds",
    ["state"],
    buckets=[1, 5, 10, 30, 60, 120, 300, 600, 1800, 3600],
)
WORKFLOW_ACTIVE = Gauge(
    "workflows_active",
    "Currently active workflows",
)

# Agent metrics
AGENT_EXECUTIONS = Counter(
    "agent_executions_total",
    "Total agent executions",
    ["agent_type", "status"],
)
AGENT_DURATION = Histogram(
    "agent_duration_seconds",
    "Agent execution duration in seconds",
    ["agent_type"],
)
AGENT_TOKEN_USAGE = Counter(
    "agent_tokens_total",
    "Total LLM tokens consumed",
    ["agent_type", "token_type"],  # token_type: input, output
)

# Validation metrics
VALIDATION_GATE_RESULTS = Counter(
    "validation_gate_results_total",
    "Validation gate results",
    ["gate_name", "result"],  # result: pass, fail, override
)

# Spec metrics
SPEC_QUALITY_SCORES = Histogram(
    "spec_quality_score",
    "Spec quality scores distribution",
    buckets=[0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0],
)

# Human review metrics
HUMAN_REVIEWS = Counter(
    "human_reviews_total",
    "Total human reviews",
    ["status"],
)

# Error metrics
ERRORS_TOTAL = Counter(
    "errors_total",
    "Total errors by component",
    ["component", "error_type"],
)


def init_metrics() -> None:
    """Initialize system info metrics."""
    settings = get_settings()
    SYSTEM_INFO.info({
        "version": "0.1.0",
        "environment": settings.environment.value,
        "claude_model": settings.claude_model,
        "mock_mode": str(settings.is_mock_mode),
    })


def get_metrics_output() -> tuple[bytes, str]:
    """Get Prometheus metrics output for /metrics endpoint."""
    return generate_latest(), CONTENT_TYPE_LATEST
