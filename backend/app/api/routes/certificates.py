from __future__ import annotations

import csv
from collections.abc import Iterable, Mapping
from datetime import UTC, date, datetime
from io import StringIO
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import Response
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.api.deps import RequestContext, audit_context_kwargs, get_request_context
from app.db.session import get_db
from app.domain.enums import CertificateStatus
from app.models import (
    AiExtractionResult,
    AuditLog,
    CertificateType,
    Employee,
    EmployeeCertificate,
    Feedback,
    ReviewTask,
)
from app.schemas.certificates import (
    EmployeeCertificateCreate,
    EmployeeCertificatePageRead,
    EmployeeCertificateRead,
    EmployeeCertificateTraceRead,
    EmployeeCertificateUpdate,
    TraceAiExtractionResultRead,
    TraceAuditLogRead,
    TraceCertificateTypeRead,
    TraceDocumentRead,
    TraceFeedbackRead,
    TraceReminderTaskRead,
    TraceReviewTaskRead,
)
from app.schemas.employees import EmployeeRead
from app.services.audit import record_audit
from app.services.certificates import (
    is_current_certificate_status,
    replace_active_certificates,
    validate_certificate_business_rules,
    validate_certificate_dates,
)

router = APIRouter()


def _certificate_statement(
    *,
    keyword: str | None = None,
    employee_id: UUID | None = None,
    certificate_type_id: UUID | None = None,
    holder_name: str | None = None,
    certificate_no: str | None = None,
    issuing_authority: str | None = None,
    status_filter: CertificateStatus | None = None,
    status_group: str | None = None,
    valid_to_from: date | None = None,
    valid_to_to: date | None = None,
):
    statement = select(EmployeeCertificate)
    if keyword:
        like = f"%{keyword.strip()}%"
        statement = statement.where(
            or_(
                EmployeeCertificate.holder_name.ilike(like),
                EmployeeCertificate.certificate_no.ilike(like),
                EmployeeCertificate.issuing_authority.ilike(like),
            )
        )
    if employee_id:
        statement = statement.where(EmployeeCertificate.employee_id == employee_id)
    if certificate_type_id:
        statement = statement.where(EmployeeCertificate.certificate_type_id == certificate_type_id)
    if holder_name:
        statement = statement.where(EmployeeCertificate.holder_name.ilike(f"%{holder_name.strip()}%"))
    if certificate_no:
        statement = statement.where(EmployeeCertificate.certificate_no.ilike(f"%{certificate_no.strip()}%"))
    if issuing_authority:
        statement = statement.where(EmployeeCertificate.issuing_authority.ilike(f"%{issuing_authority.strip()}%"))
    if status_filter:
        statement = statement.where(EmployeeCertificate.status == status_filter)
    elif status_group == "current":
        statement = statement.where(
            EmployeeCertificate.status.in_([CertificateStatus.ACTIVE, CertificateStatus.EXPIRING])
        )
    elif status_group == "risk":
        statement = statement.where(
            EmployeeCertificate.status.in_([CertificateStatus.EXPIRING, CertificateStatus.EXPIRED])
        )
    if valid_to_from:
        statement = statement.where(EmployeeCertificate.valid_to >= valid_to_from)
    if valid_to_to:
        statement = statement.where(EmployeeCertificate.valid_to <= valid_to_to)
    return statement


def build_employee_certificates_csv(
    rows: Iterable[EmployeeCertificate],
    *,
    employee_names: Mapping[UUID, str],
    certificate_type_names: Mapping[UUID, str],
) -> str:
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "员工",
        "证书类型",
        "持证人",
        "证书编号",
        "发证机构",
        "发证日期",
        "有效开始",
        "到期日期",
        "状态",
        "确认人",
        "确认时间",
    ])
    for row in rows:
        writer.writerow([
            employee_names.get(row.employee_id, str(row.employee_id)),
            certificate_type_names.get(row.certificate_type_id, str(row.certificate_type_id)),
            row.holder_name,
            row.certificate_no or "",
            row.issuing_authority or "",
            row.issue_date.isoformat() if row.issue_date else "",
            row.valid_from.isoformat() if row.valid_from else "",
            row.valid_to.isoformat() if row.valid_to else "",
            row.status.value,
            row.confirmed_by or "",
            row.confirmed_at.isoformat() if row.confirmed_at else "",
        ])
    return "\ufeff" + output.getvalue()


