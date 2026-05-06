from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models import EmployeeCertificate
from app.schemas.certificates import EmployeeCertificateCreate, EmployeeCertificateRead, EmployeeCertificateUpdate
from app.services.audit import record_audit
from app.services.certificates import replace_active_certificates, validate_certificate_dates

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
    validate_certificate_dates(
        issue_date=payload.issue_date,
        valid_from=payload.valid_from,
        valid_to=payload.valid_to,
    )
    now = datetime.now(UTC)
    certificate = EmployeeCertificate(
        **payload.model_dump(exclude={"confirmed_by"}),
        confirmed_by=payload.confirmed_by,
        confirmed_at=now if payload.confirmed_by else None,
    )
    db.add(certificate)
    db.flush()
    replaced_certificates = replace_active_certificates(db, certificate, now=now)
    record_audit(
        db,
        action="employee_certificate.create",
        resource_type="employee_certificate",
        resource_id=str(certificate.id),
        after={
            **payload.model_dump(mode="json"),
            "replaced_certificate_ids": [str(item.id) for item in replaced_certificates],
        },
    )
    db.commit()
    db.refresh(certificate)
    return certificate


@router.patch("/{certificate_id}", response_model=EmployeeCertificateRead)
def update_employee_certificate(
    certificate_id: UUID,
    payload: EmployeeCertificateUpdate,
    db: Session = Depends(get_db),
) -> EmployeeCertificate:
    certificate = db.get(EmployeeCertificate, certificate_id)
    if not certificate:
        raise HTTPException(status_code=404, detail="Employee certificate not found")

    update_data = payload.model_dump(exclude_unset=True)
    issue_date = update_data.get("issue_date", certificate.issue_date)
    valid_from = update_data.get("valid_from", certificate.valid_from)
    valid_to = update_data.get("valid_to", certificate.valid_to)
    validate_certificate_dates(issue_date=issue_date, valid_from=valid_from, valid_to=valid_to)

    before = EmployeeCertificateRead.model_validate(certificate).model_dump(mode="json")
    for field, value in update_data.items():
        setattr(certificate, field, value)

    now = datetime.now(UTC)
    if "confirmed_by" in update_data:
        certificate.confirmed_at = now if update_data["confirmed_by"] else None
    db.flush()
    replaced_certificates = replace_active_certificates(db, certificate, now=now)
    record_audit(
        db,
        action="employee_certificate.update",
        resource_type="employee_certificate",
        resource_id=str(certificate.id),
        before=before,
        after={
            **payload.model_dump(exclude_unset=True, mode="json"),
            "replaced_certificate_ids": [str(item.id) for item in replaced_certificates],
        },
    )
    db.commit()
    db.refresh(certificate)
    return certificate
