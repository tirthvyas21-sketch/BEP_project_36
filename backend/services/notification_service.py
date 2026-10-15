"""
Automated Email Notification Service.

Implements Step 10 from the PC122 Project Report:
- Sends formatted HTML email to the student with violation details, timestamp,
  violation count, action taken, and captured image attached.
- If SMTP credentials are not configured, runs safely in DRY-RUN mode,
  saving rendered HTML email previews in `data/captures/` and logging the event.
"""

from __future__ import annotations

import logging
import smtplib
from email.mime.image import MIMEImage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Optional

from backend.config import settings

logger = logging.getLogger(__name__)


class NotificationService:
    @staticmethod
    def send_violation_email(
        recipient_email: str,
        student_name: str,
        student_id: str,
        plate_number: str,
        violation_type: str,
        violation_count: int,
        action_name: str,
        penalty_details: str,
        timestamp_str: str,
        location: str,
        image_path: Optional[str] = None,
    ) -> tuple[bool, str]:
        """
        Send violation notification email with captured image proof.

        Returns:
            tuple[bool, str]: (success, status_message)
        """
        subject = f"[Campus Traffic Alert] Violation Notice #{violation_count} - Vehicle {plate_number}"

        html_body = f"""
        <!DOCTYPE html>
        <html>
        <head>
          <style>
            body {{ font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background-color: #f4f6f9; margin: 0; padding: 20px; color: #212529; }}
            .container {{ max-width: 600px; margin: 0 auto; background: #ffffff; border-radius: 8px; border: 1px solid #dee2e6; overflow: hidden; }}
            .header {{ background-color: #dc3545; color: #ffffff; padding: 20px; text-align: center; }}
            .header h1 {{ margin: 0; font-size: 20px; }}
            .content {{ padding: 25px; line-height: 1.6; }}
            .badge {{ display: inline-block; padding: 4px 10px; border-radius: 4px; font-weight: bold; background: #ffeeba; color: #856404; }}
            .table {{ width: 100%; border-collapse: collapse; margin-top: 15px; margin-bottom: 20px; }}
            .table td {{ padding: 8px 12px; border-bottom: 1px solid #e9ecef; }}
            .table td.label {{ font-weight: bold; width: 40%; color: #495057; }}
            .alert-box {{ background-color: #f8d7da; border-left: 4px solid #dc3545; padding: 12px; margin: 15px 0; color: #721c24; }}
            .footer {{ background: #f8f9fa; padding: 15px; text-align: center; font-size: 12px; color: #6c757d; border-top: 1px solid #dee2e6; }}
          </style>
        </head>
        <body>
          <div class="container">
            <div class="header">
              <h1>Campus Traffic Violation Notice</h1>
            </div>
            <div class="content">
              <p>Dear <strong>{student_name}</strong> (Student ID: <strong>{student_id}</strong>),</p>
              <p>An illegal vehicular movement was detected and recorded by the Smart Traffic Violation Detection System at the campus restricted turning zone.</p>
              
              <div class="alert-box">
                <strong>Action Enforced:</strong> {action_name}<br>
                <strong>Penalty:</strong> {penalty_details}
              </div>

              <table class="table">
                <tr><td class="label">Vehicle Plate:</td><td><strong>{plate_number}</strong></td></tr>
                <tr><td class="label">Violation Type:</td><td>Illegal Turn ({violation_type})</td></tr>
                <tr><td class="label">Location:</td><td>{location}</td></tr>
                <tr><td class="label">Timestamp:</td><td>{timestamp_str}</td></tr>
                <tr><td class="label">Total Violations on Record:</td><td><span class="badge">{violation_count}</span></td></tr>
              </table>

              <p>Image proof captured at the time of violation is attached with this communication.</p>
              <p>Please adhere strictly to campus traffic guidelines. For inquiries or appeals, contact campus security within 48 hours.</p>
            </div>
            <div class="footer">
              Automated notice issued by Campus Smart Object Detection & Traffic Management System.
            </div>
          </div>
        </body>
        </html>
        """

        # Check if real SMTP is configured
        if not settings.SMTP_HOST:
            # Safe Dry-Run Mode
            log_dir = Path(settings.CAPTURES_DIR)
            log_dir.mkdir(parents=True, exist_ok=True)
            mock_file = log_dir / f"email_preview_{plate_number}_{violation_count}.html"
            try:
                mock_file.write_text(html_body, encoding="utf-8")
                msg = f"Simulated email sent to {recipient_email} (Preview saved to {mock_file.name})"
                logger.info(msg)
                return True, msg
            except Exception as e:
                logger.error("Failed to write mock email preview: %s", e)
                return True, f"Simulated email sent to {recipient_email}"

        # Real SMTP Transmission
        try:
            msg = MIMEMultipart("related")
            msg["Subject"] = subject
            msg["From"] = settings.EMAIL_FROM
            msg["To"] = recipient_email

            msg_alt = MIMEMultipart("alternative")
            msg.attach(msg_alt)
            msg_alt.attach(MIMEText(html_body, "html"))

            # Attach captured image if present
            if image_path and Path(image_path).exists():
                with open(image_path, "rb") as img_f:
                    img_data = img_f.read()
                    img_part = MIMEImage(img_data)
                    img_part.add_header("Content-Disposition", "attachment", filename=Path(image_path).name)
                    msg.attach(img_part)

            with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=10) as server:
                server.starttls()
                if settings.SMTP_USER and settings.SMTP_PASSWORD:
                    server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
                server.send_message(msg)

            logger.info("Email notification delivered successfully to %s", recipient_email)
            return True, f"Delivered to {recipient_email}"
        except Exception as err:
            logger.error("Failed to deliver email to %s: %s", recipient_email, err)
            return False, f"SMTP Error: {str(err)}"
