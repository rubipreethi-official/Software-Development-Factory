"""
agents.py — Multi-Agent Code Generation System
================================================
Tasks: D-07, D-08, D-09, D-10
Implements the hierarchical agent swarm: base agent framework,
API Designer, Logic Implementer, and Test Generator agents.
Each agent is bound to spec lineage with full traceability.
"""

from __future__ import annotations

import ast
import json
import re
import uuid
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any, Optional

import structlog

from config import get_settings
from models import (
    AgentExecution,
    AgentType,
    CodeArtifact,
    TestArtifact,
    StructuredSpec,
)

logger = structlog.get_logger("agents")


# ─── D-07: Base Agent Framework ──────────────────────────────────────────────────

class BaseAgent(ABC):
    """
    Base class for all AI agents.
    Handles Claude API interaction, prompt management, retry logic, and metrics.
    """

    agent_type: str = "base"
    max_retries: int = 3

    def __init__(self):
        self.settings = get_settings()
        self._client = None
        self._execution_log: list[dict] = []

    @property
    def client(self):
        """Lazy-initialized Claude client."""
        if self._client is None and not self.settings.is_mock_mode:
            import anthropic
            self._client = anthropic.Anthropic(api_key=self.settings.claude_api_key)
        return self._client

    async def execute(
        self,
        input_data: dict,
        workflow_id: str,
        session,
    ) -> AgentExecution:
        """
        Execute the agent with full lifecycle tracking.
        Records execution to database for observability.
        """
        started_at = datetime.now(timezone.utc)

        execution = AgentExecution(
            workflow_id=workflow_id,
            agent_type=self.agent_type,
            input_data=self._sanitize_input(input_data),
            started_at=started_at,
        )
        session.add(execution)
        await session.flush()

        try:
            output = await self._run(input_data, session)
            ended_at = datetime.now(timezone.utc)

            execution.output_data = output
            execution.completed_at = ended_at
            execution.duration_ms = int((ended_at - started_at).total_seconds() * 1000)
            execution.success = True

            logger.info(
                "agent_execution_success",
                agent=self.agent_type,
                workflow_id=workflow_id,
                duration_ms=execution.duration_ms,
            )

        except Exception as e:
            ended_at = datetime.now(timezone.utc)
            execution.completed_at = ended_at
            execution.duration_ms = int((ended_at - started_at).total_seconds() * 1000)
            execution.success = False
            execution.error_message = str(e)

            logger.error(
                "agent_execution_failed",
                agent=self.agent_type,
                workflow_id=workflow_id,
                error=str(e),
            )
            raise

        return execution

    @abstractmethod
    async def _run(self, input_data: dict, session) -> dict:
        """Agent-specific execution logic. Override in subclasses."""
        ...

    def _call_claude(self, system_prompt: str, user_prompt: str) -> str:
        """Call Claude API or return mock response."""
        if self.settings.is_mock_mode:
            return self._mock_response(system_prompt, user_prompt)

        message = self.client.messages.create(
            model=self.settings.claude_model,
            max_tokens=4096,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )
        return message.content[0].text

    @abstractmethod
    def _mock_response(self, system_prompt: str, user_prompt: str) -> str:
        """Generate mock response for testing without API key."""
        ...

    def _extract_json(self, text: str) -> dict:
        """Extract JSON from Claude response (may be in markdown code blocks)."""
        json_match = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', text, re.DOTALL)
        if json_match:
            text = json_match.group(1)
        return json.loads(text.strip())

    def _extract_code(self, text: str, language: str = "python") -> str:
        """Extract code from Claude response."""
        code_match = re.search(
            rf'```(?:{language})?\s*\n?(.*?)\n?```',
            text,
            re.DOTALL,
        )
        if code_match:
            return code_match.group(1).strip()
        return text.strip()

    def _sanitize_input(self, data: dict) -> dict:
        """Remove large content from input for storage efficiency."""
        sanitized = {}
        for k, v in data.items():
            if isinstance(v, str) and len(v) > 1000:
                sanitized[k] = v[:500] + f"... [truncated, {len(v)} chars total]"
            elif isinstance(v, dict):
                sanitized[k] = {kk: "..." if isinstance(vv, (str, dict)) and len(str(vv)) > 500 else vv for kk, vv in v.items()}
            else:
                sanitized[k] = v
        return sanitized


