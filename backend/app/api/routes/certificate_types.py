from __future__ import annotations

import csv
from collections.abc import Iterable
from io import StringIO
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import Response
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.api.deps import RequestContext, audit_context_kwargs, get_request_context
from app.db.session import get_db
from app.models import CertificateType
from app.schemas.certificates import (
    CertificateTypeCreate,
    CertificateTypeImportErrorRead,
    CertificateTypeImportResultRead,
    CertificateTypePageRead,
    CertificateTypeRead,
    CertificateTypeUpdate,
)
from app.services.audit import record_audit

router = APIRouter()

_CERTIFICATE_TYPE_IMPORT_FIELD_ALIASES = {
    "编码": "code",
    "证书编码": "code",
    "code": "code",
    "证书类型": "name",
    "名称": "name",
    "name": "name",
    "发证机构": "issuing_authority",
    "issuing_authority": "issuing_authority",
    "issuing authority": "issuing_authority",
    "默认有效期(月)": "default_validity_months",
    "默认有效期": "default_validity_months",
    "default_validity_months": "default_validity_months",
    "default validity months": "default_validity_months",
    "强制复核": "force_manual_review",
    "force_manual_review": "force_manual_review",
    "force manual review": "force_manual_review",
    "说明": "description",
    "描述": "description",
    "description": "description",
}

_BOOLEAN_IMPORT_ALIASES = {
    "TRUE": True,
    "1": True,
    "YES": True,
    "Y": True,
    "是": True,
    "需要": True,
    "FALSE": False,
    "0": False,
    "NO": False,
    "N": False,
    "否": False,
    "不需要": False,
}


def _clean_cell(value: str | None) -> str | None:
    cleaned = value.strip() if value else ""
    return cleaned or None


def _normalized_import_key(value: str | None) -> str | None:
    if not value:
        return None
    return _CERTIFICATE_TYPE_IMPORT_FIELD_ALIASES.get(value.strip().lstrip("\ufeff").lower())


def _parse_optional_positive_int(value: str | None) -> int | None:
    if not value:
        return None
    try:
        parsed = int(value)
    except ValueError as exc:
        raise ValueError("默认有效期必须是正整数") from exc
    if parsed < 1:
        raise ValueError("默认有效期必须是正整数")
    return parsed


def _parse_force_manual_review(value: str | None) -> bool:
    if not value:
        return True
    normalized = value.strip().upper()
    parsed = _BOOLEAN_IMPORT_ALIASES.get(normalized) or _BOOLEAN_IMPORT_ALIASES.get(value.strip())
    if parsed is None:
        raise ValueError("强制复核必须是 是、否、true、false、1 或 0")
    return parsed


def decode_certificate_type_import_csv(content: bytes) -> str:
    try:
        return content.decode("utf-8-sig")
    except UnicodeDecodeError:
        return content.decode("gb18030")


def parse_certificate_type_import_csv(
    content: str,
) -> tuple[list[tuple[int, CertificateTypeCreate]], list[CertificateTypeImportErrorRead]]:
    reader = csv.DictReader(StringIO(content))
    if not reader.fieldnames:
        return [], [CertificateTypeImportErrorRead(row_number=1, message="CSV 缺少表头")]

    rows: list[tuple[int, CertificateTypeCreate]] = []
    errors: list[CertificateTypeImportErrorRead] = []
    for row_number, raw_row in enumerate(reader, start=2):
        normalized_row: dict[str, str | None] = {}
        for key, value in raw_row.items():
            normalized_key = _normalized_import_key(key)
            if normalized_key:
                normalized_row[normalized_key] = _clean_cell(value)

        if not any(normalized_row.values()):
            continue

        code = normalized_row.get("code")
        name = normalized_row.get("name")
        if not code or not name:
            errors.append(
                CertificateTypeImportErrorRead(
                    row_number=row_number,
                    code=code,
                    message="编码和证书类型不能为空",
                )
            )
            continue

        try:
            payload = CertificateTypeCreate(
                code=code,
                name=name,
                issuing_authority=normalized_row.get("issuing_authority"),
                default_validity_months=_parse_optional_positive_int(
                    normalized_row.get("default_validity_months")
                ),
                force_manual_review=_parse_force_manual_review(normalized_row.get("force_manual_review")),
                description=normalized_row.get("description"),
            )
        except ValueError as exc:
            errors.append(CertificateTypeImportErrorRead(row_number=row_number, code=code, message=str(exc)))
            continue
        rows.append((row_number, payload))

    return rows, errors


def import_certificate_type_rows(
    db: Session,
    rows: Iterable[tuple[int, CertificateTypeCreate]],
    *,
    initial_errors: list[CertificateTypeImportErrorRead] | None = None,
    request_context: RequestContext | None = None,
) -> CertificateTypeImportResultRead:
    row_list = list(rows)
    codes = {payload.code for _, payload in row_list}
    existing_by_code: dict[str, CertificateType] = {}
    if codes:
        existing_by_code = {
            certificate_type.code: certificate_type
            for certificate_type in db.scalars(select(CertificateType).where(CertificateType.code.in_(codes))).all()
        }

    created = 0
    updated = 0
    for _, payload in row_list:
        certificate_type = existing_by_code.get(payload.code)
        payload_data = payload.model_dump()
        if certificate_type:
            before = CertificateTypeRead.model_validate(certificate_type).model_dump(mode="json")
            for field, value in payload_data.items():
                if field != "code":
                    setattr(certificate_type, field, value)
            record_audit(
                db,
                action="certificate_type.import.update",
                resource_type="certificate_type",
                resource_id=str(certificate_type.id),
                before=before,
                after=payload.model_dump(mode="json"),
                **audit_context_kwargs(request_context),
            )
            updated += 1
        else:
            certificate_type = CertificateType(**payload_data)
            db.add(certificate_type)
            db.flush()
            existing_by_code[payload.code] = certificate_type
            record_audit(
                db,
                action="certificate_type.import.create",
                resource_type="certificate_type",
                resource_id=str(certificate_type.id),
                after=payload.model_dump(mode="json"),
                **audit_context_kwargs(request_context),
            )
            created += 1

    db.commit()
    errors = initial_errors or []
    return CertificateTypeImportResultRead(
        total=len(row_list) + len(errors),
        created=created,
        updated=updated,
        failed=len(errors),
        errors=errors,
    )


