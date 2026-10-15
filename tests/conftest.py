"""
Pytest configuration and shared fixtures for 5-table event architecture.
"""

import pytest
import pytest_asyncio
from backend.database import engine, Base
from backend.models.violation import Vehicle, Event, EventImage, Violation, NotificationLog  # noqa: F401


@pytest_asyncio.fixture(scope="session", autouse=True)
async def setup_test_db():
    """Ensure all 5 database tables are created before tests run."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
