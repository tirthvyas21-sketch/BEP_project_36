"""
Vehicles Router – Campus Student Vehicle Management.
"""

from __future__ import annotations

import re
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.models.violation import Vehicle
from backend.models.schemas import VehicleCreate, VehicleResponse

router = APIRouter()


def clean_plate(plate: str) -> str:
    """Normalize plate string to uppercase alphanumeric."""
    return re.sub(r"[^A-Za-z0-9]", "", plate).upper()


@router.get("/", response_model=List[VehicleResponse])
async def list_vehicles(
    skip: int = 0,
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
):
    """Retrieve all registered student vehicles."""
    result = await db.execute(select(Vehicle).offset(skip).limit(limit))
    return result.scalars().all()


@router.post("/", response_model=VehicleResponse, status_code=status.HTTP_201_CREATED)
async def register_vehicle(
    payload: VehicleCreate,
    db: AsyncSession = Depends(get_db),
):
    """Register a new student vehicle."""
    normalized_plate = clean_plate(payload.plate_number)

    # Check duplicates
    existing_plate = await db.execute(
        select(Vehicle).where(Vehicle.plate_number == normalized_plate)
    )
    if existing_plate.scalar_one_or_none():
        raise HTTPException(
            status_code=400,
            detail=f"Vehicle plate {normalized_plate} is already registered.",
        )

    existing_sid = await db.execute(
        select(Vehicle).where(Vehicle.student_id == payload.student_id)
    )
    if existing_sid.scalar_one_or_none():
        raise HTTPException(
            status_code=400,
            detail=f"Student ID {payload.student_id} is already registered.",
        )

    vehicle = Vehicle(
        plate_number=normalized_plate,
        student_name=payload.student_name,
        student_id=payload.student_id,
        email=payload.email,
        phone=payload.phone,
        department=payload.department,
    )
    db.add(vehicle)
    await db.commit()
    await db.refresh(vehicle)
    return vehicle


@router.post("/seed-demo", status_code=status.HTTP_200_OK)
async def seed_demo_vehicles(db: AsyncSession = Depends(get_db)):
    """
    Seed safe synthetic student records for testing and demonstration.
    Never uses real student or vehicle data.
    """
    demo_data = [
        {
            "plate_number": "GJ01AB1234",
            "student_name": "Demo Student Alpha",
            "student_id": "STU2025001",
            "email": "student.alpha@campus.edu",
            "phone": "+91-9876500001",
            "department": "Computer Science & Engineering",
        },
        {
            "plate_number": "GJ01CD5678",
            "student_name": "Demo Student Beta",
            "student_id": "STU2025002",
            "email": "student.beta@campus.edu",
            "phone": "+91-9876500002",
            "department": "Information & Communication Technology",
        },
        {
            "plate_number": "GJ05EF9012",
            "student_name": "Demo Student Gamma",
            "student_id": "STU2025003",
            "email": "student.gamma@campus.edu",
            "phone": "+91-9876500003",
            "department": "Electronics & Communication",
        },
        {
            "plate_number": "MH12GH3456",
            "student_name": "Demo Student Delta",
            "student_id": "STU2025004",
            "email": "student.delta@campus.edu",
            "phone": "+91-9876500004",
            "department": "Mechanical Engineering",
        },
    ]

    added = 0
    for v_data in demo_data:
        exists = await db.execute(
            select(Vehicle).where(Vehicle.plate_number == v_data["plate_number"])
        )
        if not exists.scalar_one_or_none():
            veh = Vehicle(**v_data)
            db.add(veh)
            added += 1

    await db.commit()
    return {"message": f"Successfully seeded {added} demo student vehicle records."}