class AgentRegistry:
    """Registry of available agents with capability routing."""

    _agents: dict[str, type[BaseAgent]] = {}

    @classmethod
    def register(cls, agent_class: type[BaseAgent]) -> type[BaseAgent]:
        """Decorator to register an agent."""
        cls._agents[agent_class.agent_type] = agent_class
        return agent_class

    @classmethod
    def get(cls, agent_type: str) -> BaseAgent:
        """Get an agent instance by type."""
        if agent_type not in cls._agents:
            raise ValueError(f"Unknown agent type: {agent_type}. Available: {list(cls._agents.keys())}")
        return cls._agents[agent_type]()

    @classmethod
    def list_agents(cls) -> list[str]:
        return list(cls._agents.keys())


# ─── D-08: API Designer Agent ───────────────────────────────────────────────────

@AgentRegistry.register
class APIDesignerAgent(BaseAgent):
    """Generates OpenAPI-compliant API contracts from spec requirements."""

    agent_type = AgentType.API_DESIGNER

    SYSTEM_PROMPT = """You are a senior API architect. Generate a complete OpenAPI 3.0 specification from the given requirements.

Output MUST be a valid OpenAPI 3.0 JSON document with:
- info (title, version, description)
- paths (all endpoints with request/response schemas)
- components/schemas (all data models)
- security schemes if authentication is required

Follow RESTful conventions strictly. Include proper HTTP status codes, error responses, and pagination where appropriate."""

    async def _run(self, input_data: dict, session) -> dict:
        spec_content = input_data.get("spec_content", {})
        workflow_id = input_data.get("workflow_id")

        prompt = f"""Generate an OpenAPI 3.0 specification for this system:

Title: {spec_content.get('title', 'API')}
Overview: {spec_content.get('overview', '')}

Requirements:
{json.dumps(spec_content.get('functional_requirements', []), indent=2)}

Endpoints defined in spec:
{json.dumps(spec_content.get('api_endpoints', []), indent=2)}

Data Models:
{json.dumps(spec_content.get('data_models', []), indent=2)}

Output the complete OpenAPI 3.0 JSON specification."""

        response = self._call_claude(self.SYSTEM_PROMPT, prompt)
        contract = self._extract_json(response)

        # Store as artifact
        if workflow_id:
            artifact = CodeArtifact(
                workflow_id=workflow_id,
                file_path="api/openapi.json",
                file_name="openapi.json",
                language="json",
                content=json.dumps(contract, indent=2),
                spec_requirement_ids={"source": "api_designer_agent"},
                line_count=len(json.dumps(contract, indent=2).splitlines()),
            )
            session.add(artifact)

        return {
            "contract": contract,
            "endpoint_count": len(contract.get("paths", {})),
            "schema_count": len(contract.get("components", {}).get("schemas", {})),
        }

    def _mock_response(self, system_prompt: str, user_prompt: str) -> str:
        """Generate a realistic mock OpenAPI spec."""
        mock_spec = {
            "openapi": "3.0.3",
            "info": {
                "title": "Generated API",
                "version": "1.0.0",
                "description": "Auto-generated API specification",
            },
            "paths": {
                "/api/v1/health": {
                    "get": {
                        "summary": "Health check",
                        "operationId": "healthCheck",
                        "responses": {
                            "200": {
                                "description": "Service is healthy",
                                "content": {
                                    "application/json": {
                                        "schema": {
                                            "type": "object",
                                            "properties": {
                                                "status": {"type": "string"},
                                                "timestamp": {"type": "string", "format": "date-time"},
                                            },
                                        }
                                    }
                                },
                            }
                        },
                    }
                },
                "/api/v1/resources": {
                    "get": {
                        "summary": "List resources",
                        "operationId": "listResources",
                        "parameters": [
                            {"name": "page", "in": "query", "schema": {"type": "integer", "default": 1}},
                            {"name": "limit", "in": "query", "schema": {"type": "integer", "default": 20}},
                        ],
                        "responses": {
                            "200": {
                                "description": "Resource list",
                                "content": {
                                    "application/json": {
                                        "schema": {
                                            "type": "object",
                                            "properties": {
                                                "items": {"type": "array", "items": {"$ref": "#/components/schemas/Resource"}},
                                                "total": {"type": "integer"},
                                            },
                                        }
                                    }
                                },
                            }
                        },
                        "security": [{"bearerAuth": []}],
                    },
                    "post": {
                        "summary": "Create resource",
                        "operationId": "createResource",
                        "requestBody": {
                            "required": True,
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/ResourceCreate"}
                                }
                            },
                        },
                        "responses": {
                            "201": {
                                "description": "Resource created",
                                "content": {
                                    "application/json": {
                                        "schema": {"$ref": "#/components/schemas/Resource"}
                                    }
                                },
                            },
                            "400": {"description": "Invalid input"},
                        },
                        "security": [{"bearerAuth": []}],
                    },
                },
            },
            "components": {
                "schemas": {
                    "Resource": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string", "format": "uuid"},
                            "name": {"type": "string"},
                            "description": {"type": "string"},
                            "created_at": {"type": "string", "format": "date-time"},
                            "updated_at": {"type": "string", "format": "date-time"},
                        },
                        "required": ["id", "name"],
                    },
                    "ResourceCreate": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "description": {"type": "string"},
                        },
                        "required": ["name"],
                    },
                },
                "securitySchemes": {
                    "bearerAuth": {
                        "type": "http",
                        "scheme": "bearer",
                        "bearerFormat": "JWT",
                    }
                },
            },
        }
        return f"```json\n{json.dumps(mock_spec, indent=2)}\n```"


