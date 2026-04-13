"""
test_agents.py — Unit tests for agents.py
==========================================
Task: V-01
Tests agent registry, base agent utilities, and all 4 agent implementations in mock mode.
"""

import pytest
import json


class TestAgentRegistry:
    """Tests for AgentRegistry."""

    def test_list_agents(self):
        from agents import AgentRegistry
        agents = AgentRegistry.list_agents()
        assert "api_designer" in agents
        assert "logic_implementer" in agents
        assert "test_generator" in agents
        assert "spec_generator" in agents

    def test_get_valid_agent(self):
        from agents import AgentRegistry
        from models import AgentType
        agent = AgentRegistry.get(AgentType.API_DESIGNER)
        assert agent is not None
        assert agent.agent_type == "api_designer"

    def test_get_invalid_agent_raises(self):
        from agents import AgentRegistry
        with pytest.raises(ValueError, match="Unknown agent type"):
            AgentRegistry.get("nonexistent_agent")


class TestBaseAgentUtilities:
    """Tests for BaseAgent helper methods."""

    def test_extract_json_from_code_block(self):
        from agents import AgentRegistry
        from models import AgentType
        agent = AgentRegistry.get(AgentType.API_DESIGNER)
        text = '```json\n{"key": "value"}\n```'
        result = agent._extract_json(text)
        assert result == {"key": "value"}

    def test_extract_json_plain(self):
        from agents import AgentRegistry
        from models import AgentType
        agent = AgentRegistry.get(AgentType.API_DESIGNER)
        result = agent._extract_json('{"a": 1}')
        assert result == {"a": 1}

    def test_extract_code_from_block(self):
        from agents import AgentRegistry
        from models import AgentType
        agent = AgentRegistry.get(AgentType.LOGIC_IMPLEMENTER)
        text = '```python\nprint("hello")\n```'
        result = agent._extract_code(text, "python")
        assert result == 'print("hello")'

    def test_extract_code_plain(self):
        from agents import AgentRegistry
        from models import AgentType
        agent = AgentRegistry.get(AgentType.LOGIC_IMPLEMENTER)
        result = agent._extract_code('print("hello")', "python")
        assert result == 'print("hello")'

    def test_sanitize_input_truncates_long_strings(self):
        from agents import AgentRegistry
        from models import AgentType
        agent = AgentRegistry.get(AgentType.API_DESIGNER)
        long_string = "x" * 2000
        result = agent._sanitize_input({"content": long_string})
        assert len(result["content"]) < 2000
        assert "truncated" in result["content"]

    def test_sanitize_input_keeps_short_strings(self):
        from agents import AgentRegistry
        from models import AgentType
        agent = AgentRegistry.get(AgentType.API_DESIGNER)
        result = agent._sanitize_input({"key": "short"})
        assert result["key"] == "short"


class TestAPIDesignerAgent:
    """Tests for APIDesignerAgent (mock mode)."""

    @pytest.mark.asyncio
    async def test_run_produces_openapi(self, db_session, prd_factory, workflow_factory):
        from agents import AgentRegistry
        from models import AgentType
        prd = await prd_factory.create(db_session)
        wf = await workflow_factory.create(db_session, prd_id=prd.id)

        agent = AgentRegistry.get(AgentType.API_DESIGNER)
        result = await agent.execute(
            {"spec_content": {"title": "Test"}, "workflow_id": wf.id},
            wf.id,
            db_session,
        )
        assert result.success is True
        assert result.output_data is not None
        assert "contract" in result.output_data
        contract = result.output_data["contract"]
        assert "openapi" in contract
        assert "paths" in contract


class TestLogicImplementerAgent:
    """Tests for LogicImplementerAgent (mock mode)."""

    @pytest.mark.asyncio
    async def test_run_produces_valid_python(self, db_session, prd_factory, workflow_factory):
        from agents import AgentRegistry
        from models import AgentType
        import ast

        prd = await prd_factory.create(db_session)
        wf = await workflow_factory.create(db_session, prd_id=prd.id)

        agent = AgentRegistry.get(AgentType.LOGIC_IMPLEMENTER)
        result = await agent.execute(
            {"spec_content": {"functional_requirements": []}, "api_contract": {}, "workflow_id": wf.id},
            wf.id,
            db_session,
        )
        assert result.success is True
        output = result.output_data
        assert output["syntax_valid"] is True
        assert output["line_count"] > 0


class TestTestGeneratorAgent:
    """Tests for TestGeneratorAgent (mock mode)."""

    @pytest.mark.asyncio
    async def test_run_produces_test_code(self, db_session, prd_factory, workflow_factory):
        from agents import AgentRegistry
        from models import AgentType

        prd = await prd_factory.create(db_session)
        wf = await workflow_factory.create(db_session, prd_id=prd.id)

        agent = AgentRegistry.get(AgentType.TEST_GENERATOR)
        result = await agent.execute(
            {"spec_content": {"functional_requirements": []}, "code_content": "", "workflow_id": wf.id},
            wf.id,
            db_session,
        )
        assert result.success is True
        assert result.output_data["test_count"] > 0
        assert result.output_data["syntax_valid"] is True


class TestSpecGeneratorAgent:
    """Tests for SpecGeneratorAgent (mock mode)."""

    @pytest.mark.asyncio
    async def test_run_generates_spec(self, db_session, prd_factory, workflow_factory):
        from agents import AgentRegistry
        from models import AgentType

        prd = await prd_factory.create(db_session)
        wf = await workflow_factory.create(db_session, prd_id=prd.id)

        agent = AgentRegistry.get(AgentType.SPEC_GENERATOR)
        result = await agent.execute(
            {"prd_id": prd.id},
            wf.id,
            db_session,
        )
        assert result.success is True
        assert "spec_id" in result.output_data
        assert result.output_data["quality_score"] is not None
