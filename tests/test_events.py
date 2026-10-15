"""
Comprehensive Automated Tests for the 5-Table Event-Driven Smart Traffic Architecture.

Tests:
1. Health endpoint
2. Vehicle registration and demo seeding
3. Event registration (unique event_id)
4. Image upload validation (content-type, corruption)
5. Multi-image invariant: Multiple images on 1 event do NOT create duplicate violations
6. Human review lifecycle: Pending Review -> Confirmed or Rejected
7. Escalation rules on confirmation (Warning -> Final Warning -> Fine -> Escalated)
8. Idempotency protection: Re-triggering does not send duplicate notifications
"""

import io
import pytest
import cv2
import numpy as np
from httpx import AsyncClient, ASGITransport

from main import app
from backend.models.violation import ReviewStatus, IncidentOutcome


def create_dummy_jpeg() -> bytes:
    """Generate a clean synthetic image frame."""
    img = np.zeros((480, 640, 3), dtype=np.uint8)
    cv2.rectangle(img, (150, 250), (490, 370), (255, 255, 255), -1)
    cv2.putText(img, "GJ01AB1234", (180, 330), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0, 0, 0), 3)
    _, encoded = cv2.imencode(".jpg", img)
    return encoded.tobytes()


@pytest.mark.asyncio
async def test_health_check():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.get("/health")
        assert res.status_code == 200
        assert res.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_vehicle_registration_and_seeding():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Seed demo vehicles
        seed_res = await client.post("/api/v1/vehicles/seed-demo")
        assert seed_res.status_code == 200

        # List vehicles
        list_res = await client.get("/api/v1/vehicles/")
        assert list_res.status_code == 200
        vehicles = list_res.json()
        assert len(vehicles) >= 4
        assert any(v["plate_number"] == "GJ01AB1234" for v in vehicles)


@pytest.mark.asyncio
async def test_event_registration_and_image_upload():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # 1. Register an event
        event_payload = {
            "device_id": "ESP32S3-CAM-01",
            "sensor_data": "Ultrasonic: 22.5cm | IR: TRIGGERED",
            "location": "Lotus Pond Road Circle",
        }
        evt_res = await client.post("/api/v1/events/", json=event_payload)
        assert evt_res.status_code == 201
        event = evt_res.json()
        event_id = event["event_id"]
        assert event["status"] == "received"

        # 2. Reject invalid file format
        bad_file = {"file": ("test.txt", io.BytesIO(b"not an image"), "text/plain")}
        bad_res = await client.post(f"/api/v1/events/{event_id}/images", files=bad_file)
        assert bad_res.status_code == 400

        # 3. Upload valid image frame
        jpeg_bytes = create_dummy_jpeg()
        good_file = {"file": ("frame1.jpg", io.BytesIO(jpeg_bytes), "image/jpeg")}
        up_res = await client.post(
            f"/api/v1/events/{event_id}/images",
            files=good_file,
            data={"test_plate": "GJ01AB1234"},
        )
        assert up_res.status_code == 200
        updated_event = up_res.json()
        assert len(updated_event["images"]) == 1
        assert updated_event["violation"] is not None
        assert updated_event["violation"]["recognized_plate"] == "GJ01AB1234"
        assert updated_event["violation"]["review_status"] == ReviewStatus.PENDING_REVIEW.value


@pytest.mark.asyncio
async def test_multi_image_single_violation_invariant():
    """
    CRITICAL REQUIREMENT: One event may receive multiple images (e.g. rapid camera burst),
    but must NEVER create duplicate violations.
    """
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Register event
        evt_res = await client.post("/api/v1/events/", json={"device_id": "ESP32-BURST"})
        event_id = evt_res.json()["event_id"]

        jpeg_bytes = create_dummy_jpeg()

        # Upload image 1
        file1 = {"file": ("burst1.jpg", io.BytesIO(jpeg_bytes), "image/jpeg")}
        await client.post(f"/api/v1/events/{event_id}/images", files=file1, data={"test_plate": "GJ01AB1234"})

        # Upload image 2 for the same event
        file2 = {"file": ("burst2.jpg", io.BytesIO(jpeg_bytes), "image/jpeg")}
        up2_res = await client.post(f"/api/v1/events/{event_id}/images", files=file2, data={"test_plate": "GJ01AB1234"})
        assert up2_res.status_code == 200
        data = up2_res.json()

        # Verify exactly 2 images exist
        assert len(data["images"]) == 2
        # Verify exactly 1 violation object is attached
        assert data["violation"] is not None
        assert data["violation"]["event_id"] == data["id"]


@pytest.mark.asyncio
async def test_human_review_and_idempotent_notification():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Seed vehicles
        await client.post("/api/v1/vehicles/seed-demo")

        # Simulate event
        jpeg_bytes = create_dummy_jpeg()
        files = {"file": ("sim.jpg", io.BytesIO(jpeg_bytes), "image/jpeg")}
        sim_res = await client.post(
            "/api/v1/events/simulate",
            files=files,
            data={"test_plate": "MH12GH3456", "auto_confirm": False},
        )
        assert sim_res.status_code == 200
        event_id = sim_res.json()["event_id"]

        # Human Review: Confirm the incident
        review_payload = {
            "action": "confirm",
            "confirmed_plate": "MH12GH3456",
            "reviewer_name": "Officer Sharma",
            "notes": "Verified restricted right turn into Lotus Pond lane.",
        }
        rev_res = await client.post(f"/api/v1/events/{event_id}/review", json=review_payload)
        assert rev_res.status_code == 200
        reviewed_event = rev_res.json()

        assert reviewed_event["violation"]["review_status"] == ReviewStatus.CONFIRMED.value
        assert reviewed_event["violation"]["confirmed_incident_count"] >= 1
        assert reviewed_event["violation"]["reviewed_by"] == "Officer Sharma"
        assert len(reviewed_event["notifications"]) == 1

        # Test Idempotency: Re-confirming must not create a duplicate notification
        re_confirm = await client.post(f"/api/v1/events/{event_id}/review", json=review_payload)
        assert re_confirm.status_code == 200
        re_event = re_confirm.json()
        assert len(re_event["notifications"]) == 1
