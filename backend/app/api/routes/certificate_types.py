from __future__ import annotations

from fastapi import APIRouter, Depends, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models import CertificateType
from app.schemas.certificates import CertificateTypeCreate, CertificateTypeRead
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
