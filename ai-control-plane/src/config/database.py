"""
Async MongoDB connection via Motor driver.

Role in pipeline: Data persistence layer for all factory entities.
Motor is the async version of pymongo — identical API, non-blocking I/O.
Connection is a singleton — one client for the entire app lifetime.

Depends on: MONGODB_URI and MONGODB_DB_NAME env vars
Used by: all repositories, health check endpoint
"""
import os
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from dotenv import load_dotenv
import logging

load_dotenv()
logger = logging.getLogger(__name__)

_client: AsyncIOMotorClient = None
_db: AsyncIOMotorDatabase = None

async def connect_db() -> None:
    """
    Initialize MongoDB connection on app startup.
    Called once in FastAPI lifespan context manager.
    Fails loud if MONGODB_URI is missing — no silent failures.
    """
    global _client, _db
    uri = os.getenv("MONGODB_URI")
    db_name = os.getenv("MONGODB_DB_NAME", "software_factory")

    if not uri:
        raise RuntimeError("MONGODB_URI not set in .env")

    _client = AsyncIOMotorClient(uri)
    _db = _client[db_name]

    # Verify connection is actually alive
    await _client.admin.command("ping")
    logger.info(f"MongoDB connected: {db_name}")

async def disconnect_db() -> None:
    """Close MongoDB connection on app shutdown."""
    global _client
    if _client:
        _client.close()
        logger.info("MongoDB disconnected")

def get_db() -> AsyncIOMotorDatabase:
    """
    FastAPI dependency: returns the active database instance.
    Raises RuntimeError if called before connect_db().
    """
    if _db is None:
        raise RuntimeError("Database not initialized. Call connect_db() first.")
    return _db
