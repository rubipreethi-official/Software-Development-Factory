from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from src.config.database import connect_db, disconnect_db
from src.api.routes import health, pipeline, artifacts

@asynccontextmanager
async def lifespan(app: FastAPI):
    await connect_db()      # runs on startup
    yield
    await disconnect_db()   # runs on shutdown

app = FastAPI(
    title="Software Development Factory",
    version="1.0.0",
    lifespan=lifespan
)

app.include_router(health.router)
app.include_router(pipeline.router)
app.include_router(artifacts.router)

import os
os.makedirs("frontend", exist_ok=True)
app.mount("/", StaticFiles(directory="frontend", html=True), name="static")
