"""
test_validation.py — Unit tests for validation.py
===================================================
Task: V-01
Tests contract validation, integration testing, trajectory evaluation,
and validation gates.
"""

import pytest
import json


class TestContractValidator:
    """Tests for ContractValidator."""

    @pytest.mark.asyncio
    async def test_valid_contract_passes(self, db_session, prd_factory, workflow_factory):
        from validation import ContractValidator
        prd = await prd_factory.create(db_session)
        wf = await workflow_factory.create(db_session, prd_id=prd.id)

        contract = {
            "openapi": "3.0.3",
            "info": {"title": "Test API", "version": "1.0.0"},
            "paths": {
                "/api/v1/health": {
                    "get": {
                        "summary": "Health check",
                        "responses": {"200": {"description": "OK"}},
                    }
                }
            },
            "components": {"schemas": {}},
        }
        result = await ContractValidator.validate_contract(contract, wf.id, db_session)
        assert result.passed is True
        assert result.score > 0

    @pytest.mark.asyncio
    async def test_missing_openapi_field_fails(self, db_session, prd_factory, workflow_factory):
        from validation import ContractValidator
        prd = await prd_factory.create(db_session)
        wf = await workflow_factory.create(db_session, prd_id=prd.id)

        contract = {"info": {"title": "Test"}, "paths": {"/test": {"get": {"responses": {"200": {"description": "OK"}}}}}}
        result = await ContractValidator.validate_contract(contract, wf.id, db_session)
        assert result.passed is False

    @pytest.mark.asyncio
    async def test_empty_paths_fails(self, db_session, prd_factory, workflow_factory):
        from validation import ContractValidator
        prd = await prd_factory.create(db_session)
        wf = await workflow_factory.create(db_session, prd_id=prd.id)

        contract = {"openapi": "3.0.3", "info": {"title": "T"}, "paths": {}}
        result = await ContractValidator.validate_contract(contract, wf.id, db_session)
        assert result.passed is False


class TestIntegrationTester:
    """Tests for IntegrationTester."""

    @pytest.mark.asyncio
    async def test_run_with_matching_routes(self, db_session, prd_factory, workflow_factory):
        from validation import IntegrationTester
        prd = await prd_factory.create(db_session)
        wf = await workflow_factory.create(db_session, prd_id=prd.id)

        code = '''
from fastapi import APIRouter, HTTPException
router = APIRouter()

@router.get("/api/v1/health")
async def health():
    return {"status": "ok"}

@router.post("/api/v1/resources")
async def create_resource(data: dict) -> dict:
    raise HTTPException(status_code=400, detail="Not implemented")
'''
        contract = {
            "paths": {
                "/api/v1/health": {"get": {}},
                "/api/v1/resources": {"post": {}},
            }
        }
        result = await IntegrationTester.run_integration_tests(
            code, contract, wf.id, db_session
        )
        assert result.passed is True
        assert result.score > 0


class TestTrajectoryEvaluator:
    """Tests for TrajectoryEvaluator."""

    @pytest.mark.asyncio
    async def test_evaluate_complete_trace(self, db_session, prd_factory, workflow_factory):
        from validation import TrajectoryEvaluator
        prd = await prd_factory.create(db_session)
        wf = await workflow_factory.create(db_session, prd_id=prd.id)

        trace_data = [
            {"component": "spec_generator", "event_type": "generate", "status": "success", "output": {"spec_id": "123"}},
            {"component": "api_designer", "event_type": "design", "status": "success", "output": {}},
            {"component": "logic_implementer", "event_type": "implement", "status": "success", "output": {}},
            {"component": "test_generator", "event_type": "generate_tests", "status": "success", "output": {}},
        ]
        spec_content = {"functional_requirements": [{"id": "REQ-001", "description": "Test"}]}

        result = await TrajectoryEvaluator.evaluate(
            trace_data, spec_content, wf.id, db_session
        )
        assert result.score >= 0
        assert result.score <= 1.0

    @pytest.mark.asyncio
    async def test_evaluate_with_failures(self, db_session, prd_factory, workflow_factory):
        from validation import TrajectoryEvaluator
        prd = await prd_factory.create(db_session)
        wf = await workflow_factory.create(db_session, prd_id=prd.id)

        trace_data = [
            {"component": "spec_generator", "event_type": "generate", "status": "error", "output": None},
        ]
        result = await TrajectoryEvaluator.evaluate(
            trace_data, {"functional_requirements": []}, wf.id, db_session
        )
        assert result.findings is not None


class TestValidationGate:
    """Tests for ValidationGate."""

    @pytest.mark.asyncio
    async def test_gate_passes_all_valid(self, db_session, prd_factory, workflow_factory):
        from validation import ValidationGate, ContractValidator
        prd = await prd_factory.create(db_session)
        wf = await workflow_factory.create(db_session, prd_id=prd.id)

        # Create a passing validation result
        contract = {
            "openapi": "3.0.3",
            "info": {"title": "Test", "version": "1.0.0"},
            "paths": {"/test": {"get": {"responses": {"200": {"description": "OK"}}}}},
            "components": {"schemas": {}},
        }
        vr = await ContractValidator.validate_contract(contract, wf.id, db_session)

        gate = ValidationGate("contract_validation")
        decision = await gate.evaluate([vr], wf.id, db_session)
        assert decision["passed"] is True
        assert decision["should_block"] is False

    @pytest.mark.asyncio
    async def test_gate_override(self, db_session, prd_factory, workflow_factory):
        from validation import ValidationGate
        prd = await prd_factory.create(db_session)
        wf = await workflow_factory.create(db_session, prd_id=prd.id)

        override = await ValidationGate.override_gate(
            workflow_id=wf.id,
            gate_name="test_gate",
            reason="Testing override",
            approved_by="test_user",
            original_result={"passed": False},
            session=db_session,
        )
        await db_session.flush()
        assert override.id is not None
        assert override.approved_by == "test_user"
        assert override.gate_name == "test_gate"


class TestGateRegistry:
    """Tests for GateRegistry."""

    def test_get_known_gate(self):
        from validation import GateRegistry
        gate = GateRegistry.get_gate("contract_validation")
        assert gate.gate_name == "contract_validation"

    def test_get_unknown_gate_raises(self):
        from validation import GateRegistry
        with pytest.raises(ValueError, match="Unknown gate"):
            GateRegistry.get_gate("nonexistent_gate")

    def test_get_gates_for_position(self):
        from validation import GateRegistry
        gates = GateRegistry.get_gates_for_position("after_api_design")
        assert len(gates) >= 1
