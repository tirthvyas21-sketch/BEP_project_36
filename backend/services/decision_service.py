"""
Decision Escalation Engine.

Implements Step 9 from the PC122 Project Report:
- 1st Violation -> Warning Email
- 2nd Violation -> Final Warning Email
- 3rd Violation -> Fine Notification
- 4th+ Violation -> Higher Penalty or Report to Authority
- Unknown Vehicle -> Log as Unknown Vehicle Violation
"""

from typing import Tuple
from backend.models.violation import ActionTaken


class DecisionService:
    @staticmethod
    def evaluate(student_matched: bool, previous_violation_count: int) -> Tuple[ActionTaken, str, str]:
        """
        Evaluate the appropriate action based on student matching and previous violations.

        Returns:
            Tuple[ActionTaken, action_description, penalty_details]
        """
        if not student_matched:
            return (
                ActionTaken.UNKNOWN_LOGGED,
                "Vehicle not found in student database. Logged as unknown violation.",
                "None (Unregistered/Visitor Vehicle)",
            )

        current_count = previous_violation_count + 1

        if current_count == 1:
            return (
                ActionTaken.WARNING,
                "First violation: Formal Warning Email dispatched to student.",
                "Warning Notice (Zero monetary fine)",
            )
        elif current_count == 2:
            return (
                ActionTaken.FINAL_WARNING,
                "Second violation: Final Warning Email dispatched to student.",
                "Final Warning Notice (Disciplinary notice)",
            )
        elif current_count == 3:
            return (
                ActionTaken.FINE,
                "Third violation: Fine Notification dispatched to student.",
                "Campus Traffic Fine: INR 500",
            )
        else:
            return (
                ActionTaken.REPORT_TO_AUTHORITY,
                f"Repeated violation ({current_count}th time): Escalated to Campus Security & Proctorial Board.",
                "Higher Penalty (INR 1,500) + Vehicle Gate Pass Suspension Review",
            )
