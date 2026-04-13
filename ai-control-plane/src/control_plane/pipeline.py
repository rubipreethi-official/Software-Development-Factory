"""
pipeline.py — Main Orchestration Flow
======================================
Role in pipeline: Central workflow runner.
Takes PRD -> Spec -> Code -> Tests.
Handles all MongoDB persistence and WebSocket broadcasting.

Depends on: agents, models/schema, API WebSocket
"""
import asyncio
import logging
from datetime import datetime
from src.config.database import get_db
from src.models.schema import ExecutionDocument, PRDDocument, PipelineStatus, ArtifactDocument
from src.agents.base_agent import BaseAgent
from src.api.websocket import manager

logger = logging.getLogger(__name__)

# Specialized agents initialized (Tier mapping in BaseAgent handled internally)
spec_agent = BaseAgent("SpecGeneratorAgent", "You are an expert technical product manager. Convert the user's PRD into a detailed structured technical specification.", "tier1")
code_agent = BaseAgent("CodeGeneratorAgent", "You are a senior software engineer. Write the code implementing the provided specification.", "tier1")
test_agent = BaseAgent("TestGeneratorAgent", "You are a QA automation engineer. Write tests for the provided code and specification.", "tier2_code")

async def run_pipeline(prd_id: str, execution_id: str, raw_text: str):
    """
    Executes the autonomous pipeline safely parsing through all gates.
    Streams events via WebSocket to the frontend dashboard.
    """
    db = get_db()
    
    async def update_stage(stage: str, status: str, message: str, tokens_in: int = 0, tokens_out: int = 0, latency_ms: int = 0):
        # Notify UI
        await manager.broadcast({
            "stage": stage,
            "status": status,
            "message": message,
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
            "latency_ms": latency_ms
        })
        # Persist Stage
        await db["executions"].update_one(
            {"id": execution_id},
            {"$set": {
                "current_stage": stage,
                "status": status if status in ["failed", "complete"] else "pending",
                "updated_at": datetime.utcnow()
            }}
        )

    try:
        # ---- 1: SPEC GENERATION ----
        await update_stage("spec_generation", "running", "Analyzing PRD requirements...")
        spec_content = await spec_agent.execute(f"Analyze this PRD and output a structured specification JSON/Markdown:\n{raw_text}")
        
        # Save Artifact
        spec_doc = ArtifactDocument(
            execution_id=execution_id,
            artifact_type="spec",
            content=spec_content,
            agent_id=spec_agent.agent_id,
            model_used=spec_agent.model,
            tokens_in=spec_agent.total_tokens_in,
            tokens_out=spec_agent.total_tokens_out
        )
        await db["artifacts"].insert_one(spec_doc.model_dump())
        await manager.broadcast({"stage": "spec_generation", "status": "complete", "artifact": spec_content})
        
        await asyncio.sleep(1.5) # Rate limiting buffer

        # ---- 2: CODE GENERATION ----
        await update_stage("code_generation", "running", "Designing API architecture and coding...")
        code_content = await code_agent.execute(f"Implement this specification:\n{spec_content}")
        
        code_doc = ArtifactDocument(
            execution_id=execution_id,
            artifact_type="code",
            content=code_content,
            agent_id=code_agent.agent_id,
            model_used=code_agent.model,
            tokens_in=code_agent.total_tokens_in,
            tokens_out=code_agent.total_tokens_out
        )
        await db["artifacts"].insert_one(code_doc.model_dump())
        await manager.broadcast({"stage": "code_generation", "status": "complete", "artifact": code_content})
        
        await asyncio.sleep(1.5)

        # ---- 3: TEST GENERATION ----
        await update_stage("test_generation", "running", "Writing test suites...")
        test_content = await test_agent.execute(f"Write tests for the following code and spec.\nCode: {code_content}\nSpec: {spec_content}")
        
        test_doc = ArtifactDocument(
            execution_id=execution_id,
            artifact_type="tests",
            content=test_content,
            agent_id=test_agent.agent_id,
            model_used=test_agent.model,
            tokens_in=test_agent.total_tokens_in,
            tokens_out=test_agent.total_tokens_out
        )
        await db["artifacts"].insert_one(test_doc.model_dump())
        await manager.broadcast({"stage": "test_generation", "status": "complete", "artifact": test_content})

        # ---- COMPLETION ----
        await update_stage("pipeline", "complete", "Factory execution completed successfully.")
        await db["executions"].update_one(
            {"id": execution_id},
            {"$set": {"status": "complete", "updated_at": datetime.utcnow()}}
        )

    except Exception as e:
        logger.error(f"Pipeline error: {e}")
        await update_stage(stage="pipeline", status="error", message=str(e))
        await db["executions"].update_one(
            {"id": execution_id},
            {"$set": {"status": "failed", "error": str(e), "updated_at": datetime.utcnow()}}
        )
