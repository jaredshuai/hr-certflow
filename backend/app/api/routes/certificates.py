from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models import EmployeeCertificate
from app.schemas.certificates import EmployeeCertificateCreate, EmployeeCertificateRead
from app.services.audit import record_audit

router = APIRouter()


@router.get("", response_model=list[EmployeeCertificateRead])
def list_employee_certificates(
    db: Session = Depends(get_db),
    limit: int = 100,
    offset: int = 0,
) -> list[EmployeeCertificate]:
    statement = (
        select(EmployeeCertificate)
        .order_by(EmployeeCertificate.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return list(db.scalars(statement).all())


@router.post("", response_model=EmployeeCertificateRead, status_code=status.HTTP_201_CREATED)
def create_employee_certificate(
    payload: EmployeeCertificateCreate,
    db: Session = Depends(get_db),
) -> EmployeeCertificate:
    certificate = EmployeeCertificate(
        **payload.model_dump(exclude={"confirmed_by"}),
        confirmed_by=payload.confirmed_by,
        confirmed_at=datetime.now(UTC) if payload.confirmed_by else None,
    )
    db.add(certificate)
    db.flush()
    record_audit(
        db,
        action="employee_certificate.create",
        resource_type="employee_certificate",
        resource_id=str(certificate.id),
        after=payload.model_dump(mode="json"),
    )
    db.commit()
    db.refresh(certificate)
    return certificate
