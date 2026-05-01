from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models import Employee
from app.schemas.employees import EmployeeCreate, EmployeeRead, EmployeeUpdate
from app.services.audit import record_audit

router = APIRouter()


@router.get("", response_model=list[EmployeeRead])
def list_employees(
    db: Session = Depends(get_db),
    limit: int = 100,
    offset: int = 0,
) -> list[Employee]:
    statement = select(Employee).order_by(Employee.created_at.desc()).limit(limit).offset(offset)
    return list(db.scalars(statement).all())


@router.post("", response_model=EmployeeRead, status_code=status.HTTP_201_CREATED)
def create_employee(payload: EmployeeCreate, db: Session = Depends(get_db)) -> Employee:
    employee = Employee(**payload.model_dump())
    db.add(employee)
    db.flush()
    record_audit(
        db,
        action="employee.create",
        resource_type="employee",
        resource_id=str(employee.id),
        after=payload.model_dump(mode="json"),
    )
    db.commit()
    db.refresh(employee)
    return employee


@router.patch("/{employee_id}", response_model=EmployeeRead)
def update_employee(
    employee_id: UUID,
    payload: EmployeeUpdate,
    db: Session = Depends(get_db),
) -> Employee:
    employee = db.get(Employee, employee_id)
    if not employee:
        raise HTTPException(status_code=404, detail="Employee not found")

    before = EmployeeRead.model_validate(employee).model_dump(mode="json")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(employee, field, value)
    record_audit(
        db,
        action="employee.update",
        resource_type="employee",
        resource_id=str(employee.id),
        before=before,
        after=payload.model_dump(exclude_unset=True, mode="json"),
    )
    db.commit()
    db.refresh(employee)
    return employee
