"""
MongoDB document schemas using Pydantic.

Role in pipeline: Defines the shape of every document stored in MongoDB.
MongoDB is schemaless but we enforce structure via Pydantic validation.
Every document gets an auto-generated UUID as its _id field.

Depends on: pydantic
Used by: all repository classes
"""
from pydantic import BaseModel, Field
from typing import Optional, List, Any
from datetime import datetime
from enum import Enum
import uuid

class PipelineStatus(str, Enum):
    PENDING = "pending"
    SPEC_GENERATION = "spec_generation"
    CODE_GENERATION = "code_generation"
    TEST_GENERATION = "test_generation"
    COMPLETE = "complete"
    FAILED = "failed"

class PRDDocument(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    raw_text: str
    created_at: datetime = Field(default_factory=datetime.utcnow)
    status: PipelineStatus = PipelineStatus.PENDING

class SpecDocument(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    prd_id: str                    # links back to PRDDocument
    title: str
    version: str = "1.0.0"
    requirements: List[dict] = []
    tech_stack: List[str] = []
    constraints: List[str] = []
    ambiguities: List[str] = []
    created_at: datetime = Field(default_factory=datetime.utcnow)

class ArtifactDocument(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    execution_id: str
    artifact_type: str             # "spec", "code", "tests"
    content: str
    agent_id: str
    model_used: str
    tokens_in: int = 0
    tokens_out: int = 0
    latency_ms: int = 0
    created_at: datetime = Field(default_factory=datetime.utcnow)

class ExecutionDocument(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    prd_id: str
    status: PipelineStatus = PipelineStatus.PENDING
    stages_complete: List[str] = []
    current_stage: Optional[str] = None
    error: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
