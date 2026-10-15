"""
Notifications Service (Step 9 of Curriculum).

- Sends formatted violation notifications (with image proof attachment).
- Safe test mode (generates local HTML preview files if SMTP_HOST is not set).
- Enforces an IDEMPOTENCY KEY so that re-processing or retrying an event never sends duplicate notices.
- Records every notification attempt in the notification_log database table.
"""

from __future__ import annotations

import logging
import smtplib
from datetime import datetime, timezone
from email.mime.image import MIMEImage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Optional, Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import settings
from backend.models.violation import NotificationLog

logger = logging.getLogger(__name__)


class NotificationService:
    @staticmethod
    async def dispatch_violation_notice(
        db: AsyncSession,
        event_db_id: int,
        event_id_str: str,
        recipient_email: str,
        student_name: str,
        plate_number: str,
        incident_outcome: str,
        penalty_details: str,
        confirmed_count: int,
        timestamp_str: str,
        location: str,
        image_path: Optional[str] = None,
        event: Optional[Any] = None,
    ) -> tuple[bool, str]:
        """
        Send notification with idempotency check.
        Returns: (success, status_message)
        """
        # Idempotency key based on event_id and confirmed_count
        idempotency_key = f"NOTIF-{event_id_str}-COUNT{confirmed_count}-{recipient_email}"

        # 1. Check if this notification has already been sent
        existing = await db.execute(
            select(NotificationLog).where(NotificationLog.idempotency_key == idempotency_key)
        )
        existing_log = existing.scalar_one_or_none()
        if existing_log:
            logger.info("Notification skipped: idempotency key %s already dispatched", idempotency_key)
            return True, f"Idempotent: Already sent previously ({existing_log.delivery_status})"

        subject = f"[Campus Traffic Alert] Event #{event_id_str} Notice - Vehicle {plate_number}"

        html_body = f"""
        <!DOCTYPE html>
        <html>
        <head>
          <style>
            body {{ font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background-color: #f8fafc; margin: 0; padding: 20px; color: #1e293b; }}
            .container {{ max-width: 600px; margin: 0 auto; background: #ffffff; border-radius: 8px; border: 1px solid #e2e8f0; overflow: hidden; }}
            .header {{ background-color: #0f172a; color: #38bdf8; padding: 20px; text-align: center; }}
            .header h1 {{ margin: 0; font-size: 18px; }}
            .content {{ padding: 25px; line-height: 1.6; }}
            .badge {{ display: inline-block; padding: 4px 10px; border-radius: 4px; font-weight: bold; background: #e0f2fe; color: #0369a1; }}
            .table {{ width: 100%; border-collapse: collapse; margin-top: 15px; margin-bottom: 20px; }}
            .table td {{ padding: 8px 12px; border-bottom: 1px solid #f1f5f9; font-size: 14px; }}
            .table td.label {{ font-weight: bold; width: 40%; color: #64748b; }}
            .alert-box {{ background-color: #fef2f2; border-left: 4px solid #ef4444; padding: 12px; margin: 15px 0; color: #991b1b; font-size: 14px; }}
            .footer {{ background: #f8fafc; padding: 15px; text-align: center; font-size: 12px; color: #94a3b8; border-top: 1px solid #e2e8f0; }}
          </style>
        </head>
        <body>
          <div class="container">
            <div class="header">
              <h1>Campus Traffic Incident Notice</h1>
            </div>
            <div class="content">
              <p>Dear <strong>{student_name}</strong>,</p>
              <p>An official campus traffic incident was reviewed and confirmed for event reference <strong>#{event_id_str}</strong>.</p>
              
              <div class="alert-box">
                <strong>Enforced Action:</strong> {incident_outcome.upper()}<br>
                <strong>Penalty Detail:</strong> {penalty_details}
              </div>

              <table class="table">
                <tr><td class="label">Vehicle Plate:</td><td><strong>{plate_number}</strong></td></tr>
                <tr><td class="label">Confirmed Count:</td><td><span class="badge">Incident #{confirmed_count}</span></td></tr>
                <tr><td class="label">Location:</td><td>{location}</td></tr>
                <tr><td class="label">Timestamp:</td><td>{timestamp_str}</td></tr>
                <tr><td class="label">Event Reference:</td><td>{event_id_str}</td></tr>
              </table>

              <p>Image proof captured at the time of the event is attached. For appeals, contact Campus Security within 48 hours.</p>
            </div>
            <div class="footer">
              Automated message from Campus Smart Traffic Violation Detection System.
            </div>
          </div>
        </body>
        </html>
        """

        delivery_status = "simulated"
        preview_filename = None
        message_desc = f"Delivered notice for {plate_number} to {recipient_email}"

        # Test mode: Dry-run preview
        if not settings.SMTP_HOST:
            captures_dir = Path(settings.CAPTURES_DIR)
            captures_dir.mkdir(parents=True, exist_ok=True)
            preview_filename = f"preview_{event_id_str}_{confirmed_count}.html"
            preview_path = captures_dir / preview_filename
            try:
                preview_path.write_text(html_body, encoding="utf-8")
                delivery_status = "simulated"
                message_desc = f"Simulated email (saved to {preview_filename})"
            except Exception as e:
                logger.error("Failed to write preview: %s", e)
        else:
            # Real SMTP transmission
            try:
                msg = MIMEMultipart("related")
                msg["Subject"] = subject
                msg["From"] = settings.EMAIL_FROM
                msg["To"] = recipient_email

                msg_alt = MIMEMultipart("alternative")
                msg.attach(msg_alt)
                msg_alt.attach(MIMEText(html_body, "html"))

                if image_path and Path(image_path).exists():
                    with open(image_path, "rb") as img_f:
                        img_part = MIMEImage(img_f.read())
                        img_part.add_header("Content-Disposition", "attachment", filename=Path(image_path).name)
                        msg.attach(img_part)

                with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=10) as server:
                    server.starttls()
                    if settings.SMTP_USER and settings.SMTP_PASSWORD:
                        server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
                    server.send_message(msg)

                delivery_status = "sent"
                message_desc = f"SMTP delivered to {recipient_email}"
            except Exception as err:
                delivery_status = "failed"
                message_desc = f"SMTP failure: {str(err)}"

        # 2. Record in notification_log table
        log_entry = NotificationLog(
            event_id=event_db_id,
            notification_type="email",
            recipient=recipient_email,
            delivery_status=delivery_status,
            idempotency_key=idempotency_key,
            message=message_desc,
            preview_file=preview_filename,
            timestamp=datetime.now(timezone.utc),
        )
        db.add(log_entry)
        if event is not None and hasattr(event, "notifications"):
            event.notifications.append(log_entry)
        await db.commit()

        return (delivery_status != "failed", message_desc)
