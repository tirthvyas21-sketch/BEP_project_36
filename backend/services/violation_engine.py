"""
Violation Engine (Step 7 of Curriculum).

- Matches plates against the Vehicle database.
- Counts distinct, confirmed incidents for each vehicle (avoids duplicate counts on retry).
- Applies configurable demonstration escalation rules:
    Confirmed Count 1: Warning
    Confirmed Count 2: Final Warning
    Confirmed Count 3: Fine Notification (pending review)
    Confirmed Count 4+: Escalation for Authorized Review
    Unmatched: Unregistered / Visitor Vehicle
- Marks uncertain or unmatched plates as PENDING_REVIEW.
- Never automatically sends fines or accusations based on uncertain OCR.
"""

from __future__ import annotations

from typing import Optional, Tuple
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.violation import (
    Vehicle,
    Violation,
    ReviewStatus,
    IncidentOutcome,
)


class ViolationEngine:
    @staticmethod
    async def match_vehicle(
        db: AsyncSession,
        plate_number: Optional[str],
    ) -> Optional[Vehicle]:
        """Look up vehicle by normalized registration plate."""
        if not plate_number:
            return None
        stmt = select(Vehicle).where(Vehicle.plate_number == plate_number)
        res = await db.execute(stmt)
        return res.scalar_one_or_none()

    @staticmethod
    async def get_confirmed_violation_count(
        db: AsyncSession,
        vehicle_id: int,
        exclude_event_id: Optional[int] = None,
    ) -> int:
        """
        Count distinct, CONFIRMED violations for a vehicle.
        Prevents duplicate counts when events are reprocessed or retried.
        """
        stmt = select(func.count(Violation.id)).where(
            Violation.vehicle_id == vehicle_id,
            Violation.review_status == ReviewStatus.CONFIRMED,
        )
        if exclude_event_id is not None:
            stmt = stmt.where(Violation.event_id != exclude_event_id)

        res = await db.execute(stmt)
        return res.scalar_one()

    @staticmethod
    def determine_incident_outcome(
        confirmed_count: int,
        vehicle_matched: bool,
    ) -> Tuple[IncidentOutcome, str, str]:
        """
        Determine escalation outcome for confirmed violations:
        Count 1: Warning
        Count 2: Final Warning
        Count 3: Fine
        Count 4+: Escalated to Security / Proctorial Board
        """
        if not vehicle_matched:
            return (
                IncidentOutcome.UNREGISTERED,
                "Unregistered Vehicle Violation (Visitor/Guest)",
                "None (Logged for Campus Security Check)",
            )

        if confirmed_count == 1:
            return (
                IncidentOutcome.WARNING,
                "First Violation: Warning Notice Dispatched",
                "Warning Notice (INR 0)",
            )
        elif confirmed_count == 2:
            return (
                IncidentOutcome.FINAL_WARNING,
                "Second Violation: Final Warning Dispatched",
                "Final Warning Notice (Disciplinary Record)",
            )
        elif confirmed_count == 3:
            return (
                IncidentOutcome.FINE,
                "Third Violation: Fine Notification Pending Review",
                "Campus Traffic Fine: INR 500",
            )
        else:
            return (
                IncidentOutcome.ESCALATED,
                f"Repeated Violation (#{confirmed_count}): Escalated for Authorized Review",
                "Higher Penalty (INR 1,500) & Gate Pass Review",
            )

    @staticmethod
    def evaluate_initial_review_status(
        ocr_status: str,
        confidence: Optional[float],
        vehicle_matched: bool,
    ) -> ReviewStatus:
        """
        Determine if initial status should be PENDING_REVIEW or auto-confirmed.
        Rule: Low confidence or uncertain OCR must ALWAYS be pending human review.
        """
        if ocr_status != "success" or not confidence or confidence < 0.80 or not vehicle_matched:
            return ReviewStatus.PENDING_REVIEW
        return ReviewStatus.PENDING_REVIEW  # All potential violations require human review per policy
