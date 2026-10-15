"""
Events Router – REST API for Traffic Sensor Events and Image Upload Pipeline.

Fulfills Steps 3, 5, 6, 7 & 9:
- POST /api/v1/events                  -> Register possible traffic event
- POST /api/v1/events/{event_id}/images -> Upload and validate event images
- GET  /api/v1/events                  -> List events with status filters
- GET  /api/v1/events/{event_id}        -> View one event with all images & violation
- POST /api/v1/events/{event_id}/review -> Human-in-the-loop review (confirm/reject)
- POST /api/v1/events/simulate         -> Single-call simulator for web testing
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

import cv2
import numpy as np
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.config import settings
from backend.database import get_db
from backend.models.schemas import (
    EventCreate,
    EventResponse,
    EventImageResponse,
    ReviewRequest,
    ViolationResponse,
)
from backend.models.violation import (
    Event,
    EventImage,
    EventStatus,
    ImageStatus,
    IncidentOutcome,
    NotificationLog,
    ReviewStatus,
    Vehicle,
    Violation,
)
from backend.services.notifications import NotificationService
from backend.services.plate_recognition import PlateRecognitionService
from backend.services.violation_engine import ViolationEngine

logger = logging.getLogger(__name__)
router = APIRouter()
plate_recognizer = PlateRecognitionService()

# Maximum allowed upload size (10 MB)
MAX_FILE_SIZE = 10 * 1024 * 1024
ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp"}


def generate_event_id() -> str:
    """Generate a clean, readable event identifier like EVT-20261015-A1B2."""
    date_part = datetime.now(timezone.utc).strftime("%Y%m%d")
    short_uuid = uuid.uuid4().hex[:6].upper()
    return f"EVT-{date_part}-{short_uuid}"


# ---------------------------------------------------------------------------
# 1. Register Event (Step 3)
# ---------------------------------------------------------------------------

@router.post("/", response_model=EventResponse, status_code=status.HTTP_201_CREATED)
async def register_event(
    payload: EventCreate,
    db: AsyncSession = Depends(get_db),
):
    """Register a new possible traffic violation event from sensors."""
    event_id = payload.event_id or generate_event_id()

    # Check for duplicate event_id
    existing = await db.execute(select(Event).where(Event.event_id == event_id))
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=400,
            detail=f"Event ID '{event_id}' already exists. Event IDs must be unique.",
        )

    event = Event(
        event_id=event_id,
        device_id=payload.device_id,
        sensor_data=payload.sensor_data,
        location=payload.location,
        status=EventStatus.RECEIVED,
        timestamp=datetime.now(timezone.utc),
    )
    db.add(event)
    await db.commit()
    await db.refresh(event)

    # Return with empty relationships
    return await get_event_by_id(event.event_id, db)


# ---------------------------------------------------------------------------
# 2. Upload Event Images & Run Pipeline (Step 3 & 5)
# ---------------------------------------------------------------------------

@router.post("/{event_id}/images", response_model=EventResponse, status_code=status.HTTP_200_OK)
async def upload_event_image(
    event_id: str,
    file: UploadFile = File(...),
    test_plate: Optional[str] = Form(None),
    db: AsyncSession = Depends(get_db),
):
    """
    Upload one or more images for an event.
    Validates file format and size, stores image to local disk, runs OCR,
    and updates/creates the single Violation record for this event.
    """
    # Find event
    event_res = await db.execute(
        select(Event)
        .options(
            selectinload(Event.images),
            selectinload(Event.violation),
            selectinload(Event.notifications),
        )
        .where(Event.event_id == event_id)
    )
    event = event_res.scalar_one_or_none()
    if not event:
        raise HTTPException(status_code=404, detail=f"Event '{event_id}' not found.")

    # Validate content type
    if file.content_type not in ALLOWED_IMAGE_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid image format: '{file.content_type}'. Allowed types: JPEG, PNG, WEBP.",
        )

    # Read and validate size
    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=413,
            detail=f"File exceeds maximum allowed size of {MAX_FILE_SIZE // (1024 * 1024)}MB.",
        )

    # Decode image with OpenCV
    nparr = np.frombuffer(content, np.uint8)
    frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    if frame is None:
        raise HTTPException(status_code=400, detail="Corrupted or unreadable image file.")

    # Save raw image to disk
    captures_dir = Path(settings.CAPTURES_DIR)
    captures_dir.mkdir(parents=True, exist_ok=True)
    clean_filename = f"{event.event_id}_{int(datetime.now(timezone.utc).timestamp())}_{file.filename or 'frame.jpg'}"
    raw_path = captures_dir / clean_filename
    with open(raw_path, "wb") as f_out:
        f_out.write(content)

    # Step 6: Plate Recognition
    rec_result = plate_recognizer.recognize(frame, mock_plate_fallback=test_plate)

    # Save annotated image
    annotated_filename = f"annotated_{clean_filename}"
    annotated_path = captures_dir / annotated_filename
    cv2.imwrite(str(annotated_path), rec_result.annotated_frame)

    # Record Image in DB
    event_image = EventImage(
        event_id=event.id,
        image_path=f"/captures/{clean_filename}",
        annotated_path=f"/captures/{annotated_filename}",
        upload_timestamp=datetime.now(timezone.utc),
        status=ImageStatus.PROCESSED,
    )
    db.add(event_image)
    event.images.append(event_image)

    # Step 7: Match Vehicle & Update Event's Single Violation
    detected_plate = rec_result.detected_plate_text
    matched_vehicle = await ViolationEngine.match_vehicle(db, detected_plate)

    # Find existing violation for this event or create new (guarantees 1 violation per event)
    viol_res = await db.execute(select(Violation).where(Violation.event_id == event.id))
    violation = viol_res.scalar_one_or_none()

    if not violation:
        violation = Violation(
            event_id=event.id,
            vehicle_id=matched_vehicle.id if matched_vehicle else None,
            recognized_plate=detected_plate,
            confidence=rec_result.confidence,
            review_status=ReviewStatus.PENDING_REVIEW,
            incident_outcome=IncidentOutcome.PENDING,
            confirmed_incident_count=0,
            created_at=datetime.now(timezone.utc),
        )
        violation.vehicle = matched_vehicle
        db.add(violation)
        event.violation = violation
    else:
        # If new image has higher confidence, update recognized plate
        if rec_result.confidence and (not violation.confidence or rec_result.confidence > violation.confidence):
            violation.recognized_plate = detected_plate
            violation.confidence = rec_result.confidence
            if matched_vehicle:
                violation.vehicle_id = matched_vehicle.id
                violation.vehicle = matched_vehicle

    event.status = EventStatus.PROCESSED
    await db.commit()

    return event


# ---------------------------------------------------------------------------
# 3. List Events (Step 3)
# ---------------------------------------------------------------------------

@router.get("/", response_model=List[EventResponse])
async def list_events(
    skip: int = 0,
    limit: int = 50,
    review_status: Optional[ReviewStatus] = None,
    db: AsyncSession = Depends(get_db),
):
    """List all traffic events with image counts, violation status, and review state."""
    stmt = (
        select(Event)
        .execution_options(populate_existing=True)
        .options(
            selectinload(Event.images),
            selectinload(Event.violation).selectinload(Violation.vehicle),
            selectinload(Event.notifications),
        )
        .order_by(Event.timestamp.desc())
        .offset(skip)
        .limit(limit)
    )

    if review_status:
        stmt = stmt.join(Violation).where(Violation.review_status == review_status)

    result = await db.execute(stmt)
    return result.scalars().all()


# ---------------------------------------------------------------------------
# 4. View One Event (Step 3)
# ---------------------------------------------------------------------------

@router.get("/{event_id}", response_model=EventResponse)
async def get_event_by_id(
    event_id: str,
    db: AsyncSession = Depends(get_db),
):
    """View details of a specific event, including all images and review status."""
    stmt = (
        select(Event)
        .execution_options(populate_existing=True)
        .options(
            selectinload(Event.images),
            selectinload(Event.violation).selectinload(Violation.vehicle),
            selectinload(Event.notifications),
        )
        .where(Event.event_id == event_id)
    )
    res = await db.execute(stmt)
    event = res.scalar_one_or_none()
    if not event:
        raise HTTPException(status_code=404, detail=f"Event '{event_id}' not found.")
    return event


# ---------------------------------------------------------------------------
# 5. Human Review Endpoint (Steps 7 & 8)
# ---------------------------------------------------------------------------

@router.post("/{event_id}/review", response_model=EventResponse)
async def review_event(
    event_id: str,
    payload: ReviewRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Human reviewer confirms or rejects an incident.
    - If confirmed: counts historical confirmed incidents for that vehicle,
      applies escalation rules, and dispatches an automated notification email.
    - If rejected: marks the event as dismissed.
    """
    stmt = (
        select(Event)
        .options(
            selectinload(Event.images),
            selectinload(Event.violation).selectinload(Violation.vehicle),
            selectinload(Event.notifications),
        )
        .where(Event.event_id == event_id)
    )
    res = await db.execute(stmt)
    event = res.scalar_one_or_none()
    if not event or not event.violation:
        raise HTTPException(status_code=404, detail=f"Event or violation '{event_id}' not found.")

    violation = event.violation
    action = payload.action.lower()

    if action == "reject":
        violation.review_status = ReviewStatus.REJECTED
        violation.incident_outcome = IncidentOutcome.REJECTED
        violation.reviewed_by = payload.reviewer_name
        violation.reviewed_at = datetime.now(timezone.utc)
        violation.review_notes = payload.notes or "Rejected by human reviewer"
        event.status = EventStatus.REVIEWED
        await db.commit()
        return event

    elif action == "confirm":
        # Reviewer can confirm existing or correct the plate number
        confirmed_plate = (payload.confirmed_plate or violation.recognized_plate or "").strip().upper()
        if not confirmed_plate:
            raise HTTPException(status_code=400, detail="Cannot confirm incident without a valid vehicle plate.")

        violation.confirmed_plate = confirmed_plate

        # Re-check vehicle match with confirmed plate
        vehicle = await ViolationEngine.match_vehicle(db, confirmed_plate)
        violation.vehicle_id = vehicle.id if vehicle else None

        # Count prior confirmed incidents for this vehicle
        confirmed_count = 1
        if vehicle:
            prior_count = await ViolationEngine.get_confirmed_violation_count(
                db, vehicle.id, exclude_event_id=event.id
            )
            confirmed_count = prior_count + 1

        outcome, action_desc, penalty = ViolationEngine.determine_incident_outcome(
            confirmed_count=confirmed_count,
            vehicle_matched=vehicle is not None,
        )

        violation.review_status = ReviewStatus.CONFIRMED
        violation.incident_outcome = outcome
        violation.confirmed_incident_count = confirmed_count
        violation.reviewed_by = payload.reviewer_name
        violation.reviewed_at = datetime.now(timezone.utc)
        violation.review_notes = payload.notes or f"Confirmed: {action_desc}"
        event.status = EventStatus.REVIEWED

        await db.commit()

        # Step 9: Send notification with idempotency protection
        if vehicle and vehicle.email:
            # Pick best image
            img_path = None
            if event.images:
                best_img = event.images[0]
                img_path = str(Path(settings.CAPTURES_DIR) / Path(best_img.image_path).name)

            await NotificationService.dispatch_violation_notice(
                db=db,
                event_db_id=event.id,
                event_id_str=event.event_id,
                recipient_email=vehicle.email,
                student_name=vehicle.student_name,
                plate_number=confirmed_plate,
                incident_outcome=outcome.value,
                penalty_details=penalty,
                confirmed_count=confirmed_count,
                timestamp_str=event.timestamp.strftime("%Y-%m-%d %H:%M:%S UTC"),
                location=event.location,
                image_path=img_path,
                event=event,
            )

        return event

    else:
        raise HTTPException(status_code=400, detail="Invalid action. Allowed: 'confirm' or 'reject'.")


