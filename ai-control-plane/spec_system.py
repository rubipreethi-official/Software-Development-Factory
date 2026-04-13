"""
spec_system.py — PRD Ingestion, Spec Generation, Validation & Versioning
==========================================================================
Tasks: D-02, D-03, D-04, D-05, D-06
Converts raw PRDs into validated, versioned, structured specifications
with contradiction detection and traceability.
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from difflib import SequenceMatcher
from typing import Any, Optional

import structlog
from pydantic import BaseModel, Field
from sqlalchemy import select, func

from config import get_settings, get_policy_manager
from models import (
    PRD, PRDStatus,
    StructuredSpec, SpecStatus,
    SpecRequirement,
    APIContract,
    AuditLog, AuditAction,
)

logger = structlog.get_logger("spec_system")


# ─── Pydantic Schemas for Spec Structure ─────────────────────────────────────────

class RequirementSchema(BaseModel):
    """Schema for a single requirement within a spec."""
    id: str = Field(default_factory=lambda: f"REQ-{uuid.uuid4().hex[:6].upper()}")
    description: str
    priority: str = "medium"
    category: str = "functional"
    acceptance_criteria: str = ""
    dependencies: list[str] = Field(default_factory=list)


class EndpointSchema(BaseModel):
    """Schema for an API endpoint."""
    path: str
    method: str
    summary: str
    request_body: Optional[dict] = None
    response_schema: Optional[dict] = None
    auth_required: bool = True
    parameters: list[dict] = Field(default_factory=list)


class DataModelSchema(BaseModel):
    """Schema for a data model."""
    name: str
    fields: list[dict]
    relationships: list[str] = Field(default_factory=list)


class SpecContentSchema(BaseModel):
    """Complete structured specification schema."""
    title: str
    overview: str
    functional_requirements: list[RequirementSchema] = Field(default_factory=list)
    non_functional_requirements: list[RequirementSchema] = Field(default_factory=list)
    api_endpoints: list[EndpointSchema] = Field(default_factory=list)
    data_models: list[DataModelSchema] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    out_of_scope: list[str] = Field(default_factory=list)


# ─── D-02: PRD Ingestion & Preprocessing ─────────────────────────────────────────

class PRDProcessor:
    """Handles PRD ingestion, preprocessing, and validation."""

    MIN_WORD_COUNT = 20  # Relaxed for pilot

    @staticmethod
    def preprocess(raw_text: str) -> str:
        """Normalize and clean PRD text."""
        # Normalize whitespace
        text = re.sub(r'\r\n', '\n', raw_text)
        text = re.sub(r'\n{3,}', '\n\n', text)
        text = text.strip()

        # Standardize section headers
        text = re.sub(r'^(#{1,6})\s*', r'\1 ', text, flags=re.MULTILINE)

        return text

    @staticmethod
    def extract_metadata(text: str) -> dict[str, Any]:
        """Extract metadata from PRD text."""
        metadata = {
            "word_count": len(text.split()),
            "has_sections": bool(re.search(r'^#+\s', text, re.MULTILINE)),
            "has_bullet_points": bool(re.search(r'^\s*[-*]\s', text, re.MULTILINE)),
            "has_numbered_lists": bool(re.search(r'^\s*\d+\.\s', text, re.MULTILINE)),
        }

        # Try to extract title from first heading
        title_match = re.search(r'^#\s+(.+)$', text, re.MULTILINE)
        if title_match:
            metadata["extracted_title"] = title_match.group(1).strip()

        # Identify key sections
        sections_found = []
        for section in ["overview", "requirements", "constraints", "scope",
                        "architecture", "security", "testing"]:
            if re.search(rf'\b{section}\b', text, re.IGNORECASE):
                sections_found.append(section)
        metadata["sections_found"] = sections_found

        return metadata

    @classmethod
    def validate_prd(cls, text: str) -> tuple[bool, list[str]]:
        """
        Validate PRD meets minimum requirements.
        Returns (is_valid, list_of_warnings).
        """
        warnings = []
        metadata = cls.extract_metadata(text)

        if metadata["word_count"] < cls.MIN_WORD_COUNT:
            warnings.append(
                f"PRD is too short ({metadata['word_count']} words, "
                f"minimum {cls.MIN_WORD_COUNT})"
            )

        policy = get_policy_manager()
        required_sections = policy.get("spec_validation", "required_sections", [])
        missing = [s for s in required_sections if s not in metadata.get("sections_found", [])]
        if missing:
            warnings.append(f"Missing recommended sections: {', '.join(missing)}")

        is_valid = metadata["word_count"] >= cls.MIN_WORD_COUNT
        return is_valid, warnings

    @classmethod
    async def ingest(cls, title: str, raw_content: str, session, source_metadata: dict | None = None) -> PRD:
        """
        Full PRD ingestion pipeline: preprocess → validate → store.
        """
        processed = cls.preprocess(raw_content)
        metadata = cls.extract_metadata(processed)
        is_valid, warnings = cls.validate_prd(processed)

        prd = PRD(
            title=title or metadata.get("extracted_title", "Untitled PRD"),
            raw_content=processed,
            source_metadata=source_metadata or {},
            status=PRDStatus.VALIDATED if is_valid else PRDStatus.REJECTED,
            word_count=metadata["word_count"],
            validation_notes=json.dumps(warnings) if warnings else None,
        )
        session.add(prd)
        await session.flush()

        logger.info(
            "prd_ingested",
            prd_id=prd.id,
            title=prd.title,
            word_count=metadata["word_count"],
            valid=is_valid,
            warnings=warnings,
        )
        return prd


# ─── D-03: Spec Generation (Claude or Mock) ──────────────────────────────────────

class SpecGenerator:
    """
    Generates structured specifications from PRDs using Claude AI.
    Falls back to intelligent mock generation when API key is not configured.
    """

    SYSTEM_PROMPT = """You are a senior software architect. Your task is to convert a Product Requirements Document (PRD) into a detailed structured specification.

