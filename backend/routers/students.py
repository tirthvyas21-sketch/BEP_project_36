"""
Students Router – Campus Student Vehicle Management.

Allows registering students, querying registered vehicles, and seeding synthetic demo data.
"""

from __future__ import annotations

import re
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.models.violation import Student
from backend.models.schemas import StudentCreate, StudentResponse

router = APIRouter()


def clean_plate(plate: str) -> str:
    """Normalize plate string to uppercase alphanumeric."""
    return re.sub(r"[^A-Za-z0-9]", "", plate).upper()


@router.get("/", response_model=List[StudentResponse])
async def list_students(
    skip: int = 0,
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
):
    """Retrieve all registered student vehicles."""
    result = await db.execute(select(Student).offset(skip).limit(limit))
    return result.scalars().all()


@router.post("/", response_model=StudentResponse, status_code=status.HTTP_201_CREATED)
async def register_student(
    payload: StudentCreate,
    db: AsyncSession = Depends(get_db),
):
    """Register a new student with their vehicle registration number."""
    normalized_plate = clean_plate(payload.vehicle_number)

    # Check for duplicate student_id or vehicle_number
    existing_plate = await db.execute(
        select(Student).where(Student.vehicle_number == normalized_plate)
    )
    if existing_plate.scalar_one_or_none():
        raise HTTPException(
            status_code=400,
            detail=f"Vehicle plate {normalized_plate} is already registered.",
        )

    existing_sid = await db.execute(
        select(Student).where(Student.student_id == payload.student_id)
    )
    if existing_sid.scalar_one_or_none():
        raise HTTPException(
            status_code=400,
            detail=f"Student ID {payload.student_id} is already registered.",
        )

    student = Student(
        student_id=payload.student_id,
        name=payload.name,
        email=payload.email,
        vehicle_number=normalized_plate,
        phone=payload.phone,
        department=payload.department,
    )
    db.add(student)
    await db.commit()
    await db.refresh(student)
    return student


@router.post("/seed-demo", status_code=status.HTTP_200_OK)
async def seed_demo_data(db: AsyncSession = Depends(get_db)):
    """
    Seed safe, synthetic demo student records for demonstration and testing.
    Never uses real student or vehicle data.
    """
    demo_students = [
        {
            "student_id": "STU2025001",
            "name": "Demo Student Alpha",
            "email": "demo.alpha@campus.edu",
            "vehicle_number": "GJ01AB1234",
            "phone": "+91-9876500001",
            "department": "Computer Science & Engineering",
        },
        {
            "student_id": "STU2025002",
            "name": "Demo Student Beta",
            "email": "demo.beta@campus.edu",
            "vehicle_number": "GJ01CD5678",
            "phone": "+91-9876500002",
            "department": "Information & Communication Technology",
        },
        {
            "student_id": "STU2025003",
            "name": "Demo Student Gamma",
            "email": "demo.gamma@campus.edu",
            "vehicle_number": "GJ05EF9012",
            "phone": "+91-9876500003",
            "department": "Electronics & Communication",
        },
        {
            "student_id": "STU2025004",
            "name": "Demo Student Delta",
            "email": "demo.delta@campus.edu",
            "vehicle_number": "MH12GH3456",
            "phone": "+91-9876500004",
            "department": "Mechanical Engineering",
        },
    ]

    added = 0
    for s_data in demo_students:
        exists = await db.execute(
            select(Student).where(Student.student_id == s_data["student_id"])
        )
        if not exists.scalar_one_or_none():
            student = Student(**s_data)
            db.add(student)
            added += 1

    await db.commit()
    return {"message": f"Successfully seeded {added} demo student vehicle records."}
