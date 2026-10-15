"""
Detections Router – Violation Processing and Management.

Implements Steps 5 to 11 from the PC122 Project Report:
- Accepts image captures from ESP32-S3 or web dashboard
- Executes OpenCV preprocessing and license plate OCR
- Matches vehicle against the campus student database
- Calculates total violation count and executes the 4-tier decision escalation
- Triggers automated warning/fine email notifications with image proof
- Permanently stores violation records in the database.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

import cv2
import numpy as np
from fastapi import APIRouter, Depends, Form, HTTPException, UploadFile, File, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.config import settings
from backend.database import get_db
from backend.models.violation import Violation, Student, ViolationType, ActionTaken
from backend.models.schemas import ViolationCreate, ViolationResponse, AnalysisResponse
from backend.services.detection_service import DetectionService
from backend.services.decision_service import DecisionService
from backend.services.notification_service import NotificationService

logger = logging.getLogger(__name__)
router = APIRouter()
detection_service = DetectionService()


def normalize_plate(plate: str | None) -> str | None:
    if not plate:
        return None
    return re.sub(r"[^A-Za-z0-9]", "", plate).upper()


@router.get("/", response_model=List[ViolationResponse])
async def list_violations(
    skip: int = 0,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
):
    """Return a paginated list of violation records, newest first."""
    result = await db.execute(
        select(Violation)
        .options(selectinload(Violation.student))
        .order_by(Violation.timestamp.desc())
        .offset(skip)
        .limit(limit)
    )
    return result.scalars().all()


@router.post("/", response_model=ViolationResponse, status_code=status.HTTP_201_CREATED)
async def create_violation(
    payload: ViolationCreate,
    db: AsyncSession = Depends(get_db),
):
    """Manually create a violation record."""
    violation = Violation(**payload.model_dump())
    db.add(violation)
    await db.commit()
    await db.refresh(violation)
    return violation


@router.get("/{violation_id}", response_model=ViolationResponse)
async def get_violation(violation_id: int, db: AsyncSession = Depends(get_db)):
    """Fetch one violation by ID."""
    result = await db.execute(
        select(Violation)
        .options(selectinload(Violation.student))
        .where(Violation.id == violation_id)
    )
    obj = result.scalar_one_or_none()
    if obj is None:
        raise HTTPException(status_code=404, detail="Violation not found")
    return obj


@router.delete("/{violation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_violation(violation_id: int, db: AsyncSession = Depends(get_db)):
    """Delete a violation record."""
    obj = await db.get(Violation, violation_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="Violation not found")
    await db.delete(obj)
    await db.commit()


@router.post("/analyse", response_model=AnalysisResponse, status_code=status.HTTP_200_OK)
async def analyse_and_record_violation(
    file: UploadFile = File(...),
    test_plate: Optional[str] = Form(None),
    location: str = Form("Lotus Pond Road Circle"),
    db: AsyncSession = Depends(get_db),
):
    """
    Main analysis pipeline:
    1. Receive frame from ESP32-S3 Sense or web upload
    2. Store captured frame locally in `data/captures/`
    3. Run OpenCV detection & OCR extraction
    4. Query Student database for plate match
    5. Determine escalation tier (Warning -> Final Warning -> Fine -> Authority)
    6. Dispatch automated email notification
    7. Store record in database permanently
    """
    contents = await file.read()
    nparr = np.frombuffer(contents, np.uint8)
    frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

    if frame is None:
        raise HTTPException(status_code=400, detail="Uploaded file is not a valid image.")

    # Save original capture
    timestamp = datetime.now(timezone.utc)
    ts_str = timestamp.strftime("%Y%m%d_%H%M%S")
    safe_filename = f"violation_{ts_str}_{file.filename or 'frame.jpg'}"
    captures_dir = Path(settings.CAPTURES_DIR)
    captures_dir.mkdir(parents=True, exist_ok=True)
    raw_path = captures_dir / safe_filename

    with open(raw_path, "wb") as f_out:
        f_out.write(contents)

    # Process frame through OpenCV & OCR
    detection_result = detection_service.process_frame(frame, mock_plate_fallback=test_plate)
    detected_plate = normalize_plate(detection_result["plate_number"])
    confidence = detection_result["confidence"]

    # Save annotated frame
    annotated_path = captures_dir / f"annotated_{safe_filename}"
    cv2.imwrite(str(annotated_path), detection_result["annotated_frame"])

    # Step 7: Database Matching
    student: Optional[Student] = None
    previous_count = 0

    if detected_plate:
        stmt = select(Student).where(Student.vehicle_number == detected_plate)
        student_res = await db.execute(stmt)
        student = student_res.scalar_one_or_none()

    if student:
        # Count existing violations for this student
        count_stmt = select(func.count(Violation.id)).where(Violation.student_id == student.id)
        count_res = await db.execute(count_stmt)
        previous_count = count_res.scalar_one()

    # Step 9: Decision Escalation
    student_matched = student is not None
    action_taken, action_desc, penalty = DecisionService.evaluate(
        student_matched=student_matched,
        previous_violation_count=previous_count,
    )
    current_count = previous_count + 1 if student_matched else 1

    # Step 10: Email Notification
    email_sent = False
    email_status = "No recipient email (unregistered vehicle)"

    if student:
        email_sent, email_status = NotificationService.send_violation_email(
            recipient_email=student.email,
            student_name=student.name,
            student_id=student.student_id,
            plate_number=detected_plate or "UNKNOWN",
            violation_type="Illegal Right Turn",
            violation_count=current_count,
            action_name=action_desc,
            penalty_details=penalty,
            timestamp_str=timestamp.strftime("%Y-%m-%d %H:%M:%S UTC"),
            location=location,
            image_path=str(annotated_path),
        )

    # Step 11: Permanent Storage
    violation_record = Violation(
        timestamp=timestamp,
        violation_type=ViolationType.RESTRICTED_TURN,
        plate_number=detected_plate,
        confidence=confidence,
        image_path=f"/captures/{annotated_path.name}",
        location=location,
        notes=f"Escalation: {action_desc} | Penalty: {penalty}",
        student_id=student.id if student else None,
        violation_count_at_time=current_count,
        action_taken=action_taken,
        email_sent=email_sent,
        email_status=email_status,
    )
    db.add(violation_record)
    await db.commit()
    await db.refresh(violation_record)

    return AnalysisResponse(
        violation_detected=True,
        violation_id=violation_record.id,
        plate_number=detected_plate,
        confidence=confidence,
        student_matched=student_matched,
        student_name=student.name if student else None,
        student_id=student.student_id if student else None,
        student_email=student.email if student else None,
        violation_count=current_count,
        action_taken=action_taken,
        action_description=action_desc,
        email_sent=email_sent,
        email_status=email_status,
        image_path=f"/captures/{annotated_path.name}",
    )