Output MUST be valid JSON matching this exact schema:
{
  "title": "string",
  "overview": "string - 2-3 paragraph summary",
  "functional_requirements": [
    {"id": "REQ-XXXXXX", "description": "string", "priority": "high|medium|low", "category": "string", "acceptance_criteria": "string", "dependencies": ["REQ-..."]}
  ],
  "non_functional_requirements": [
    {"id": "REQ-XXXXXX", "description": "string", "priority": "high|medium|low", "category": "performance|security|scalability|reliability", "acceptance_criteria": "string", "dependencies": []}
  ],
  "api_endpoints": [
    {"path": "/api/v1/...", "method": "GET|POST|PUT|DELETE", "summary": "string", "request_body": null|{"type":"object","properties":{}}, "response_schema": {"type":"object","properties":{}}, "auth_required": true}
  ],
  "data_models": [
    {"name": "string", "fields": [{"name":"string","type":"string","required":true}], "relationships": ["string"]}
  ],
  "constraints": ["string"],
  "assumptions": ["string"],
  "out_of_scope": ["string"]
}

Rules:
- Every requirement MUST have a unique ID (REQ-XXXXXX format)
- Every requirement MUST have acceptance criteria
- API endpoints must follow RESTful conventions
- Data models must include all fields referenced in requirements
- Be specific; avoid vague language"""

    @classmethod
    async def generate(cls, prd: PRD, session) -> StructuredSpec:
        """Generate a structured spec from a PRD."""
        settings = get_settings()

        if settings.is_mock_mode:
            spec_content = cls._generate_mock(prd)
        else:
            spec_content = await cls._generate_with_claude(prd, settings)

        # Parse and validate the spec content
        try:
            parsed = SpecContentSchema(**spec_content)
            content_dict = parsed.model_dump()
        except Exception as e:
            logger.error("spec_parse_failed", error=str(e))
            content_dict = spec_content  # Store raw even if validation fails

        # Determine version
        existing_count = await session.execute(
            select(func.count()).where(StructuredSpec.prd_id == prd.id)
        )
        version = (existing_count.scalar() or 0) + 1

        spec = StructuredSpec(
            prd_id=prd.id,
            version=version,
            content=content_dict,
            status=SpecStatus.DRAFT,
        )
        session.add(spec)
        await session.flush()

        logger.info(
            "spec_generated",
            spec_id=spec.id,
            prd_id=prd.id,
            version=version,
            mock_mode=settings.is_mock_mode,
        )
        return spec

    @classmethod
    async def _generate_with_claude(cls, prd: PRD, settings) -> dict:
        """Generate spec using Claude API."""
        import anthropic

        client = anthropic.Anthropic(api_key=settings.claude_api_key)

        message = client.messages.create(
            model=settings.claude_model,
            max_tokens=4096,
            system=cls.SYSTEM_PROMPT,
            messages=[
                {
                    "role": "user",
                    "content": f"Convert this PRD into a structured specification:\n\n---\nTitle: {prd.title}\n\n{prd.raw_content}\n---",
                }
            ],
        )

        response_text = message.content[0].text

        # Extract JSON from response (may be wrapped in markdown code blocks)
        json_match = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', response_text, re.DOTALL)
        if json_match:
            response_text = json_match.group(1)

        return json.loads(response_text)

    @classmethod
    def _generate_mock(cls, prd: PRD) -> dict:
        """Generate intelligent mock spec from PRD content analysis."""
        content = prd.raw_content.lower()
        title = prd.title

        # Analyze PRD content to generate relevant mock
        has_auth = any(w in content for w in ["auth", "login", "user", "password", "jwt"])
        has_api = any(w in content for w in ["api", "endpoint", "rest", "http"])
        has_data = any(w in content for w in ["database", "store", "model", "data", "crud"])

        # Build requirements from content analysis
        func_reqs = []
        req_counter = 1

        if has_auth:
            func_reqs.extend([
                RequirementSchema(
                    id=f"REQ-{req_counter:06d}",
                    description="User registration with email and password",
                    priority="high",
                    category="authentication",
                    acceptance_criteria="Users can register with unique email, password is hashed",
                ),
                RequirementSchema(
                    id=f"REQ-{req_counter + 1:06d}",
                    description="User login with JWT token generation",
                    priority="high",
                    category="authentication",
                    acceptance_criteria="Valid credentials return JWT token with configurable expiry",
                ),
            ])
            req_counter += 2

        if has_api:
            func_reqs.append(RequirementSchema(
                id=f"REQ-{req_counter:06d}",
                description="RESTful API with versioned endpoints",
                priority="high",
                category="api",
                acceptance_criteria="All endpoints follow REST conventions with /api/v1 prefix",
            ))
            req_counter += 1

        if has_data:
            func_reqs.append(RequirementSchema(
                id=f"REQ-{req_counter:06d}",
                description="CRUD operations for core data entities",
                priority="high",
                category="data",
                acceptance_criteria="All entities support Create, Read, Update, Delete operations",
            ))
            req_counter += 1

        # Always add at least one requirement
        if not func_reqs:
            func_reqs.append(RequirementSchema(
                id=f"REQ-{req_counter:06d}",
                description=f"Core functionality as described in PRD: {title}",
                priority="high",
                category="functional",
                acceptance_criteria="System implements the primary use case described in the PRD",
            ))

        # Build mock endpoints
        endpoints = []
        if has_auth:
            endpoints.extend([
                EndpointSchema(
                    path="/api/v1/auth/register",
                    method="POST",
                    summary="Register a new user",
                    request_body={"type": "object", "properties": {"email": {"type": "string"}, "password": {"type": "string"}}},
                    response_schema={"type": "object", "properties": {"user_id": {"type": "string"}, "email": {"type": "string"}}},
                    auth_required=False,
                ),
                EndpointSchema(
                    path="/api/v1/auth/login",
                    method="POST",
                    summary="Authenticate user and return JWT",
                    request_body={"type": "object", "properties": {"email": {"type": "string"}, "password": {"type": "string"}}},
                    response_schema={"type": "object", "properties": {"token": {"type": "string"}, "expires_in": {"type": "integer"}}},
                    auth_required=False,
                ),
            ])

        # Build spec
        spec = SpecContentSchema(
            title=title,
            overview=f"Structured specification generated from PRD: {title}. "
                     f"This specification defines the functional and non-functional requirements, "
                     f"API contracts, and data models needed to implement the system.",
            functional_requirements=func_reqs,
            non_functional_requirements=[
                RequirementSchema(
                    id="REQ-NFR-001",
                    description="API response time under 500ms for 95th percentile",
                    priority="high",
                    category="performance",
                    acceptance_criteria="Load tests confirm p95 latency < 500ms",
                ),
                RequirementSchema(
                    id="REQ-NFR-002",
                    description="All sensitive data encrypted at rest and in transit",
                    priority="high",
                    category="security",
                    acceptance_criteria="TLS 1.2+ for transit, AES-256 for rest",
                ),
            ],
            api_endpoints=endpoints,
            data_models=[
                DataModelSchema(
                    name="User",
                    fields=[
                        {"name": "id", "type": "uuid", "required": True},
                        {"name": "email", "type": "string", "required": True},
                        {"name": "password_hash", "type": "string", "required": True},
                        {"name": "created_at", "type": "datetime", "required": True},
                    ],
                    relationships=[],
                ),
            ] if has_auth else [],
            constraints=[
                "Must run on Python 3.11+",
                "Must use PostgreSQL or SQLite for persistence",
                "Must be containerizable with Docker",
            ],
            assumptions=[
                "Single-tenant deployment for pilot phase",
                "Maximum 100 concurrent users during pilot",
            ],
            out_of_scope=[
                "Multi-tenancy",
                "Real-time features (WebSocket)",
                "Mobile application",
            ],
        )

        return spec.model_dump()


# ─── D-04: Requirement Extraction & Traceability ─────────────────────────────────

class RequirementExtractor:
    """Extracts individual requirements from a spec and creates traceability links."""

    @staticmethod
    async def extract_and_store(spec: StructuredSpec, session) -> list[SpecRequirement]:
        """Extract requirements from spec content and persist them."""
        content = spec.content
        requirements = []

        # Extract functional requirements
        for req_data in content.get("functional_requirements", []):
            req = SpecRequirement(
                spec_id=spec.id,
                requirement_id=req_data.get("id", f"REQ-{uuid.uuid4().hex[:6].upper()}"),
                description=req_data.get("description", ""),
                priority=req_data.get("priority", "medium"),
                acceptance_criteria=req_data.get("acceptance_criteria", ""),
                category=req_data.get("category", "functional"),
                prd_section_ref="functional_requirements",
            )
            session.add(req)
            requirements.append(req)

        # Extract non-functional requirements
        for req_data in content.get("non_functional_requirements", []):
            req = SpecRequirement(
                spec_id=spec.id,
                requirement_id=req_data.get("id", f"REQ-{uuid.uuid4().hex[:6].upper()}"),
                description=req_data.get("description", ""),
                priority=req_data.get("priority", "medium"),
                acceptance_criteria=req_data.get("acceptance_criteria", ""),
                category=req_data.get("category", "non-functional"),
                prd_section_ref="non_functional_requirements",
            )
            session.add(req)
            requirements.append(req)

        await session.flush()

        logger.info(
            "requirements_extracted",
            spec_id=spec.id,
            count=len(requirements),
        )
        return requirements


# ─── D-05: Spec Validation ───────────────────────────────────────────────────────

class SpecValidator:
    """
    Multi-layer spec validation: schema conformance, completeness,
    contradiction detection, and semantic quality scoring.
    """

    @classmethod
    async def validate(cls, spec: StructuredSpec, session) -> dict[str, Any]:
        """
        Run all validations on a spec. Returns comprehensive report.
        """
        content = spec.content
        report = {
            "spec_id": spec.id,
            "version": spec.version,
            "checks": {},
            "overall_score": 0.0,
            "blocking_issues": [],
            "warnings": [],
        }

        # 1. Schema validation
        schema_result = cls._validate_schema(content)
        report["checks"]["schema"] = schema_result

        # 2. Completeness check
        completeness_result = cls._check_completeness(content)
        report["checks"]["completeness"] = completeness_result

        # 3. Contradiction detection
        contradiction_result = cls._detect_contradictions(content)
        report["checks"]["contradictions"] = contradiction_result

        # 4. Semantic quality scoring
        quality_result = cls._score_quality(content)
        report["checks"]["quality"] = quality_result

        # Calculate overall score
        scores = [
            schema_result.get("score", 0),
            completeness_result.get("score", 0),
            1.0 - min(contradiction_result.get("contradiction_count", 0) * 0.2, 1.0),
            quality_result.get("score", 0),
        ]
        report["overall_score"] = round(sum(scores) / len(scores), 2)

        # Update spec with validation results
        spec.completeness_score = completeness_result.get("score", 0)
        spec.quality_score = report["overall_score"]
        spec.contradiction_count = contradiction_result.get("contradiction_count", 0)
        spec.contradiction_details = contradiction_result.get("details", None)

        # Check against policy thresholds
        policy = get_policy_manager()
        min_score = policy.get("spec_validation", "min_completeness_score", 0.7)
        max_contradictions = policy.get("spec_validation", "max_contradictions", 3)

        if report["overall_score"] < min_score:
            report["blocking_issues"].append(
                f"Overall score {report['overall_score']} below threshold {min_score}"
            )
        if spec.contradiction_count > max_contradictions:
            report["blocking_issues"].append(
                f"Found {spec.contradiction_count} contradictions (max: {max_contradictions})"
            )

        # Determine if human review is needed
        human_threshold = policy.get("spec_validation", "human_review_threshold", 0.5)
        spec.human_review_required = report["overall_score"] < human_threshold

        passed = len(report["blocking_issues"]) == 0
        if passed:
            spec.status = SpecStatus.VALIDATED
        else:
            spec.status = SpecStatus.DRAFT  # Needs rework

        report["passed"] = passed

        logger.info(
            "spec_validated",
            spec_id=spec.id,
            score=report["overall_score"],
            passed=passed,
            blocking_issues=len(report["blocking_issues"]),
        )
        return report

    @staticmethod
    def _validate_schema(content: dict) -> dict:
        """Verify spec conforms to expected schema structure."""
        required_fields = ["title", "overview", "functional_requirements"]
        missing = [f for f in required_fields if f not in content or not content[f]]
        score = 1.0 - (len(missing) * 0.3)

        return {
            "passed": len(missing) == 0,
            "score": max(score, 0),
            "missing_fields": missing,
        }

    @staticmethod
    def _check_completeness(content: dict) -> dict:
        """Check all requirements have acceptance criteria and all fields are populated."""
        issues = []
        total_checks = 0
        passed_checks = 0

        for req_type in ["functional_requirements", "non_functional_requirements"]:
            for req in content.get(req_type, []):
                total_checks += 1
                if req.get("acceptance_criteria"):
                    passed_checks += 1
                else:
                    issues.append(f"{req.get('id', '?')}: missing acceptance criteria")

        # Check API endpoints have schemas
        for endpoint in content.get("api_endpoints", []):
            total_checks += 1
            if endpoint.get("response_schema"):
                passed_checks += 1
            else:
                issues.append(f"{endpoint.get('method', '?')} {endpoint.get('path', '?')}: missing response schema")

        score = passed_checks / max(total_checks, 1)

        return {
            "passed": score >= 0.8,
            "score": round(score, 2),
            "issues": issues,
            "checks_passed": passed_checks,
            "checks_total": total_checks,
        }

    @staticmethod
    def _detect_contradictions(content: dict) -> dict:
        """Detect contradictory requirements using semantic similarity."""
        contradictions = []
        all_reqs = []

        for req_type in ["functional_requirements", "non_functional_requirements"]:
            for req in content.get(req_type, []):
                all_reqs.append(req)

        # Pairwise comparison for contradictions
        for i, req_a in enumerate(all_reqs):
            for j, req_b in enumerate(all_reqs[i + 1:], i + 1):
                desc_a = req_a.get("description", "").lower()
                desc_b = req_b.get("description", "").lower()

                # Check for potential contradictions via keyword analysis
                contradiction_pairs = [
                    ("required", "optional"),
                    ("must", "must not"),
                    ("always", "never"),
                    ("synchronous", "asynchronous"),
                    ("public", "private"),
                    ("allow", "deny"),
                    ("enable", "disable"),
                ]

                for pos, neg in contradiction_pairs:
                    if pos in desc_a and neg in desc_b:
                        similarity = SequenceMatcher(None, desc_a, desc_b).ratio()
                        if similarity > 0.3:  # Related enough to be a contradiction
                            contradictions.append({
                                "req_a": req_a.get("id"),
                                "req_b": req_b.get("id"),
                                "reason": f"Potential conflict: '{pos}' vs '{neg}'",
                                "similarity": round(similarity, 2),
                            })

        return {
            "contradiction_count": len(contradictions),
            "details": contradictions if contradictions else None,
        }

    @staticmethod
    def _score_quality(content: dict) -> dict:
        """Score spec quality based on clarity and specificity."""
        vague_terms = [
            "should", "might", "could", "various", "etc", "appropriate",
            "adequate", "reasonable", "some", "probably", "maybe",
        ]

        total_text = ""
        for key in ["overview", "constraints", "assumptions"]:
            val = content.get(key, "")
            if isinstance(val, str):
                total_text += " " + val
            elif isinstance(val, list):
                total_text += " " + " ".join(str(v) for v in val)

        for req_type in ["functional_requirements", "non_functional_requirements"]:
            for req in content.get(req_type, []):
                total_text += " " + req.get("description", "")
                total_text += " " + req.get("acceptance_criteria", "")

        total_text = total_text.lower()
        words = total_text.split()
        vague_count = sum(1 for w in words if w.strip(".,;:") in vague_terms)
        vague_ratio = vague_count / max(len(words), 1)

        # Penalize vagueness
        score = max(1.0 - (vague_ratio * 10), 0.3)

        # Bonus for having structured elements
        if content.get("api_endpoints"):
            score = min(score + 0.1, 1.0)
        if content.get("data_models"):
            score = min(score + 0.1, 1.0)
        if content.get("constraints"):
            score = min(score + 0.05, 1.0)

        return {
            "score": round(score, 2),
            "vague_term_count": vague_count,
            "vague_ratio": round(vague_ratio, 3),
            "word_count": len(words),
        }


# ─── D-06: Spec Versioning & Diff Tracking ───────────────────────────────────────

class SpecVersionManager:
    """Manages spec versions with immutable history and diff comparison."""

    @staticmethod
    async def get_version_history(prd_id: str, session) -> list[dict]:
        """Get all versions of a spec for a given PRD."""
        result = await session.execute(
            select(StructuredSpec)
            .where(StructuredSpec.prd_id == prd_id)
            .order_by(StructuredSpec.version)
        )
        specs = result.scalars().all()
        return [
            {
                "spec_id": s.id,
                "version": s.version,
                "status": s.status,
                "quality_score": s.quality_score,
                "completeness_score": s.completeness_score,
                "contradiction_count": s.contradiction_count,
                "created_at": s.created_at.isoformat(),
            }
            for s in specs
        ]

    @staticmethod
    def diff_specs(spec_a_content: dict, spec_b_content: dict) -> dict:
        """
        Compare two spec versions and return a structured diff.
        """
        diff = {
            "added_requirements": [],
            "removed_requirements": [],
            "modified_requirements": [],
            "added_endpoints": [],
            "removed_endpoints": [],
            "other_changes": [],
        }

        # Compare requirements
        reqs_a = {r.get("id"): r for r in spec_a_content.get("functional_requirements", [])}
        reqs_b = {r.get("id"): r for r in spec_b_content.get("functional_requirements", [])}

        for rid in reqs_b:
            if rid not in reqs_a:
                diff["added_requirements"].append(reqs_b[rid])
            elif reqs_b[rid] != reqs_a[rid]:
                diff["modified_requirements"].append({
                    "id": rid,
                    "before": reqs_a[rid],
                    "after": reqs_b[rid],
                })

        for rid in reqs_a:
            if rid not in reqs_b:
                diff["removed_requirements"].append(reqs_a[rid])

        # Compare endpoints
        eps_a = {f"{e.get('method')} {e.get('path')}": e for e in spec_a_content.get("api_endpoints", [])}
        eps_b = {f"{e.get('method')} {e.get('path')}": e for e in spec_b_content.get("api_endpoints", [])}

        for key in eps_b:
            if key not in eps_a:
                diff["added_endpoints"].append(eps_b[key])
        for key in eps_a:
            if key not in eps_b:
                diff["removed_endpoints"].append(eps_a[key])

        # Compare top-level fields
        for field in ["title", "overview", "constraints", "assumptions", "out_of_scope"]:
            if spec_a_content.get(field) != spec_b_content.get(field):
                diff["other_changes"].append({
                    "field": field,
                    "changed": True,
                })

        return diff
