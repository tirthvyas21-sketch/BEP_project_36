"""
Database ORM Models for the 5-Table Event-Driven Smart Traffic Violation Architecture.

Step 4 of Curriculum:
1. vehicles: test plate number, student name, student ID, email, department, phone.
2. events: event_id (unique), timestamp, device_id, sensor_data, status.
3. images: id, event_id, image_path, upload_timestamp, status.
4. violations: event_id (unique 1:1 with event), matched_vehicle_id, recognized_plate,
   confidence, review_status, incident_outcome, reviewed_by, reviewed_at, notes.
5. notification_log: event_id, notification_type, recipient, delivery_status,
   idempotency_key (unique), message, timestamp.
"""

from __future__ import annotations

import enum
from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.database import Base


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class EventStatus(str, enum.Enum):
    RECEIVED = "received"
    AWAITING_RECOGNITION = "awaiting_recognition"
    PROCESSED = "processed"
    REVIEWED = "reviewed"


class ReviewStatus(str, enum.Enum):
    PENDING_REVIEW = "pending_review"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"


class IncidentOutcome(str, enum.Enum):
    WARNING = "warning"
    FINAL_WARNING = "final_warning"
    FINE = "fine"
    ESCALATED = "escalated"
    UNREGISTERED = "unregistered"
    REJECTED = "rejected"
    PENDING = "pending"


class ImageStatus(str, enum.Enum):
    UPLOADED = "uploaded"
    PROCESSED = "processed"
    FAILED = "failed"


# ---------------------------------------------------------------------------
# 1. Vehicles Table
# ---------------------------------------------------------------------------

class Vehicle(Base):
    """Registered campus vehicles with student owner information."""

    __tablename__ = "vehicles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    plate_number: Mapped[str] = mapped_column(String(20), unique=True, index=True, nullable=False)
    student_name: Mapped[str] = mapped_column(String(100), nullable=False)
    student_id: Mapped[str] = mapped_column(String(50), unique=True, index=True, nullable=False)
    email: Mapped[str] = mapped_column(String(150), unique=True, index=True, nullable=False)
    phone: Mapped[Optional[str]] = mapped_column(String(25), nullable=True)
    department: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), nullable=False
    )

    # Relationships
    violations: Mapped[List[Violation]] = relationship("Violation", back_populates="vehicle")

    def __repr__(self) -> str:
        return f"<Vehicle plate='{self.plate_number}' student='{self.student_name}'>"


# ---------------------------------------------------------------------------
# 2. Events Table
# ---------------------------------------------------------------------------

class Event(Base):
    """
    Traffic sensor triggers.
    Enforces uniqueness on event_id. One event may receive multiple camera images,
    but never counts as multiple violations.
    """

    __tablename__ = "events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    event_id: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), nullable=False, index=True
    )
    device_id: Mapped[str] = mapped_column(String(64), default="ESP32S3-CAM-01", index=True)
    sensor_data: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON or text sensor payload
    status: Mapped[EventStatus] = mapped_column(
        Enum(EventStatus), default=EventStatus.RECEIVED, nullable=False
    )
    location: Mapped[str] = mapped_column(String(255), default="Lotus Pond Road Circle")

    # Relationships
    images: Mapped[List[EventImage]] = relationship("EventImage", back_populates="event", cascade="all, delete-orphan", lazy="selectin")
    violation: Mapped[Optional[Violation]] = relationship("Violation", back_populates="event", uselist=False, cascade="all, delete-orphan", lazy="selectin")
    notifications: Mapped[List[NotificationLog]] = relationship("NotificationLog", back_populates="event", cascade="all, delete-orphan", lazy="selectin")

    def __repr__(self) -> str:
        return f"<Event id={self.event_id} status={self.status}>"


# ---------------------------------------------------------------------------
# 3. Images Table
# ---------------------------------------------------------------------------

class EventImage(Base):
    """Image files attached to an event."""

    __tablename__ = "images"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    event_id: Mapped[int] = mapped_column(Integer, ForeignKey("events.id"), nullable=False, index=True)
    image_path: Mapped[str] = mapped_column(String(512), nullable=False)
    annotated_path: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    upload_timestamp: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), nullable=False
    )
    status: Mapped[ImageStatus] = mapped_column(Enum(ImageStatus), default=ImageStatus.UPLOADED)

    event: Mapped[Event] = relationship("Event", back_populates="images")

    def __repr__(self) -> str:
        return f"<EventImage id={self.id} path='{self.image_path}'>"


# ---------------------------------------------------------------------------
# 4. Violations Table
# ---------------------------------------------------------------------------

class Violation(Base):
    """
    Incident outcome for an event.
    Has 1:1 relationship with an event to guarantee an event is never duplicated.
    Includes human review status (pending_review, confirmed, rejected).
    """

    __tablename__ = "violations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    event_id: Mapped[int] = mapped_column(Integer, ForeignKey("events.id"), unique=True, nullable=False, index=True)
    vehicle_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("vehicles.id"), nullable=True, index=True)

    recognized_plate: Mapped[Optional[str]] = mapped_column(String(20), index=True, nullable=True)
    confirmed_plate: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    confidence: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    review_status: Mapped[ReviewStatus] = mapped_column(
        Enum(ReviewStatus), default=ReviewStatus.PENDING_REVIEW, nullable=False, index=True
    )
    incident_outcome: Mapped[IncidentOutcome] = mapped_column(
        Enum(IncidentOutcome), default=IncidentOutcome.PENDING, nullable=False
    )
    confirmed_incident_count: Mapped[int] = mapped_column(Integer, default=0)

    reviewed_by: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    review_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), nullable=False
    )

    # Relationships
    event: Mapped[Event] = relationship("Event", back_populates="violation", lazy="selectin")
    vehicle: Mapped[Optional[Vehicle]] = relationship("Vehicle", back_populates="violations", lazy="selectin")

    def __repr__(self) -> str:
        return f"<Violation event_id={self.event_id} plate='{self.recognized_plate}' status={self.review_status}>"


# ---------------------------------------------------------------------------
# 5. Notification Log Table
# ---------------------------------------------------------------------------

class NotificationLog(Base):
    """
    Log of notices dispatched.
    Enforces idempotency keys so retrying an event processing does NOT duplicate emails.
    """

    __tablename__ = "notification_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    event_id: Mapped[int] = mapped_column(Integer, ForeignKey("events.id"), nullable=False, index=True)
    notification_type: Mapped[str] = mapped_column(String(50), default="email")
    recipient: Mapped[str] = mapped_column(String(150), nullable=False)
    delivery_status: Mapped[str] = mapped_column(String(50), default="simulated")  # simulated | sent | failed
    idempotency_key: Mapped[str] = mapped_column(String(128), unique=True, index=True, nullable=False)
    message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    preview_file: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), nullable=False
    )

    event: Mapped[Event] = relationship("Event", back_populates="notifications")

    def __repr__(self) -> str:
        return f"<NotificationLog event={self.event_id} recipient='{self.recipient}' status='{self.delivery_status}'>"