def _certificate_type_statement(
    *,
    keyword: str | None = None,
    code: str | None = None,
    name: str | None = None,
    issuing_authority: str | None = None,
    force_manual_review: bool | None = None,
):
    statement = select(CertificateType)
    if keyword:
        like = f"%{keyword.strip()}%"
        statement = statement.where(
            or_(
                CertificateType.code.ilike(like),
                CertificateType.name.ilike(like),
                CertificateType.issuing_authority.ilike(like),
                CertificateType.description.ilike(like),
            )
        )
    if code:
        statement = statement.where(CertificateType.code.ilike(f"%{code.strip()}%"))
    if name:
        statement = statement.where(CertificateType.name.ilike(f"%{name.strip()}%"))
    if issuing_authority:
        statement = statement.where(CertificateType.issuing_authority.ilike(f"%{issuing_authority.strip()}%"))
    if force_manual_review is not None:
        statement = statement.where(CertificateType.force_manual_review == force_manual_review)
    return statement


def build_certificate_types_csv(rows: Iterable[CertificateType]) -> str:
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(["编码", "证书类型", "发证机构", "默认有效期(月)", "强制复核", "说明"])
    for row in rows:
        writer.writerow([
            row.code,
            row.name,
            row.issuing_authority or "",
            row.default_validity_months or "",
            "是" if row.force_manual_review else "否",
            row.description or "",
        ])
    return "\ufeff" + output.getvalue()


@router.get("", response_model=list[CertificateTypeRead])
def list_certificate_types(db: Session = Depends(get_db)) -> list[CertificateType]:
    return list(db.scalars(select(CertificateType).order_by(CertificateType.name.asc())).all())


@router.get("/page", response_model=CertificateTypePageRead)
def page_certificate_types(
    db: Session = Depends(get_db),
    current: int = 1,
    page_size: int = 20,
    keyword: str | None = None,
    code: str | None = None,
    name: str | None = None,
    issuing_authority: str | None = None,
    force_manual_review: bool | None = None,
) -> CertificateTypePageRead:
    current = max(current, 1)
    page_size = min(max(page_size, 1), 200)
    filtered = _certificate_type_statement(
        keyword=keyword,
        code=code,
        name=name,
        issuing_authority=issuing_authority,
        force_manual_review=force_manual_review,
    )
    total = int(db.scalar(select(func.count()).select_from(filtered.subquery())) or 0)
    rows = db.scalars(
        filtered.order_by(CertificateType.name.asc()).limit(page_size).offset((current - 1) * page_size)
    ).all()
    return CertificateTypePageRead(data=[CertificateTypeRead.model_validate(row) for row in rows], total=total)


@router.get("/export.csv")
def export_certificate_types_csv(
    db: Session = Depends(get_db),
    keyword: str | None = None,
    code: str | None = None,
    name: str | None = None,
    issuing_authority: str | None = None,
    force_manual_review: bool | None = None,
) -> Response:
    rows = db.scalars(
        _certificate_type_statement(
            keyword=keyword,
            code=code,
            name=name,
            issuing_authority=issuing_authority,
            force_manual_review=force_manual_review,
        ).order_by(CertificateType.name.asc())
    ).all()
    return Response(
        content=build_certificate_types_csv(rows),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="certificate-types.csv"'},
    )


@router.post("/import.csv", response_model=CertificateTypeImportResultRead)
async def import_certificate_types_csv(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    request_context: RequestContext | None = Depends(get_request_context),
) -> CertificateTypeImportResultRead:
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="CSV 文件不能为空")

    rows, errors = parse_certificate_type_import_csv(decode_certificate_type_import_csv(content))
    if not rows and errors:
        return CertificateTypeImportResultRead(
            total=len(errors),
            created=0,
            updated=0,
            failed=len(errors),
            errors=errors,
        )
    return import_certificate_type_rows(db, rows, initial_errors=errors, request_context=request_context)


@router.post("", response_model=CertificateTypeRead, status_code=status.HTTP_201_CREATED)
def create_certificate_type(
    payload: CertificateTypeCreate,
    db: Session = Depends(get_db),
    request_context: RequestContext | None = Depends(get_request_context),
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
        **audit_context_kwargs(request_context),
    )
    db.commit()
    db.refresh(certificate_type)
    return certificate_type


@router.patch("/{certificate_type_id}", response_model=CertificateTypeRead)
def update_certificate_type(
    certificate_type_id: UUID,
    payload: CertificateTypeUpdate,
    db: Session = Depends(get_db),
    request_context: RequestContext | None = Depends(get_request_context),
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
        **audit_context_kwargs(request_context),
    )
    db.commit()
    db.refresh(certificate_type)
    return certificate_type