# ---------------------------------------------------------------------------
# 6. Single-Call Simulator Endpoint (for easy web UI & hardware testing)
# ---------------------------------------------------------------------------

@router.post("/simulate", response_model=EventResponse)
async def simulate_event(
    file: UploadFile = File(...),
    test_plate: Optional[str] = Form(None),
    device_id: str = Form("ESP32S3-CAM-01"),
    sensor_info: str = Form("Ultrasonic: 28cm | IR: TRIGGERED"),
    location: str = Form("Lotus Pond Road Circle"),
    auto_confirm: bool = Form(False),
    db: AsyncSession = Depends(get_db),
):
    """
    Simulate a complete hardware trigger:
    1. Register event with sensor payload
    2. Upload image and run plate recognition
    3. Optionally auto-confirm for fast automated testing
    """
    event_id = generate_event_id()
    new_event = Event(
        event_id=event_id,
        device_id=device_id,
        sensor_data=sensor_info,
        location=location,
        status=EventStatus.RECEIVED,
        timestamp=datetime.now(timezone.utc),
    )
    db.add(new_event)
    await db.commit()
    await db.refresh(new_event)

    # Upload image
    uploaded_event = await upload_event_image(event_id=event_id, file=file, test_plate=test_plate, db=db)

    # Optional auto-confirm
    if auto_confirm:
        review_req = ReviewRequest(action="confirm", confirmed_plate=test_plate, reviewer_name="Auto-Simulator")
        return await review_event(event_id=event_id, payload=review_req, db=db)

    return uploaded_event