def _load_certificate_export_labels(
    db: Session,
    rows: Iterable[EmployeeCertificate],
) -> tuple[dict[UUID, str], dict[UUID, str]]:
    row_list = list(rows)
    employee_ids = {row.employee_id for row in row_list}
    certificate_type_ids = {row.certificate_type_id for row in row_list}
    employee_names: dict[UUID, str] = {}
    certificate_type_names: dict[UUID, str] = {}

    if employee_ids:
        employee_names = {
            employee.id: f"{employee.name}（{employee.employee_no}）"
            for employee in db.scalars(select(Employee).where(Employee.id.in_(employee_ids))).all()
        }
    if certificate_type_ids:
        certificate_type_names = {
            certificate_type.id: certificate_type.name
            for certificate_type in db.scalars(
                select(CertificateType).where(CertificateType.id.in_(certificate_type_ids))
            ).all()
        }

    return employee_names, certificate_type_names


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


@router.get("/page", response_model=EmployeeCertificatePageRead)
def page_employee_certificates(
    db: Session = Depends(get_db),
    current: int = 1,
    page_size: int = 20,
    keyword: str | None = None,
    employee_id: UUID | None = None,
    certificate_type_id: UUID | None = None,
    holder_name: str | None = None,
    certificate_no: str | None = None,
    issuing_authority: str | None = None,
    status: CertificateStatus | None = None,
    status_group: str | None = None,
    valid_to_from: date | None = None,
    valid_to_to: date | None = None,
) -> EmployeeCertificatePageRead:
    current = max(current, 1)
    page_size = min(max(page_size, 1), 200)
    filtered = _certificate_statement(
        keyword=keyword,
        employee_id=employee_id,
        certificate_type_id=certificate_type_id,
        holder_name=holder_name,
        certificate_no=certificate_no,
        issuing_authority=issuing_authority,
        status_filter=status,
        status_group=status_group,
        valid_to_from=valid_to_from,
        valid_to_to=valid_to_to,
    )
    total = int(db.scalar(select(func.count()).select_from(filtered.subquery())) or 0)
    rows = db.scalars(
        filtered.order_by(EmployeeCertificate.created_at.desc()).limit(page_size).offset((current - 1) * page_size)
    ).all()
    return EmployeeCertificatePageRead(data=[EmployeeCertificateRead.model_validate(row) for row in rows], total=total)


@router.get("/export.csv")
def export_employee_certificates_csv(
    db: Session = Depends(get_db),
    keyword: str | None = None,
    employee_id: UUID | None = None,
    certificate_type_id: UUID | None = None,
    holder_name: str | None = None,
    certificate_no: str | None = None,
    issuing_authority: str | None = None,
    status: CertificateStatus | None = None,
    status_group: str | None = None,
    valid_to_from: date | None = None,
    valid_to_to: date | None = None,
) -> Response:
    rows = db.scalars(
        _certificate_statement(
            keyword=keyword,
            employee_id=employee_id,
            certificate_type_id=certificate_type_id,
            holder_name=holder_name,
            certificate_no=certificate_no,
            issuing_authority=issuing_authority,
            status_filter=status,
            status_group=status_group,
            valid_to_from=valid_to_from,
            valid_to_to=valid_to_to,
        ).order_by(EmployeeCertificate.created_at.desc())
    ).all()
    employee_names, certificate_type_names = _load_certificate_export_labels(db, rows)
    return Response(
        content=build_employee_certificates_csv(
            rows,
            employee_names=employee_names,
            certificate_type_names=certificate_type_names,
        ),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="employee-certificates.csv"'},
    )


def _load_certificate_trace_audit_logs(db: Session, certificate: EmployeeCertificate) -> list[AuditLog]:
    resource_ids = {str(certificate.id)}
    resource_ids.add(str(certificate.employee_id))
    resource_ids.add(str(certificate.certificate_type_id))
    if certificate.source_document_id:
        resource_ids.add(str(certificate.source_document_id))

    direct_logs = list(
        db.scalars(
            select(AuditLog)
            .where(AuditLog.resource_id.in_(resource_ids))
            .order_by(AuditLog.created_at.desc())
            .limit(80)
        ).all()
    )
    certificate_id_text = str(certificate.id)
    review_logs = [
        log
        for log in db.scalars(
            select(AuditLog)
            .where(AuditLog.resource_type == "review_task")
            .order_by(AuditLog.created_at.desc())
            .limit(200)
        ).all()
        if isinstance(log.after, dict) and log.after.get("certificate_id") == certificate_id_text
    ]
    logs_by_id = {log.id: log for log in direct_logs + review_logs}
    return sorted(logs_by_id.values(), key=lambda log: log.created_at, reverse=True)[:100]


