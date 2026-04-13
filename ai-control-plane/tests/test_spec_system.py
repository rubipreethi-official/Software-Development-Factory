"""
test_spec_system.py — Unit tests for spec_system.py
=====================================================
Task: V-01
Tests PRD processing, spec generation, requirement extraction,
validation, and versioning.
"""

import pytest
import json


class TestPRDProcessor:
    """Tests for PRDProcessor."""

    def test_preprocess_normalizes_whitespace(self):
        from spec_system import PRDProcessor
        raw = "Hello\r\n\r\n\r\nWorld\r\n"
        result = PRDProcessor.preprocess(raw)
        assert "\r\n" not in result
        assert "\n\n\n" not in result

    def test_preprocess_strips_text(self):
        from spec_system import PRDProcessor
        result = PRDProcessor.preprocess("  hello  ")
        assert result == "hello"

    def test_extract_metadata_word_count(self):
        from spec_system import PRDProcessor
        meta = PRDProcessor.extract_metadata("one two three four five")
        assert meta["word_count"] == 5

    def test_extract_metadata_sections(self):
        from spec_system import PRDProcessor
        text = "# Title\n## Requirements\n- Item\n## Security\n- Rule"
        meta = PRDProcessor.extract_metadata(text)
        assert meta["has_sections"] is True
        assert meta["has_bullet_points"] is True
        assert "requirements" in meta["sections_found"]
        assert "security" in meta["sections_found"]

    def test_validate_rejects_short_prd(self):
        from spec_system import PRDProcessor
        is_valid, warnings = PRDProcessor.validate_prd("too short")
        assert is_valid is False
        assert any("too short" in w for w in warnings)

    def test_validate_accepts_long_prd(self):
        from spec_system import PRDProcessor
        long_text = "word " * 50
        is_valid, _ = PRDProcessor.validate_prd(long_text)
        assert is_valid is True

    @pytest.mark.asyncio
    async def test_ingest_stores_prd(self, db_session):
        from spec_system import PRDProcessor
        prd = await PRDProcessor.ingest(
            title="Test PRD",
            raw_content=(
                "# Test PRD\n\n## Overview\n"
                "This is a valid PRD document with enough words to pass the minimum "
                "threshold for validation testing. It includes an overview section "
                "and requirements that describe what the system should do in detail."
            ),
            session=db_session,
        )
        assert prd.id is not None
        assert prd.status in ("validated", "submitted")
        assert prd.word_count > 0

    @pytest.mark.asyncio
    async def test_ingest_rejects_invalid(self, db_session):
        from spec_system import PRDProcessor
        prd = await PRDProcessor.ingest(
            title="Bad",
            raw_content="short",
            session=db_session,
        )
        assert prd.status == "rejected"


class TestSpecGenerator:
    """Tests for SpecGenerator (mock mode)."""

    @pytest.mark.asyncio
    async def test_generate_mock_spec(self, db_session, prd_factory):
        from spec_system import SpecGenerator
        prd = await prd_factory.create(db_session)
        spec = await SpecGenerator.generate(prd, db_session)

        assert spec.id is not None
        assert spec.prd_id == prd.id
        assert spec.version == 1
        assert isinstance(spec.content, dict)
        assert "title" in spec.content
        assert "functional_requirements" in spec.content
        assert len(spec.content["functional_requirements"]) > 0

    @pytest.mark.asyncio
    async def test_generate_detects_auth_keywords(self, db_session, prd_factory):
        from spec_system import SpecGenerator
        prd = await prd_factory.create(
            db_session,
            raw_content="Build an authentication API with JWT login, user registration, and password hashing."
        )
        spec = await SpecGenerator.generate(prd, db_session)
        content = spec.content
        # Should detect auth keywords and generate auth-related requirements
        req_descriptions = [r["description"].lower() for r in content.get("functional_requirements", [])]
        has_auth_req = any("registration" in d or "login" in d or "auth" in d for d in req_descriptions)
        assert has_auth_req


class TestRequirementExtractor:
    """Tests for RequirementExtractor."""

    @pytest.mark.asyncio
    async def test_extract_and_store(self, db_session, prd_factory, spec_factory):
        from spec_system import RequirementExtractor
        prd = await prd_factory.create(db_session)
        spec = await spec_factory.create(db_session, prd_id=prd.id)
        reqs = await RequirementExtractor.extract_and_store(spec, db_session)
        assert len(reqs) >= 1
        assert reqs[0].spec_id == spec.id
        assert reqs[0].requirement_id.startswith("REQ-")


class TestSpecValidator:
    """Tests for SpecValidator."""

    @pytest.mark.asyncio
    async def test_validate_good_spec(self, db_session, prd_factory, spec_factory):
        from spec_system import SpecValidator
        prd = await prd_factory.create(db_session)
        spec = await spec_factory.create(db_session, prd_id=prd.id)
        report = await SpecValidator.validate(spec, db_session)

        assert "overall_score" in report
        assert report["overall_score"] > 0
        assert "checks" in report
        assert "schema" in report["checks"]

    @pytest.mark.asyncio
    async def test_validate_empty_spec_scores_low(self, db_session, prd_factory, spec_factory):
        from spec_system import SpecValidator
        prd = await prd_factory.create(db_session)
        spec = await spec_factory.create(
            db_session,
            prd_id=prd.id,
            content={"title": "", "overview": "", "functional_requirements": []},
        )
        report = await SpecValidator.validate(spec, db_session)
        assert report["overall_score"] < 0.8


class TestSpecVersionManager:
    """Tests for SpecVersionManager."""

    def test_diff_specs_detects_added_requirement(self):
        from spec_system import SpecVersionManager
        spec_a = {"functional_requirements": [], "api_endpoints": []}
        spec_b = {
            "functional_requirements": [
                {"id": "REQ-001", "description": "New requirement"}
            ],
            "api_endpoints": [],
        }
        diff = SpecVersionManager.diff_specs(spec_a, spec_b)
        assert len(diff["added_requirements"]) == 1
        assert diff["added_requirements"][0]["id"] == "REQ-001"

    def test_diff_specs_detects_removed_requirement(self):
        from spec_system import SpecVersionManager
        spec_a = {
            "functional_requirements": [
                {"id": "REQ-001", "description": "Old requirement"}
            ],
            "api_endpoints": [],
        }
        spec_b = {"functional_requirements": [], "api_endpoints": []}
        diff = SpecVersionManager.diff_specs(spec_a, spec_b)
        assert len(diff["removed_requirements"]) == 1

    def test_diff_specs_no_changes(self):
        from spec_system import SpecVersionManager
        spec = {"functional_requirements": [{"id": "REQ-001", "description": "Same"}], "api_endpoints": []}
        diff = SpecVersionManager.diff_specs(spec, spec)
        assert len(diff["added_requirements"]) == 0
        assert len(diff["removed_requirements"]) == 0
        assert len(diff["modified_requirements"]) == 0
