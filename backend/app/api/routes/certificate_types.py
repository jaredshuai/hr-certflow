from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models import CertificateType
from app.schemas.certificates import CertificateTypeCreate, CertificateTypeRead, CertificateTypeUpdate
from app.services.audit import record_audit

router = APIRouter()


@router.get("", response_model=list[CertificateTypeRead])
def list_certificate_types(db: Session = Depends(get_db)) -> list[CertificateType]:
    return list(db.scalars(select(CertificateType).order_by(CertificateType.name.asc())).all())


@router.post("", response_model=CertificateTypeRead, status_code=status.HTTP_201_CREATED)
def create_certificate_type(
    payload: CertificateTypeCreate,
    db: Session = Depends(get_db),
) -> CertificateType:
    certificate_type = CertificateType(**payload.model_dump())
    db.add(certificate_type)
    db.flush()
    record_audit(
        db,
        action="certificate_type.create",
        resource_type="certificate_type",
        resource_id=str(certificate_type.id),
        after=payload.model_dump(mode="json"),
    )
    db.commit()
    db.refresh(certificate_type)
    return certificate_type


@router.patch("/{certificate_type_id}", response_model=CertificateTypeRead)
def update_certificate_type(
    certificate_type_id: UUID,
    payload: CertificateTypeUpdate,
    db: Session = Depends(get_db),
) -> CertificateType:
    certificate_type = db.get(CertificateType, certificate_type_id)
    if not certificate_type:
        raise HTTPException(status_code=404, detail="Certificate type not found")

    before = CertificateTypeRead.model_validate(certificate_type).model_dump(mode="json")
    update_data = payload.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(certificate_type, field, value)

    record_audit(
        db,
        action="certificate_type.update",
        resource_type="certificate_type",
        resource_id=str(certificate_type.id),
        before=before,
        after=payload.model_dump(exclude_unset=True, mode="json"),
    )
    db.commit()
    db.refresh(certificate_type)
    return certificate_type