@router.get("/{certificate_id}/trace", response_model=EmployeeCertificateTraceRead)
def get_employee_certificate_trace(
    certificate_id: UUID,
    db: Session = Depends(get_db),
) -> EmployeeCertificateTraceRead:
    certificate = db.scalar(
        select(EmployeeCertificate)
        .options(
            selectinload(EmployeeCertificate.employee),
            selectinload(EmployeeCertificate.certificate_type),
            selectinload(EmployeeCertificate.source_document),
            selectinload(EmployeeCertificate.reminder_tasks),
        )
        .where(EmployeeCertificate.id == certificate_id)
    )
    if not certificate:
        raise HTTPException(status_code=404, detail="Employee certificate not found")

    ai_results: list[AiExtractionResult] = []
    review_tasks: list[ReviewTask] = []
    if certificate.source_document_id:
        ai_results = list(
            db.scalars(
                select(AiExtractionResult)
                .where(AiExtractionResult.document_id == certificate.source_document_id)
                .order_by(AiExtractionResult.created_at.desc())
            ).all()
        )
        review_tasks = list(
            db.scalars(
                select(ReviewTask)
                .where(ReviewTask.document_id == certificate.source_document_id)
                .order_by(ReviewTask.created_at.desc())
            ).all()
        )

    reminder_task_ids = [task.id for task in certificate.reminder_tasks]
    feedback_items = (
        list(
            db.scalars(
                select(Feedback)
                .where(Feedback.reminder_task_id.in_(reminder_task_ids))
                .order_by(Feedback.created_at.desc())
            ).all()
        )
        if reminder_task_ids
        else []
    )
    audit_logs = _load_certificate_trace_audit_logs(db, certificate)

    return EmployeeCertificateTraceRead(
        certificate=EmployeeCertificateRead.model_validate(certificate),
        employee=EmployeeRead.model_validate(certificate.employee) if certificate.employee else None,
        certificate_type=(
            TraceCertificateTypeRead(
                id=certificate.certificate_type.id,
                code=certificate.certificate_type.code,
                name=certificate.certificate_type.name,
                issuing_authority=certificate.certificate_type.issuing_authority,
            )
            if certificate.certificate_type
            else None
        ),
        source_document=(
            TraceDocumentRead(
                id=certificate.source_document.id,
                status=certificate.source_document.status.value,
                storage_key=certificate.source_document.storage_key,
                original_filename=certificate.source_document.original_filename,
                content_type=certificate.source_document.content_type,
                file_size=certificate.source_document.file_size,
                sha256=certificate.source_document.sha256,
                failure_reason=certificate.source_document.failure_reason,
                created_at=certificate.source_document.created_at,
                updated_at=certificate.source_document.updated_at,
            )
            if certificate.source_document
            else None
        ),
        ai_results=[
            TraceAiExtractionResultRead(
                id=result.id,
                document_id=result.document_id,
                workflow_run_id=result.workflow_run_id,
                model_name=result.model_name,
                output_json=result.output_json,
                suspicious_points=result.suspicious_points,
                confidence=float(result.confidence) if result.confidence is not None else None,
                created_at=result.created_at,
            )
            for result in ai_results
        ],
        review_tasks=[
            TraceReviewTaskRead(
                id=task.id,
                document_id=task.document_id,
                ai_result_id=task.ai_result_id,
                status=task.status,
                assigned_to=task.assigned_to,
                reviewed_by=task.reviewed_by,
                reviewed_at=task.reviewed_at,
                decision_payload=task.decision_payload,
                notes=task.notes,
                created_at=task.created_at,
                updated_at=task.updated_at,
            )
            for task in review_tasks
        ],
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
            for task in certificate.reminder_tasks
        ],
        feedback_items=[
            TraceFeedbackRead(
                id=feedback.id,
                reminder_task_id=feedback.reminder_task_id,
                status=feedback.status,
                content=feedback.content,
                created_by=feedback.created_by,
                created_at=feedback.created_at,
            )
            for feedback in feedback_items
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


@router.post("", response_model=EmployeeCertificateRead, status_code=status.HTTP_201_CREATED)
def create_employee_certificate(
    payload: EmployeeCertificateCreate,
    db: Session = Depends(get_db),
    request_context: RequestContext | None = Depends(get_request_context),
) -> EmployeeCertificate:
    target_status = payload.status
    validate_certificate_dates(
        issue_date=payload.issue_date,
        valid_from=payload.valid_from,
        valid_to=payload.valid_to,
    )
    validate_certificate_business_rules(
        db,
        employee_id=payload.employee_id,
        certificate_type_id=payload.certificate_type_id,
        holder_name=payload.holder_name,
        certificate_no=payload.certificate_no,
        require_active_employee=is_current_certificate_status(target_status),
    )
    now = datetime.now(UTC)
    certificate_status = CertificateStatus.DRAFT if is_current_certificate_status(target_status) else target_status
    certificate = EmployeeCertificate(
        **payload.model_dump(exclude={"confirmed_by", "status"}),
        status=certificate_status,
        confirmed_by=payload.confirmed_by,
        confirmed_at=now if payload.confirmed_by else None,
    )
    db.add(certificate)
    db.flush()
    replaced_certificates = replace_active_certificates(db, certificate, now=now, target_status=target_status)
    if certificate.status != target_status:
        certificate.status = target_status
        db.flush()
    record_audit(
        db,
        action="employee_certificate.create",
        resource_type="employee_certificate",
        resource_id=str(certificate.id),
        after={
            **payload.model_dump(mode="json"),
            "replaced_certificate_ids": [str(item.id) for item in replaced_certificates],
        },
        **audit_context_kwargs(request_context),
    )
    db.commit()
    db.refresh(certificate)
    return certificate


@router.patch("/{certificate_id}", response_model=EmployeeCertificateRead)
def update_employee_certificate(
    certificate_id: UUID,
    payload: EmployeeCertificateUpdate,
    db: Session = Depends(get_db),
    request_context: RequestContext | None = Depends(get_request_context),
) -> EmployeeCertificate:
    certificate = db.get(EmployeeCertificate, certificate_id)
    if not certificate:
        raise HTTPException(status_code=404, detail="Employee certificate not found")

    update_data = payload.model_dump(exclude_unset=True)
    issue_date = update_data.get("issue_date", certificate.issue_date)
    valid_from = update_data.get("valid_from", certificate.valid_from)
    valid_to = update_data.get("valid_to", certificate.valid_to)
    validate_certificate_dates(issue_date=issue_date, valid_from=valid_from, valid_to=valid_to)
    target_status = update_data.get("status", certificate.status)
    validate_certificate_business_rules(
        db,
        employee_id=update_data.get("employee_id", certificate.employee_id),
        certificate_type_id=update_data.get("certificate_type_id", certificate.certificate_type_id),
        holder_name=update_data.get("holder_name", certificate.holder_name),
        certificate_no=update_data.get("certificate_no", certificate.certificate_no),
        exclude_certificate_id=certificate.id,
        require_active_employee=is_current_certificate_status(target_status),
    )

    before = EmployeeCertificateRead.model_validate(certificate).model_dump(mode="json")
    target_status = update_data.pop("status", certificate.status)
    needs_current_replacement = is_current_certificate_status(target_status)
    original_status = certificate.status
    if needs_current_replacement and is_current_certificate_status(certificate.status):
        certificate.status = CertificateStatus.DRAFT
        db.flush()

    for field, value in update_data.items():
        setattr(certificate, field, value)

    now = datetime.now(UTC)
    if "confirmed_by" in update_data:
        certificate.confirmed_at = now if update_data["confirmed_by"] else None
    replaced_certificates = replace_active_certificates(db, certificate, now=now, target_status=target_status)
    if certificate.status != target_status:
        certificate.status = target_status
    if certificate.status != original_status or update_data or "confirmed_by" in update_data:
        db.flush()
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
        **audit_context_kwargs(request_context),
    )
    db.commit()
    db.refresh(certificate)
    return certificate