# ─── D-09: Logic Implementer Agent ──────────────────────────────────────────────

@AgentRegistry.register
class LogicImplementerAgent(BaseAgent):
    """Generates business logic implementation from spec and API contract."""

    agent_type = AgentType.LOGIC_IMPLEMENTER

    SYSTEM_PROMPT = """You are a senior Python developer. Generate clean, production-quality Python code implementing the business logic described in the requirements.

Rules:
- Use FastAPI for API endpoints
- Use Pydantic for data validation
- Include proper error handling
- Add docstrings and type hints
- Include comments linking code to requirement IDs (e.g., # REQ-001)
- Follow PEP 8 conventions
- Output complete, runnable code files"""

    async def _run(self, input_data: dict, session) -> dict:
        spec_content = input_data.get("spec_content", {})
        api_contract = input_data.get("api_contract", {})
        workflow_id = input_data.get("workflow_id")

        prompt = f"""Implement the business logic for this system:

Requirements:
{json.dumps(spec_content.get('functional_requirements', []), indent=2)}

API Contract (OpenAPI):
{json.dumps(api_contract, indent=2)}

Data Models:
{json.dumps(spec_content.get('data_models', []), indent=2)}

Generate a complete Python module with:
1. Pydantic models for request/response schemas
2. FastAPI route handlers for each endpoint
3. Business logic functions
4. Error handling

Output as a single Python file."""

        response = self._call_claude(self.SYSTEM_PROMPT, prompt)
        code = self._extract_code(response, "python")

        # Validate syntax
        syntax_valid = True
        syntax_errors = []
        try:
            ast.parse(code)
        except SyntaxError as e:
            syntax_valid = False
            syntax_errors.append(f"Line {e.lineno}: {e.msg}")

        # Store artifact
        if workflow_id:
            artifact = CodeArtifact(
                workflow_id=workflow_id,
                file_path="src/app.py",
                file_name="app.py",
                language="python",
                content=code,
                spec_requirement_ids={
                    "requirements": [r.get("id") for r in spec_content.get("functional_requirements", [])],
                },
                validation_status="valid" if syntax_valid else "syntax_error",
                validation_errors={"syntax": syntax_errors} if syntax_errors else None,
                line_count=len(code.splitlines()),
            )
            session.add(artifact)

        return {
            "code_length": len(code),
            "line_count": len(code.splitlines()),
            "syntax_valid": syntax_valid,
            "syntax_errors": syntax_errors,
            "file_path": "src/app.py",
        }

    def _mock_response(self, system_prompt: str, user_prompt: str) -> str:
        mock_code = '''"""
Generated Application — Auto-generated by Logic Implementer Agent
==================================================================
Linked to spec requirements: see inline REQ-XXXXXX comments.
"""

from datetime import datetime
from typing import Optional
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, Field


# ─── Pydantic Models ───────────────────────────────

class ResourceCreate(BaseModel):
    """Request schema for creating a resource. # REQ-000001"""
    name: str = Field(..., min_length=1, max_length=200)
    description: Optional[str] = None

class ResourceResponse(BaseModel):
    """Response schema for resource data."""
    id: str
    name: str
    description: Optional[str]
    created_at: datetime
    updated_at: datetime

class ResourceList(BaseModel):
    """Paginated resource list response."""
    items: list[ResourceResponse]
    total: int
    page: int
    limit: int


# ─── In-Memory Store (replace with DB) ─────────────

_store: dict[str, dict] = {}


# ─── Business Logic ────────────────────────────────

def create_resource(data: ResourceCreate) -> dict:
    """Create a new resource. # REQ-000001"""
    resource_id = str(uuid4())
    now = datetime.utcnow()
    resource = {
        "id": resource_id,
        "name": data.name,
        "description": data.description,
        "created_at": now,
        "updated_at": now,
    }
    _store[resource_id] = resource
    return resource

def get_resource(resource_id: str) -> dict:
    """Get resource by ID. Raises 404 if not found."""
    if resource_id not in _store:
        raise HTTPException(status_code=404, detail="Resource not found")
    return _store[resource_id]

def list_resources(page: int = 1, limit: int = 20) -> dict:
    """List resources with pagination. # REQ-000001"""
    items = list(_store.values())
    total = len(items)
    start = (page - 1) * limit
    end = start + limit
    return {
        "items": items[start:end],
        "total": total,
        "page": page,
        "limit": limit,
    }


# ─── API Routes ─────────────────────────────────────

router = APIRouter(prefix="/api/v1", tags=["resources"])

@router.post("/resources", response_model=ResourceResponse, status_code=201)
async def create_resource_endpoint(data: ResourceCreate):
    """Create a new resource."""
    return create_resource(data)

@router.get("/resources", response_model=ResourceList)
async def list_resources_endpoint(page: int = 1, limit: int = 20):
    """List all resources with pagination."""
    return list_resources(page, limit)

@router.get("/resources/{resource_id}", response_model=ResourceResponse)
async def get_resource_endpoint(resource_id: str):
    """Get a specific resource by ID."""
    return get_resource(resource_id)

@router.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "timestamp": datetime.utcnow().isoformat()}
'''
        return f"```python\n{mock_code}\n```"


