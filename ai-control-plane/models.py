"""
models.py — SQLAlchemy ORM Models
==================================
Task: D-01
Defines all persistent entities: PRDs, Specs, Executions, Artifacts, and Audit logs.
Every model has full traceability via foreign keys and UUID identifiers.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum as PyEnum
from typing import Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    JSON,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base, TimestampMixin


# ─── Helper ─────────────────────────────────────────────────────────────────────

def _uuid() -> str:
    return str(uuid.uuid4())


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ─── Enumerations ───────────────────────────────────────────────────────────────

class PRDStatus(str, PyEnum):
    SUBMITTED = "submitted"
    PREPROCESSING = "preprocessing"
    VALIDATED = "validated"
    REJECTED = "rejected"
    PROCESSING = "processing"
    COMPLETED = "completed"


class SpecStatus(str, PyEnum):
    DRAFT = "draft"
    VALIDATED = "validated"
    APPROVED = "approved"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"


class WorkflowState(str, PyEnum):
    IDLE = "idle"
    SPEC_GENERATION = "spec_generation"
    SPEC_VALIDATION = "spec_validation"
    CODE_GENERATION = "code_generation"
    CODE_VALIDATION = "code_validation"
    TESTING = "testing"
    DEPLOYMENT = "deployment"
    COMPLETED = "completed"
    FAILED = "failed"
    HUMAN_REVIEW_REQUIRED = "human_review_required"


class AgentType(str, PyEnum):
    API_DESIGNER = "api_designer"
    LOGIC_IMPLEMENTER = "logic_implementer"
    TEST_GENERATOR = "test_generator"
    SPEC_GENERATOR = "spec_generator"


class ValidationSeverity(str, PyEnum):
    BLOCKING = "blocking"
    WARNING = "warning"
    INFO = "info"


class ReviewStatus(str, PyEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class AuditAction(str, PyEnum):
    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"
    APPROVE = "approve"
    REJECT = "reject"
    OVERRIDE = "override"
    ESCALATE = "escalate"
    STATE_CHANGE = "state_change"


# ─── Spec Models ────────────────────────────────────────────────────────────────

class PRD(Base, TimestampMixin):
    """Raw Product Requirements Document as submitted by user."""

    __tablename__ = "prds"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    raw_content: Mapped[str] = mapped_column(Text, nullable=False)
    source_metadata: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), default=PRDStatus.SUBMITTED, nullable=False, index=True
    )
    word_count: Mapped[int] = mapped_column(Integer, default=0)
    validation_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Relationships
    specs: Mapped[list["StructuredSpec"]] = relationship(back_populates="prd", cascade="all, delete-orphan")
    workflow_executions: Mapped[list["WorkflowExecution"]] = relationship(back_populates="prd")

    __table_args__ = (
        Index("ix_prds_status_created", "status", "created_at"),
    )


class StructuredSpec(Base, TimestampMixin):
    """AI-generated structured specification from a PRD."""

    __tablename__ = "structured_specs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    prd_id: Mapped[str] = mapped_column(ForeignKey("prds.id"), nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    content: Mapped[dict] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), default=SpecStatus.DRAFT, nullable=False, index=True
    )

    # Validation scores
    completeness_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    quality_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    contradiction_count: Mapped[int] = mapped_column(Integer, default=0)
    contradiction_details: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    # Human review
    human_review_required: Mapped[bool] = mapped_column(Boolean, default=False)
    human_review_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Relationships
    prd: Mapped["PRD"] = relationship(back_populates="specs")
    requirements: Mapped[list["SpecRequirement"]] = relationship(
        back_populates="spec", cascade="all, delete-orphan"
    )
    api_contracts: Mapped[list["APIContract"]] = relationship(
        back_populates="spec", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_specs_prd_version", "prd_id", "version", unique=True),
    )


class SpecRequirement(Base, TimestampMixin):
    """Individual requirement extracted from a structured spec."""

    __tablename__ = "spec_requirements"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    spec_id: Mapped[str] = mapped_column(ForeignKey("structured_specs.id"), nullable=False, index=True)
    requirement_id: Mapped[str] = mapped_column(String(50), nullable=False)  # e.g., "REQ-001"
    description: Mapped[str] = mapped_column(Text, nullable=False)
    priority: Mapped[str] = mapped_column(String(20), default="medium")  # high, medium, low
    acceptance_criteria: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    parent_requirement_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("spec_requirements.id"), nullable=True
    )
    prd_section_ref: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    category: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)

    # Relationships
    spec: Mapped["StructuredSpec"] = relationship(back_populates="requirements")
    children: Mapped[list["SpecRequirement"]] = relationship(
        back_populates="parent", remote_side="SpecRequirement.parent_requirement_id"
    )
    parent: Mapped[Optional["SpecRequirement"]] = relationship(
        back_populates="children", remote_side="SpecRequirement.id"
    )


class APIContract(Base, TimestampMixin):
    """OpenAPI-compliant API contract generated from spec."""

    __tablename__ = "api_contracts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    spec_id: Mapped[str] = mapped_column(ForeignKey("structured_specs.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    openapi_schema: Mapped[dict] = mapped_column(JSON, nullable=False)
    version: Mapped[str] = mapped_column(String(20), default="1.0.0")
    validation_status: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    validation_errors: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    # Relationships
    spec: Mapped["StructuredSpec"] = relationship(back_populates="api_contracts")


# ─── Execution Models ───────────────────────────────────────────────────────────

class WorkflowExecution(Base, TimestampMixin):
    """End-to-end workflow execution tracking."""

    __tablename__ = "workflow_executions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    prd_id: Mapped[str] = mapped_column(ForeignKey("prds.id"), nullable=False, index=True)
    spec_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("structured_specs.id"), nullable=True
    )
    state: Mapped[str] = mapped_column(
        String(30), default=WorkflowState.IDLE, nullable=False, index=True
    )
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    metadata_: Mapped[Optional[dict]] = mapped_column("metadata", JSON, nullable=True)

    # Checkpoint for recovery
    checkpoint_data: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)

    # Relationships
    prd: Mapped["PRD"] = relationship(back_populates="workflow_executions")
    agent_executions: Mapped[list["AgentExecution"]] = relationship(
        back_populates="workflow", cascade="all, delete-orphan"
    )
    traces: Mapped[list["ExecutionTrace"]] = relationship(
        back_populates="workflow", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_workflow_state_started", "state", "started_at"),
    )


class AgentExecution(Base, TimestampMixin):
    """Individual agent run within a workflow."""

    __tablename__ = "agent_executions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    workflow_id: Mapped[str] = mapped_column(
        ForeignKey("workflow_executions.id"), nullable=False, index=True
    )
    agent_type: Mapped[str] = mapped_column(String(30), nullable=False)
    input_data: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    output_data: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    success: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    token_usage: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    # Relationships
    workflow: Mapped["WorkflowExecution"] = relationship(back_populates="agent_executions")


class ExecutionTrace(Base, TimestampMixin):
    """Detailed execution event for observability and replay."""

    __tablename__ = "execution_traces"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    workflow_id: Mapped[str] = mapped_column(
        ForeignKey("workflow_executions.id"), nullable=False, index=True
    )
    trace_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    parent_span_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    span_id: Mapped[str] = mapped_column(String(36), default=_uuid)
    event_type: Mapped[str] = mapped_column(String(50), nullable=False)
    component: Mapped[str] = mapped_column(String(100), nullable=False)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    input_snapshot: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    output_snapshot: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    duration_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    status: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    metadata_: Mapped[Optional[dict]] = mapped_column("metadata", JSON, nullable=True)

    # Relationships
    workflow: Mapped["WorkflowExecution"] = relationship(back_populates="traces")

    __table_args__ = (
        Index("ix_trace_workflow_time", "workflow_id", "timestamp"),
    )


# ─── Artifact Models ────────────────────────────────────────────────────────────

class CodeArtifact(Base, TimestampMixin):
    """Generated code file with spec traceability."""

    __tablename__ = "code_artifacts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    workflow_id: Mapped[str] = mapped_column(
        ForeignKey("workflow_executions.id"), nullable=False, index=True
    )
    file_path: Mapped[str] = mapped_column(String(500), nullable=False)
    file_name: Mapped[str] = mapped_column(String(200), nullable=False)
    language: Mapped[str] = mapped_column(String(50), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    spec_requirement_ids: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    validation_status: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    validation_errors: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    line_count: Mapped[int] = mapped_column(Integer, default=0)


class TestArtifact(Base, TimestampMixin):
    """Generated test file with coverage metrics."""

    __tablename__ = "test_artifacts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    workflow_id: Mapped[str] = mapped_column(
        ForeignKey("workflow_executions.id"), nullable=False, index=True
    )
    test_type: Mapped[str] = mapped_column(String(50), nullable=False)  # unit, contract, trajectory
    file_name: Mapped[str] = mapped_column(String(200), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    target_artifact_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("code_artifacts.id"), nullable=True
    )
    execution_result: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    coverage_percent: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    pass_count: Mapped[int] = mapped_column(Integer, default=0)
    fail_count: Mapped[int] = mapped_column(Integer, default=0)


class ValidationResult(Base, TimestampMixin):
    """Validation outcome from any gate or checker."""

    __tablename__ = "validation_results"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    workflow_id: Mapped[str] = mapped_column(
        ForeignKey("workflow_executions.id"), nullable=False, index=True
    )
    validation_type: Mapped[str] = mapped_column(String(50), nullable=False)
    gate_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    passed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    severity: Mapped[str] = mapped_column(
        String(20), default=ValidationSeverity.INFO
    )
    findings: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    recommendations: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)


# ─── Audit Models ───────────────────────────────────────────────────────────────

class AuditLog(Base):
    """Comprehensive audit trail for all system actions."""

    __tablename__ = "audit_logs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False, index=True
    )
    user_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    action: Mapped[str] = mapped_column(String(30), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(50), nullable=False)
    resource_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    before_state: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    after_state: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    details: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    ip_address: Mapped[Optional[str]] = mapped_column(String(45), nullable=True)

    __table_args__ = (
        Index("ix_audit_resource", "resource_type", "resource_id"),
    )


class HumanReview(Base, TimestampMixin):
    """Human review queue entry for escalated decisions."""

    __tablename__ = "human_reviews"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    workflow_id: Mapped[str] = mapped_column(
        ForeignKey("workflow_executions.id"), nullable=False, index=True
    )
    review_type: Mapped[str] = mapped_column(String(50), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    context: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), default=ReviewStatus.PENDING, nullable=False, index=True
    )
    priority: Mapped[str] = mapped_column(String(20), default="medium")
    assigned_to: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    resolution_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_by: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)


class PolicyOverride(Base, TimestampMixin):
    """Record of manual policy/gate overrides for audit."""

    __tablename__ = "policy_overrides"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    workflow_id: Mapped[str] = mapped_column(
        ForeignKey("workflow_executions.id"), nullable=False, index=True
    )
    gate_name: Mapped[str] = mapped_column(String(100), nullable=False)
    override_reason: Mapped[str] = mapped_column(Text, nullable=False)
    approved_by: Mapped[str] = mapped_column(String(100), nullable=False)
    original_result: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
