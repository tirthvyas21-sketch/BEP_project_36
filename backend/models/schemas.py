"""
Pydantic schemas for the 5-table event-driven architecture.
"""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from backend.models.violation import (
    EventStatus,
    ReviewStatus,
    IncidentOutcome,
    ImageStatus,
)


# ---------------------------------------------------------------------------
# 1. Vehicle Schemas
# ---------------------------------------------------------------------------

class VehicleBase(BaseModel):
    plate_number: str = Field(..., examples=["GJ01AB1234"])
    student_name: str = Field(..., examples=["Demo Student Alpha"])
    student_id: str = Field(..., examples=["STU2025001"])
    email: EmailStr = Field(..., examples=["student.alpha@campus.edu"])
    phone: Optional[str] = None
    department: Optional[str] = None


class VehicleCreate(VehicleBase):
    pass


class VehicleResponse(VehicleBase):
    id: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------------------
# 2. Image Schemas
# ---------------------------------------------------------------------------

class EventImageResponse(BaseModel):
    id: int
    event_id: int
    image_path: str
    annotated_path: Optional[str] = None
    upload_timestamp: datetime
    status: ImageStatus

    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------------------
# 3. Violation Schemas
# ---------------------------------------------------------------------------

class ViolationResponse(BaseModel):
    id: int
    event_id: int
    vehicle_id: Optional[int] = None
    recognized_plate: Optional[str] = None
    confirmed_plate: Optional[str] = None
    confidence: Optional[float] = None
    review_status: ReviewStatus
    incident_outcome: IncidentOutcome
    confirmed_incident_count: int
    reviewed_by: Optional[str] = None
    reviewed_at: Optional[datetime] = None
    review_notes: Optional[str] = None
    created_at: datetime
    vehicle: Optional[VehicleResponse] = None

    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------------------
# 4. Notification Log Schemas
# ---------------------------------------------------------------------------

class NotificationLogResponse(BaseModel):
    id: int
    event_id: int
    notification_type: str
    recipient: str
    delivery_status: str
    idempotency_key: str
    message: Optional[str] = None
    preview_file: Optional[str] = None
    timestamp: datetime

    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------------------
# 5. Event Schemas
# ---------------------------------------------------------------------------

class EventCreate(BaseModel):
    event_id: Optional[str] = Field(None, description="Optional custom unique event ID, auto-generated if omitted")
    device_id: str = Field("ESP32S3-CAM-01", description="Identifier of the capture hardware/location")
    sensor_data: Optional[str] = Field(None, description="JSON or text payload with ultrasonic distance, IR state, etc.")
    location: str = Field("Lotus Pond Road Circle", description="Campus location")


class EventResponse(BaseModel):
    id: int
    event_id: str
    timestamp: datetime
    device_id: str
    sensor_data: Optional[str] = None
    status: EventStatus
    location: str
    images: List[EventImageResponse] = []
    violation: Optional[ViolationResponse] = None
    notifications: List[NotificationLogResponse] = []

    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------------------
# Human Review Action Schema
# ---------------------------------------------------------------------------

class ReviewRequest(BaseModel):
    action: str = Field(..., description="'confirm' or 'reject'")
    confirmed_plate: Optional[str] = Field(None, description="Corrected or confirmed plate number")
    reviewer_name: str = Field("Campus Officer", description="Name/ID of reviewer")
    notes: Optional[str] = Field(None, description="Review remarks or rationale")
