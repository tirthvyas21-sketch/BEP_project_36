"""
Smart Traffic Violation Detection System – Application Entry Point.

Group 36 | PC122 Project
FastAPI app implementing 5-table event-driven architecture with human review.
"""

from pathlib import Path
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from backend.config import settings
from backend.database import init_db
from backend.routers import events, vehicles, dashboard, health


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup / shutdown lifecycle handler."""
    await init_db()
    yield


app = FastAPI(
    title="Smart Traffic Violation Detection System",
    description=(
        "PC122 Project: Event-driven restricted-turn violation detection pipeline "
        "featuring multi-image support, plate recognition, human review, and idempotent notifications."
    ),
    version="0.3.0",
    lifespan=lifespan,
)

# Ensure local directories exist
Path("backend/static").mkdir(parents=True, exist_ok=True)
Path(settings.CAPTURES_DIR).mkdir(parents=True, exist_ok=True)
Path("./data").mkdir(parents=True, exist_ok=True)

# Static and captured image serving
app.mount("/static", StaticFiles(directory="backend/static"), name="static")
app.mount("/captures", StaticFiles(directory=settings.CAPTURES_DIR), name="captures")

# Core Routers
app.include_router(health.router, tags=["Health"])
app.include_router(events.router, prefix="/api/v1/events", tags=["Events"])
app.include_router(vehicles.router, prefix="/api/v1/vehicles", tags=["Vehicles"])
app.include_router(dashboard.router, tags=["Dashboard"])
