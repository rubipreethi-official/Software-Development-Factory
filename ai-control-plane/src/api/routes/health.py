from fastapi import APIRouter
from src.config.database import get_db

router = APIRouter()

@router.get("/health")
async def health_check():
    try:
        db = get_db()
        await db.command("ping")
        return {"status": "ok", "database": "mongodb", "connected": True}
    except Exception as e:
        return {"status": "error", "database": "mongodb", "error": str(e)}
