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
from app.models import AuditLog, CertificateType, EmployeeCertificate, ReminderPolicy, ReminderTask
from app.schemas.certificates import (
    CertificateTypeCreate,
    CertificateTypeDefaultReminderPolicyRead,
    CertificateTypeDefaultReminderPolicyUpsert,
    CertificateTypeImportErrorRead,
    CertificateTypeImportResultRead,
    CertificateTypePageRead,
    CertificateTypeRead,
    CertificateTypeTraceRead,
    CertificateTypeUpdate,
    EmployeeCertificateRead,
    TraceAuditLogRead,
    TraceReminderPolicyRead,
    TraceReminderTaskRead,
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
    "是否必备": "is_required",
    "必备": "is_required",
    "必备证书": "is_required",
    "is_required": "is_required",
    "is required": "is_required",
    "required": "is_required",
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
    "必备": True,
    "FALSE": False,
    "0": False,
    "NO": False,
    "N": False,
    "否": False,
    "不需要": False,
    "可选": False,
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


def _parse_boolean_import(value: str | None, *, default: bool, message: str) -> bool:
    if not value:
        return default
    normalized = value.strip().upper()
    parsed = _BOOLEAN_IMPORT_ALIASES.get(normalized)
    if parsed is None:
        parsed = _BOOLEAN_IMPORT_ALIASES.get(value.strip())
    if parsed is None:
        raise ValueError(message)
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
    seen_codes: set[str] = set()
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

        if code in seen_codes:
            errors.append(
                CertificateTypeImportErrorRead(
                    row_number=row_number,
                    code=code,
                    message="同一导入文件内编码重复，请保留一行后重试",
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
                is_required=_parse_boolean_import(
                    normalized_row.get("is_required"),
                    default=True,
                    message="是否必备必须是 是、否、必备、可选、true、false、1 或 0",
                ),
                force_manual_review=_parse_boolean_import(
                    normalized_row.get("force_manual_review"),
                    default=True,
                    message="强制复核必须是 是、否、true、false、1 或 0",
                ),
                description=normalized_row.get("description"),
            )
        except ValueError as exc:
            errors.append(CertificateTypeImportErrorRead(row_number=row_number, code=code, message=str(exc)))
            continue
        seen_codes.add(code)
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
        payload_data = payload.model_dump(exclude={"default_reminder_policy"})
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


def _certificate_type_payload_data(
    payload: CertificateTypeCreate | CertificateTypeUpdate,
    *,
    exclude_unset: bool = False,
) -> dict:
    return payload.model_dump(exclude={"default_reminder_policy"}, exclude_unset=exclude_unset)


def _default_policy_name(certificate_type: CertificateType, payload: CertificateTypeDefaultReminderPolicyUpsert) -> str:
    return payload.name or f"{certificate_type.name}默认提醒"


def _policy_read(policy: ReminderPolicy | None) -> CertificateTypeDefaultReminderPolicyRead | None:
    if not policy:
        return None
    return CertificateTypeDefaultReminderPolicyRead(
        id=policy.id,
        name=policy.name,
        days_before_expiry=policy.days_before_expiry,
        second_reminder_after_days=policy.second_reminder_after_days,
        escalation_after_days=policy.escalation_after_days,
        channels=policy.channels,
        enabled=policy.enabled,
        updated_at=policy.updated_at,
    )


def _latest_type_policy(db: Session, certificate_type_id: UUID) -> ReminderPolicy | None:
    return db.scalar(
        select(ReminderPolicy)
        .where(ReminderPolicy.certificate_type_id == certificate_type_id)
        .order_by(ReminderPolicy.created_at.desc())
    )


def _certificate_type_to_read(
    db: Session,
    certificate_type: CertificateType,
    *,
    default_policy: ReminderPolicy | None = None,
    load_default_policy: bool = True,
) -> CertificateTypeRead:
    policy = default_policy
    if policy is None and load_default_policy:
        policy = _latest_type_policy(db, certificate_type.id)
    return CertificateTypeRead.model_validate(certificate_type).model_copy(
        update={"default_reminder_policy": _policy_read(policy)}
    )


def _upsert_default_reminder_policy(
    db: Session,
    *,
    certificate_type: CertificateType,
    payload: CertificateTypeDefaultReminderPolicyUpsert | None,
    request_context: RequestContext | None = None,
) -> ReminderPolicy | None:
    if payload is None:
        return None

    policy = _latest_type_policy(db, certificate_type.id)
    policy_data = payload.model_dump()
    policy_data["name"] = _default_policy_name(certificate_type, payload)
    if policy:
        before = {
            "name": policy.name,
            "days_before_expiry": policy.days_before_expiry,
            "second_reminder_after_days": policy.second_reminder_after_days,
            "escalation_after_days": policy.escalation_after_days,
            "channels": policy.channels,
            "enabled": policy.enabled,
        }
        for field, value in policy_data.items():
            setattr(policy, field, value)
        action = "certificate_type.default_reminder_policy.update"
    else:
        policy = ReminderPolicy(certificate_type_id=certificate_type.id, **policy_data)
        db.add(policy)
        action = "certificate_type.default_reminder_policy.create"
        before = None

    db.flush()
    after = {
        "certificate_type_id": str(certificate_type.id),
        "policy_id": str(policy.id),
        "name": policy.name,
        "days_before_expiry": policy.days_before_expiry,
        "second_reminder_after_days": policy.second_reminder_after_days,
        "escalation_after_days": policy.escalation_after_days,
        "channels": policy.channels,
        "enabled": policy.enabled,
    }
    record_audit(
        db,
        action=action,
        resource_type="reminder_policy",
        resource_id=str(policy.id),
        before=before,
        after=after,
        **audit_context_kwargs(request_context),
    )
    return policy


def _certificate_type_statement(
    *,
    keyword: str | None = None,
    code: str | None = None,
    name: str | None = None,
    issuing_authority: str | None = None,
    is_required: bool | None = None,
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
    if is_required is not None:
        statement = statement.where(CertificateType.is_required == is_required)
    if force_manual_review is not None:
        statement = statement.where(CertificateType.force_manual_review == force_manual_review)
    return statement


def build_certificate_types_csv(rows: Iterable[CertificateType]) -> str:
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(["编码", "证书类型", "发证机构", "默认有效期(月)", "是否必备", "强制复核", "说明"])
    for row in rows:
        writer.writerow([
            row.code,
            row.name,
            row.issuing_authority or "",
            row.default_validity_months or "",
            "是" if row.is_required else "否",
            "是" if row.force_manual_review else "否",
            row.description or "",
        ])
    return "\ufeff" + output.getvalue()


def build_certificate_type_import_template_csv() -> str:
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(["编码", "证书类型", "发证机构", "默认有效期(月)", "是否必备", "强制复核", "说明"])
    writer.writerow(["SAFETY", "安全员证", "住建局", "36", "是", "是", "施工现场安全管理"])
    return "\ufeff" + output.getvalue()


@router.get("", response_model=list[CertificateTypeRead])
def list_certificate_types(db: Session = Depends(get_db)) -> list[CertificateTypeRead]:
    rows = list(db.scalars(select(CertificateType).order_by(CertificateType.name.asc())).all())
    return [_certificate_type_to_read(db, row) for row in rows]


@router.get("/page", response_model=CertificateTypePageRead)
def page_certificate_types(
    db: Session = Depends(get_db),
    current: int = 1,
    page_size: int = 20,
    keyword: str | None = None,
    code: str | None = None,
    name: str | None = None,
    issuing_authority: str | None = None,
    is_required: bool | None = None,
    force_manual_review: bool | None = None,
) -> CertificateTypePageRead:
    current = max(current, 1)
    page_size = min(max(page_size, 1), 200)
    filtered = _certificate_type_statement(
        keyword=keyword,
        code=code,
        name=name,
        issuing_authority=issuing_authority,
        is_required=is_required,
        force_manual_review=force_manual_review,
    )
    total = int(db.scalar(select(func.count()).select_from(filtered.subquery())) or 0)
    rows = db.scalars(
        filtered.order_by(CertificateType.name.asc()).limit(page_size).offset((current - 1) * page_size)
    ).all()
    return CertificateTypePageRead(data=[_certificate_type_to_read(db, row) for row in rows], total=total)


@router.get("/export.csv")
def export_certificate_types_csv(
    db: Session = Depends(get_db),
    keyword: str | None = None,
    code: str | None = None,
    name: str | None = None,
    issuing_authority: str | None = None,
    is_required: bool | None = None,
    force_manual_review: bool | None = None,
) -> Response:
    rows = db.scalars(
        _certificate_type_statement(
            keyword=keyword,
            code=code,
            name=name,
            issuing_authority=issuing_authority,
            is_required=is_required,
            force_manual_review=force_manual_review,
        ).order_by(CertificateType.name.asc())
    ).all()
    return Response(
        content=build_certificate_types_csv(rows),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="certificate-types.csv"'},
    )


@router.get("/import-template.csv")
def export_certificate_type_import_template_csv() -> Response:
    return Response(
        content=build_certificate_type_import_template_csv(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="certificate-types-import-template.csv"'},
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


def _load_certificate_type_trace_audit_logs(
    db: Session,
    *,
    certificate_type: CertificateType,
    policies: Iterable[ReminderPolicy],
    certificates: Iterable[EmployeeCertificate],
    reminder_tasks: Iterable[ReminderTask],
) -> list[AuditLog]:
    resource_ids = {str(certificate_type.id)}
    resource_ids.update(str(policy.id) for policy in policies)
    resource_ids.update(str(certificate.id) for certificate in certificates)
    resource_ids.update(str(task.id) for task in reminder_tasks)
    return list(
        db.scalars(
            select(AuditLog)
            .where(AuditLog.resource_id.in_(resource_ids))
            .order_by(AuditLog.created_at.desc())
            .limit(100)
        ).all()
    )


@router.get("/{certificate_type_id}/trace", response_model=CertificateTypeTraceRead)
def get_certificate_type_trace(
    certificate_type_id: UUID,
    db: Session = Depends(get_db),
) -> CertificateTypeTraceRead:
    certificate_type = db.get(CertificateType, certificate_type_id)
    if not certificate_type:
        raise HTTPException(status_code=404, detail="Certificate type not found")

    policies = list(
        db.scalars(
            select(ReminderPolicy)
            .where(ReminderPolicy.certificate_type_id == certificate_type.id)
            .order_by(ReminderPolicy.created_at.desc())
        ).all()
    )
    certificates = list(
        db.scalars(
            select(EmployeeCertificate)
            .where(EmployeeCertificate.certificate_type_id == certificate_type.id)
            .order_by(EmployeeCertificate.created_at.desc())
        ).all()
    )
    certificate_ids = [certificate.id for certificate in certificates]
    reminder_tasks = (
        list(
            db.scalars(
                select(ReminderTask)
                .where(ReminderTask.employee_certificate_id.in_(certificate_ids))
                .order_by(ReminderTask.created_at.desc())
            ).all()
        )
        if certificate_ids
        else []
    )
    audit_logs = _load_certificate_type_trace_audit_logs(
        db,
        certificate_type=certificate_type,
        policies=policies,
        certificates=certificates,
        reminder_tasks=reminder_tasks,
    )

    return CertificateTypeTraceRead(
        certificate_type=_certificate_type_to_read(
            db,
            certificate_type,
            default_policy=policies[0] if policies else None,
            load_default_policy=False,
        ),
        reminder_policies=[
            TraceReminderPolicyRead(
                id=policy.id,
                certificate_type_id=policy.certificate_type_id,
                name=policy.name,
                days_before_expiry=policy.days_before_expiry,
                second_reminder_after_days=policy.second_reminder_after_days,
                escalation_after_days=policy.escalation_after_days,
                channels=policy.channels,
                enabled=policy.enabled,
                created_at=policy.created_at,
                updated_at=policy.updated_at,
            )
            for policy in policies
        ],
        certificates=[EmployeeCertificateRead.model_validate(certificate) for certificate in certificates],
        reminder_tasks=[
            TraceReminderTaskRead(
                id=task.id,
                status=task.status,
                trigger_date=task.trigger_date,
                due_date=task.due_date,
                last_event_at=task.last_event_at,
                resolved_at=task.resolved_at,
                closed_reason=task.closed_reason,
            )
            for task in reminder_tasks
        ],
        audit_logs=[
            TraceAuditLogRead(
                id=log.id,
                action=log.action,
                resource_type=log.resource_type,
                resource_id=log.resource_id,
                actor_name=log.actor_name,
                request_id=log.request_id,
                ip_address=log.ip_address,
                created_at=log.created_at,
            )
            for log in audit_logs
        ],
    )


@router.post("", response_model=CertificateTypeRead, status_code=status.HTTP_201_CREATED)
def create_certificate_type(
    payload: CertificateTypeCreate,
    db: Session = Depends(get_db),
    request_context: RequestContext | None = Depends(get_request_context),
) -> CertificateTypeRead:
    certificate_type = CertificateType(**_certificate_type_payload_data(payload))
    db.add(certificate_type)
    db.flush()
    _upsert_default_reminder_policy(
        db,
        certificate_type=certificate_type,
        payload=payload.default_reminder_policy,
        request_context=request_context,
    )
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
    return _certificate_type_to_read(db, certificate_type)


@router.patch("/{certificate_type_id}", response_model=CertificateTypeRead)
def update_certificate_type(
    certificate_type_id: UUID,
    payload: CertificateTypeUpdate,
    db: Session = Depends(get_db),
    request_context: RequestContext | None = Depends(get_request_context),
) -> CertificateTypeRead:
    certificate_type = db.get(CertificateType, certificate_type_id)
    if not certificate_type:
        raise HTTPException(status_code=404, detail="Certificate type not found")

    before = CertificateTypeRead.model_validate(certificate_type).model_dump(mode="json")
    update_data = _certificate_type_payload_data(payload, exclude_unset=True)
    for field, value in update_data.items():
        setattr(certificate_type, field, value)
    db.flush()
    _upsert_default_reminder_policy(
        db,
        certificate_type=certificate_type,
        payload=payload.default_reminder_policy,
        request_context=request_context,
    )

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
    return _certificate_type_to_read(db, certificate_type)