# ─── D-10: Test Generator Agent ─────────────────────────────────────────────────

@AgentRegistry.register
class TestGeneratorAgent(BaseAgent):
    """Generates comprehensive test suites from spec and generated code."""

    agent_type = AgentType.TEST_GENERATOR

    SYSTEM_PROMPT = """You are a senior QA engineer. Generate comprehensive pytest test cases for the given code and requirements.

Include:
1. Unit tests for each business logic function
2. API endpoint tests using FastAPI TestClient
3. Edge cases and error conditions
4. Validation tests for input schemas
5. Comments linking tests to requirement IDs (# Tests REQ-XXXXXX)

Use pytest conventions with clear test names and docstrings.
Output complete, runnable test code."""

    async def _run(self, input_data: dict, session) -> dict:
        spec_content = input_data.get("spec_content", {})
        code_content = input_data.get("code_content", "")
        workflow_id = input_data.get("workflow_id")

        prompt = f"""Generate pytest tests for this code:

Code:
```python
{code_content[:3000]}
```

Requirements being tested:
{json.dumps(spec_content.get('functional_requirements', []), indent=2)}

Generate comprehensive tests including:
1. Happy path tests
2. Error/edge case tests
3. Validation tests
4. Contract tests verifying API schemas"""

        response = self._call_claude(self.SYSTEM_PROMPT, prompt)
        test_code = self._extract_code(response, "python")

        # Validate test syntax
        syntax_valid = True
        try:
            ast.parse(test_code)
        except SyntaxError:
            syntax_valid = False

        # Count test functions
        test_count = len(re.findall(r'def test_\w+', test_code))

        # Store artifact
        if workflow_id:
            artifact = TestArtifact(
                workflow_id=workflow_id,
                test_type="unit",
                file_name="test_app.py",
                content=test_code,
                pass_count=0,  # Updated after execution
                fail_count=0,
            )
            session.add(artifact)

        return {
            "test_count": test_count,
            "syntax_valid": syntax_valid,
            "line_count": len(test_code.splitlines()),
            "file_name": "test_app.py",
        }

    def _mock_response(self, system_prompt: str, user_prompt: str) -> str:
        mock_tests = '''"""
Auto-generated Test Suite
=========================
Tests generated from spec requirements.
"""

import pytest
from datetime import datetime


# ─── Unit Tests ─────────────────────────────────────

class TestResourceCreation:
    """Tests for resource creation. # Tests REQ-000001"""

    def test_create_resource_success(self):
        """Test creating a resource with valid data."""
        from app import create_resource, ResourceCreate, _store
        _store.clear()

        data = ResourceCreate(name="Test Resource", description="A test")
        result = create_resource(data)

        assert result["name"] == "Test Resource"
        assert result["description"] == "A test"
        assert "id" in result
        assert "created_at" in result

    def test_create_resource_minimal(self):
        """Test creating a resource with only required fields."""
        from app import create_resource, ResourceCreate, _store
        _store.clear()

        data = ResourceCreate(name="Minimal")
        result = create_resource(data)

        assert result["name"] == "Minimal"
        assert result["description"] is None

    def test_create_resource_name_validation(self):
        """Test that empty name is rejected."""
        from app import ResourceCreate
        with pytest.raises(Exception):
            ResourceCreate(name="")


class TestResourceRetrieval:
    """Tests for resource retrieval."""

    def test_get_existing_resource(self):
        """Test retrieving an existing resource."""
        from app import create_resource, get_resource, ResourceCreate, _store
        _store.clear()

        data = ResourceCreate(name="Findable")
        created = create_resource(data)
        found = get_resource(created["id"])

        assert found["id"] == created["id"]
        assert found["name"] == "Findable"

    def test_get_nonexistent_resource(self):
        """Test 404 for missing resource."""
        from app import get_resource, _store
        _store.clear()

        with pytest.raises(Exception):
            get_resource("nonexistent-id")


class TestResourceListing:
    """Tests for resource listing with pagination."""

    def test_list_empty(self):
        """Test listing when no resources exist."""
        from app import list_resources, _store
        _store.clear()

        result = list_resources()
        assert result["total"] == 0
        assert result["items"] == []

    def test_list_with_pagination(self):
        """Test pagination parameters."""
        from app import create_resource, list_resources, ResourceCreate, _store
        _store.clear()

        for i in range(5):
            create_resource(ResourceCreate(name=f"Item {i}"))

        result = list_resources(page=1, limit=2)
        assert len(result["items"]) == 2
        assert result["total"] == 5
        assert result["page"] == 1


class TestHealthCheck:
    """Tests for health check endpoint."""

    def test_health_returns_healthy(self):
        """Test health check returns expected format."""
        # Would use TestClient in real implementation
        assert True  # Placeholder for API test
'''
        return f"```python\n{mock_tests}\n```"


