"""
Dashboard Router – Serves the HTML Web Dashboard.

Provides reviewers with an incident queue, metrics, image previews,
and single-click confirm/reject verification.
"""

from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.database import get_db
from backend.models.violation import (
    Event,
    Vehicle,
    Violation,
    NotificationLog,
    ReviewStatus,
)

router = APIRouter()
templates = Jinja2Templates(directory="backend/templates")


@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request, db: AsyncSession = Depends(get_db)):
    """Render the incident review dashboard."""
    # Summary statistics
    total_events_res = await db.execute(select(func.count(Event.id)))
    total_events = total_events_res.scalar_one()

    awaiting_review_res = await db.execute(
        select(func.count(Violation.id)).where(Violation.review_status == ReviewStatus.PENDING_REVIEW)
    )
    awaiting_review = awaiting_review_res.scalar_one()

    confirmed_res = await db.execute(
        select(func.count(Violation.id)).where(Violation.review_status == ReviewStatus.CONFIRMED)
    )
    confirmed_violations = confirmed_res.scalar_one()

    total_vehicles_res = await db.execute(select(func.count(Vehicle.id)))
    total_vehicles = total_vehicles_res.scalar_one()

    # Recent events (with images, violation, and vehicle eager loaded)
    events_stmt = (
        select(Event)
        .options(
            selectinload(Event.images),
            selectinload(Event.violation).selectinload(Violation.vehicle),
            selectinload(Event.notifications),
        )
        .order_by(Event.timestamp.desc())
        .limit(25)
    )
    events_res = await db.execute(events_stmt)
    events_list = events_res.scalars().all()

    # Registered vehicles
    vehicles_stmt = select(Vehicle).order_by(Vehicle.created_at.desc()).limit(20)
    vehicles_res = await db.execute(vehicles_stmt)
    vehicles_list = vehicles_res.scalars().all()

    # Recent notifications
    notifs_stmt = select(NotificationLog).order_by(NotificationLog.timestamp.desc()).limit(10)
    notifs_res = await db.execute(notifs_stmt)
    notifs_list = notifs_res.scalars().all()

    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={
            "total_events": total_events,
            "awaiting_review": awaiting_review,
            "confirmed_violations": confirmed_violations,
            "total_vehicles": total_vehicles,
            "events_list": events_list,
            "vehicles_list": vehicles_list,
            "notifs_list": notifs_list,
        },
    )
