"""
test_observability.py — Unit tests for observability.py
========================================================
Task: V-01
Tests trace context, span lifecycle, trace storage, replay engine, and metrics.
"""

import pytest
from datetime import datetime, timezone


class TestTraceContext:
    """Tests for TraceContext and SpanRecord."""

    def test_create_trace_context(self):
        from observability import TraceContext
        ctx = TraceContext(workflow_id="test-wf-id")
        assert ctx.workflow_id == "test-wf-id"
        assert ctx.trace_id is not None
        assert len(ctx.spans) == 0

    def test_start_span(self):
        from observability import TraceContext
        ctx = TraceContext(workflow_id="wf-1")
        span = ctx.start_span("test_component", "test_event")
        assert span.span_id is not None
        assert span.component == "test_component"
        assert span.event_type == "test_event"
        assert len(ctx.spans) == 1

    def test_end_span(self):
        from observability import TraceContext
        ctx = TraceContext(workflow_id="wf-1")
        span = ctx.start_span("comp", "evt")
        ctx.end_span(span.span_id, output_data={"result": "ok"}, status="success")
        assert span.status == "success"
        assert span.duration_ms is not None
        assert span.duration_ms >= 0
        assert span.output_data == {"result": "ok"}

    def test_end_span_with_error(self):
        from observability import TraceContext
        ctx = TraceContext(workflow_id="wf-1")
        span = ctx.start_span("comp", "evt")
        ctx.end_span(span.span_id, status="error", error="Something broke")
        assert span.status == "error"
        assert span.error == "Something broke"

    def test_end_nonexistent_span(self):
        from observability import TraceContext
        ctx = TraceContext(workflow_id="wf-1")
        # Should not raise, just warn
        ctx.end_span("fake-span-id")

    def test_span_to_dict(self):
        from observability import TraceContext
        ctx = TraceContext(workflow_id="wf-1")
        span = ctx.start_span("comp", "evt", input_data={"x": 1})
        ctx.end_span(span.span_id, output_data={"y": 2})
        d = span.to_dict()
        assert d["component"] == "comp"
        assert d["event_type"] == "evt"
        assert d["input_data"] == {"x": 1}
        assert d["output_data"] == {"y": 2}
        assert d["duration_ms"] is not None

    def test_parent_span(self):
        from observability import TraceContext
        ctx = TraceContext(workflow_id="wf-1")
        parent = ctx.start_span("parent_comp", "parent_evt")
        child = ctx.start_span("child_comp", "child_evt", parent_span_id=parent.span_id)
        assert child.parent_span_id == parent.span_id


class TestTracedOperation:
    """Tests for the traced_operation context manager."""

    @pytest.mark.asyncio
    async def test_traced_operation_success(self):
        from observability import TraceContext, traced_operation
        ctx = TraceContext(workflow_id="wf-1")
        async with traced_operation(ctx, "comp", "op") as span:
            span.output_data = {"done": True}

        assert len(ctx.spans) == 1
        assert ctx.spans[0].status == "success"
        assert ctx.spans[0].output_data == {"done": True}

    @pytest.mark.asyncio
    async def test_traced_operation_error(self):
        from observability import TraceContext, traced_operation
        ctx = TraceContext(workflow_id="wf-1")

        with pytest.raises(ValueError):
            async with traced_operation(ctx, "comp", "op") as span:
                raise ValueError("Test error")

        assert ctx.spans[0].status == "error"
        assert "Test error" in (ctx.spans[0].error or "")


class TestTraceStore:
    """Tests for TraceStore persistence."""

    @pytest.mark.asyncio
    async def test_save_and_get_trace(self, db_session, prd_factory, workflow_factory):
        from observability import TraceContext, TraceStore
        prd = await prd_factory.create(db_session)
        wf = await workflow_factory.create(db_session, prd_id=prd.id)

        ctx = TraceContext(workflow_id=wf.id)
        span = ctx.start_span("test_comp", "test_evt")
        ctx.end_span(span.span_id, output_data={"x": 1})

        await TraceStore.save_trace(ctx, db_session)
        await db_session.flush()

        traces = await TraceStore.get_trace(wf.id, db_session)
        assert len(traces) == 1
        assert traces[0]["component"] == "test_comp"
        assert traces[0]["event_type"] == "test_evt"


class TestReplayEngine:
    """Tests for ReplayEngine divergence detection."""

    def test_detect_no_divergence(self):
        from observability import ReplayEngine
        spans = [
            {"component": "a", "event_type": "x", "output": {"v": 1}},
            {"component": "b", "event_type": "y", "output": {"v": 2}},
        ]
        divergences = ReplayEngine.detect_divergence(spans, spans)
        assert len(divergences) == 0

    def test_detect_missing_span(self):
        from observability import ReplayEngine
        original = [
            {"component": "a", "event_type": "x", "output": {}},
            {"component": "b", "event_type": "y", "output": {}},
        ]
        replay = [
            {"component": "a", "event_type": "x", "output": {}},
        ]
        divergences = ReplayEngine.detect_divergence(original, replay)
        assert any(d["type"] == "missing_span" for d in divergences)

    def test_detect_output_mismatch(self):
        from observability import ReplayEngine
        original = [{"component": "a", "event_type": "x", "output": {"v": 1}}]
        replay = [{"component": "a", "event_type": "x", "output": {"v": 999}}]
        divergences = ReplayEngine.detect_divergence(original, replay)
        assert any(d["type"] == "output_mismatch" for d in divergences)


class TestMetrics:
    """Tests for Prometheus metrics initialization."""

    def test_init_metrics(self):
        from observability import init_metrics
        # Should not raise
        init_metrics()

    def test_get_metrics_output(self):
        from observability import get_metrics_output, init_metrics
        init_metrics()
        output, content_type = get_metrics_output()
        assert isinstance(output, bytes)
        assert len(output) > 0
        assert "text/plain" in content_type or "openmetrics" in content_type