# ─── Spec Generator Agent (used by orchestrator) ─────────────────────────────────

@AgentRegistry.register
class SpecGeneratorAgent(BaseAgent):
    """Wraps spec_system.SpecGenerator as an agent for orchestration."""

    agent_type = AgentType.SPEC_GENERATOR

    async def _run(self, input_data: dict, session) -> dict:
        from spec_system import SpecGenerator, PRDProcessor, RequirementExtractor, SpecValidator

        prd_id = input_data.get("prd_id")
        prd = await session.get(PRD, prd_id)
        if not prd:
            raise ValueError(f"PRD not found: {prd_id}")

        # Generate spec
        spec = await SpecGenerator.generate(prd, session)

        # Extract requirements
        requirements = await RequirementExtractor.extract_and_store(spec, session)

        # Validate spec
        validation_report = await SpecValidator.validate(spec, session)

        return {
            "spec_id": spec.id,
            "version": spec.version,
            "requirement_count": len(requirements),
            "validation": validation_report,
            "quality_score": spec.quality_score,
        }

    def _mock_response(self, system_prompt: str, user_prompt: str) -> str:
        return "{}"  # Not used — _run handles everything

    def _call_claude(self, system_prompt: str, user_prompt: str) -> str:
        return "{}"  # Not used directly


# Need to import PRD for SpecGeneratorAgent
from models import PRD
