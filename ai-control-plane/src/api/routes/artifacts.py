from fastapi import APIRouter, HTTPException
from src.config.database import get_db

router = APIRouter()

@router.get("/api/v1/executions/{execution_id}/artifacts", tags=["Artifacts"])
async def get_execution_artifacts(execution_id: str):
    """Retrieve all artifacts for a given execution."""
    db = get_db()
    cursor = db["artifacts"].find({"execution_id": execution_id})
    artifacts = await cursor.to_list(length=100)
    
    # Strip internally generated Mongo ID strictly for schema compliance if needed,
    # or format list of dicts.
    return {
        "execution_id": execution_id,
        "artifacts": [
             {
                 "id": a["id"],
                 "type": a["artifact_type"],
                 "content": a["content"],
                 "model": a["model_used"]
             }
             for a in artifacts
        ]
    }
