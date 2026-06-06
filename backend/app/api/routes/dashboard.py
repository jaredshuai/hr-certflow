from __future__ import annotations

from collections.abc import Iterable
from urllib.parse import urlencode
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.db.session import get_db
from app.domain.enums import CertificateStatus, DocumentStatus, EmploymentStatus, ReminderTaskStatus, ReviewStatus
from app.models import (
    AuditLog,
    CertificateDocument,
    CertificateType,
    Employee,
    EmployeeCertificate,
    ReminderTask,
    ReviewTask,
)
from app.schemas.certificates import EmployeeCertificateRead, TraceAuditLogRead
from app.schemas.dashboard import (
    DashboardChartRow,
    DashboardMissingRequiredItem,
    DashboardPipelineStep,
    DashboardRiskRow,
    DashboardRiskTraceRead,
    DashboardSummaryRead,
)
from app.schemas.documents import CertificateDocumentRead, ReviewTaskRead
from app.schemas.reminders import ReminderTaskRead

router = APIRouter()

CERTIFICATE_STATUS_LABELS = {
    CertificateStatus.DRAFT: "草稿",
    CertificateStatus.PENDING_REVIEW: "待复核",
    CertificateStatus.ACTIVE: "有效",
    CertificateStatus.EXPIRING: "即将到期",
    CertificateStatus.EXPIRED: "已过期",
    CertificateStatus.RENEWED: "已续证",
    CertificateStatus.REPLACED: "已替换",
    CertificateStatus.ARCHIVED: "已归档",
}

ACTIVE_COVERAGE_STATUSES = (CertificateStatus.ACTIVE, CertificateStatus.EXPIRING)
PENDING_REVIEW_STATUSES = (ReviewStatus.PENDING, ReviewStatus.NEEDS_INFO)
SECOND_REMINDER_STATUSES = (ReminderTaskStatus.SECOND_SENT, ReminderTaskStatus.ESCALATED)
OPEN_REMINDER_STATUSES = (
    ReminderTaskStatus.PENDING,
    ReminderTaskStatus.FIRST_SENT,
    ReminderTaskStatus.WAITING_FEEDBACK,
    ReminderTaskStatus.SECOND_SENT,
    ReminderTaskStatus.ESCALATED,
)
RISK_ROW_DEFINITIONS = {
    "expired-certificates": ("已过期证书", "需跟进", "/certificates?status=EXPIRED"),
    "failed-documents": ("识别失败文件", "需跟进", "/documents?status=FAILED"),
    "pending-reviews": ("待复核识别", "处理中", "/review-queue"),
    "second-reminders": ("二次或升级提醒", "升级前", "/reminders?status=SECOND_SENT&status=ESCALATED"),
    "missing-required-certificates": ("缺失必备证书", "需跟进", "/reports"),
}


def _count(db: Session, statement) -> int:
    return int(db.scalar(statement) or 0)


def _count_certificates(db: Session, *statuses: CertificateStatus) -> int:
    return _count(
        db,
        select(func.count()).select_from(EmployeeCertificate).where(EmployeeCertificate.status.in_(statuses)),
    )


def _count_documents(db: Session, *statuses: DocumentStatus) -> int:
    return _count(
        db,
        select(func.count()).select_from(CertificateDocument).where(CertificateDocument.status.in_(statuses)),
    )


def _count_reviews(db: Session, *statuses: ReviewStatus) -> int:
    return _count(
        db,
        select(func.count()).select_from(ReviewTask).where(ReviewTask.status.in_(statuses)),
    )


def _count_reminders(db: Session, *statuses: ReminderTaskStatus) -> int:
    return _count(
        db,
        select(func.count()).select_from(ReminderTask).where(ReminderTask.status.in_(statuses)),
    )


def _missing_required_certificate_items(
    db: Session,
    *,
    limit: int | None = None,
) -> list[DashboardMissingRequiredItem]:
    active_employees = list(
        db.scalars(
            select(Employee)
            .where(Employee.employment_status == EmploymentStatus.ACTIVE)
            .order_by(Employee.employee_no.asc())
        ).all()
    )
    required_types = list(
        db.scalars(
            select(CertificateType).where(CertificateType.is_required.is_(True)).order_by(CertificateType.name.asc())
        ).all()
    )
    if not active_employees or not required_types:
        return []

    active_employee_ids = {employee.id for employee in active_employees}
    required_type_ids = {certificate_type.id for certificate_type in required_types}
    covered_pairs = {
        (employee_id, certificate_type_id)
        for employee_id, certificate_type_id in db.execute(
            select(EmployeeCertificate.employee_id, EmployeeCertificate.certificate_type_id).where(
                EmployeeCertificate.employee_id.in_(active_employee_ids),
                EmployeeCertificate.certificate_type_id.in_(required_type_ids),
                EmployeeCertificate.status.in_(ACTIVE_COVERAGE_STATUSES),
            )
        )
    }

    items: list[DashboardMissingRequiredItem] = []
    for employee in active_employees:
        for certificate_type in required_types:
            if (employee.id, certificate_type.id) in covered_pairs:
                continue
            items.append(
                DashboardMissingRequiredItem(
                    employee_id=employee.id,
                    employee_no=employee.employee_no,
                    employee_name=employee.name,
                    department=employee.department,
                    certificate_type_id=certificate_type.id,
                    certificate_type_code=certificate_type.code,
                    certificate_type_name=certificate_type.name,
                    target_path="/employees?"
                    + urlencode(
                        {
                            "employment_status": EmploymentStatus.ACTIVE.value,
                            "missing_certificate_type_id": str(certificate_type.id),
                            "employee_no": employee.employee_no,
                        }
                    ),
                )
            )
            if limit is not None and len(items) >= limit:
                return items
    return items


def _count_missing_required_certificates(db: Session) -> int:
    return len(_missing_required_certificate_items(db))


def _risk_row(risk_id: str, count: int) -> DashboardRiskRow:
    definition = RISK_ROW_DEFINITIONS.get(risk_id)
    if not definition:
        raise HTTPException(status_code=404, detail="Dashboard risk item not found")
    metric, status_text, target_path = definition
    return DashboardRiskRow(id=risk_id, metric=metric, count=count, status=status_text, target_path=target_path)


def _audit_logs_for_resource_ids(db: Session, resource_ids: Iterable[UUID | str | None]) -> list[AuditLog]:
    resource_id_texts = {str(resource_id) for resource_id in resource_ids if resource_id}
    if not resource_id_texts:
        return []
    return list(
        db.scalars(
            select(AuditLog)
            .where(AuditLog.resource_id.in_(resource_id_texts))
            .order_by(AuditLog.created_at.desc())
            .limit(100)
        ).all()
    )


def _documents_by_ids(db: Session, document_ids: Iterable[UUID | None]) -> list[CertificateDocument]:
    ids = {document_id for document_id in document_ids if document_id}
    if not ids:
        return []
    return list(
        db.scalars(
            select(CertificateDocument)
            .where(CertificateDocument.id.in_(ids))
            .order_by(CertificateDocument.created_at.desc())
        ).all()
    )


def _certificates_by_ids(db: Session, certificate_ids: Iterable[UUID | None]) -> list[EmployeeCertificate]:
    ids = {certificate_id for certificate_id in certificate_ids if certificate_id}
    if not ids:
        return []
    return list(
        db.scalars(
            select(EmployeeCertificate)
            .where(EmployeeCertificate.id.in_(ids))
            .order_by(EmployeeCertificate.created_at.desc())
        ).all()
    )


def _dashboard_risk_trace_payload(
    *,
    risk: DashboardRiskRow,
    certificates: list[EmployeeCertificate] | None = None,
    documents: list[CertificateDocument] | None = None,
    review_tasks: list[ReviewTask] | None = None,
    reminder_tasks: list[ReminderTask] | None = None,
    audit_logs: list[AuditLog] | None = None,
    missing_required_items: list[DashboardMissingRequiredItem] | None = None,
) -> DashboardRiskTraceRead:
    return DashboardRiskTraceRead(
        risk=risk,
        certificates=[EmployeeCertificateRead.model_validate(certificate) for certificate in certificates or []],
        documents=[CertificateDocumentRead.model_validate(document) for document in documents or []],
        review_tasks=[ReviewTaskRead.model_validate(task) for task in review_tasks or []],
        reminder_tasks=[ReminderTaskRead.model_validate(task) for task in reminder_tasks or []],
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
            for log in audit_logs or []
        ],
        missing_required_items=missing_required_items or [],
    )


@router.get("/summary", response_model=DashboardSummaryRead)
def get_dashboard_summary(db: Session = Depends(get_db)) -> DashboardSummaryRead:
    employee_count = _count(db, select(func.count()).select_from(Employee))
    covered_employee_count = _count(
        db,
        select(func.count(func.distinct(EmployeeCertificate.employee_id))).where(
            EmployeeCertificate.status.in_(ACTIVE_COVERAGE_STATUSES)
        ),
    )

    uploaded_count = _count_documents(db, DocumentStatus.UPLOADED)
    parsing_count = _count_documents(db, DocumentStatus.PARSING)
    failed_document_count = _count_documents(db, DocumentStatus.FAILED)
    expiring_count = _count_certificates(db, CertificateStatus.EXPIRING)
    expired_count = _count_certificates(db, CertificateStatus.EXPIRED)
    pending_review_count = _count_reviews(db, *PENDING_REVIEW_STATUSES)
    second_reminder_count = _count_reminders(db, *SECOND_REMINDER_STATUSES)
    open_reminder_count = _count_reminders(db, *OPEN_REMINDER_STATUSES)
    archived_count = _count_certificates(db, *ACTIVE_COVERAGE_STATUSES)
    missing_required_count = _count_missing_required_certificates(db)

    certificate_status_counts = [
        (status, int(count))
        for status, count in db.execute(
            select(EmployeeCertificate.status, func.count())
            .group_by(EmployeeCertificate.status)
            .order_by(EmployeeCertificate.status)
        )
    ]

    return build_dashboard_summary(
        employee_count=employee_count,
        covered_employee_count=covered_employee_count,
        uploaded_count=uploaded_count,
        parsing_count=parsing_count,
        failed_document_count=failed_document_count,
        expiring_count=expiring_count,
        expired_count=expired_count,
        pending_review_count=pending_review_count,
        second_reminder_count=second_reminder_count,
        open_reminder_count=open_reminder_count,
        archived_count=archived_count,
        missing_required_count=missing_required_count,
        certificate_status_counts=certificate_status_counts,
    )


def build_dashboard_summary(
    *,
    employee_count: int,
    covered_employee_count: int,
    uploaded_count: int,
    parsing_count: int,
    failed_document_count: int,
    expiring_count: int,
    expired_count: int,
    pending_review_count: int,
    second_reminder_count: int,
    open_reminder_count: int,
    archived_count: int,
    certificate_status_counts: Iterable[tuple[CertificateStatus, int]],
    missing_required_count: int = 0,
) -> DashboardSummaryRead:
    coverage = round((covered_employee_count / employee_count) * 100, 1) if employee_count else 0
    certificate_status_rows = [
        DashboardChartRow(
            category=CERTIFICATE_STATUS_LABELS[status],
            count=count,
            target_path=f"/certificates?status={status.value}",
        )
        for status, count in certificate_status_counts
        if count
    ]
    workload_rows = [
        DashboardChartRow(category="即将到期", count=expiring_count, target_path="/certificates?status=EXPIRING"),
        DashboardChartRow(category="已过期", count=expired_count, target_path="/certificates?status=EXPIRED"),
        DashboardChartRow(category="识别失败", count=failed_document_count, target_path="/documents?status=FAILED"),
        DashboardChartRow(category="待复核", count=pending_review_count, target_path="/review-queue"),
        DashboardChartRow(
            category="升级提醒",
            count=second_reminder_count,
            target_path="/reminders?status=SECOND_SENT&status=ESCALATED",
        ),
        DashboardChartRow(category="缺失必备", count=missing_required_count, target_path="/reports"),
    ]

    pipeline_steps = [
        DashboardPipelineStep(
            title="上传原件",
            description=f"{uploaded_count} 件待识别",
            count=uploaded_count,
            target_path="/documents?status=UPLOADED",
        ),
        DashboardPipelineStep(
            title="AI 识别",
            description=f"{parsing_count} 件识别中",
            count=parsing_count,
            target_path="/documents?status=PARSING",
        ),
        DashboardPipelineStep(
            title="人工复核",
            description=f"{pending_review_count} 件待复核",
            count=pending_review_count,
            target_path="/review-queue",
        ),
        DashboardPipelineStep(
            title="正式入库",
            description=f"{archived_count} 件已入库",
            count=archived_count,
            target_path="/certificates?status_group=current",
        ),
        DashboardPipelineStep(
            title="到期提醒",
            description=f"{open_reminder_count} 件提醒中",
            count=open_reminder_count,
            target_path="/reminders?status=open",
        ),
    ]

    risk_rows = [
        _risk_row("expired-certificates", expired_count),
        _risk_row("failed-documents", failed_document_count),
        _risk_row("pending-reviews", pending_review_count),
        _risk_row("second-reminders", second_reminder_count),
        _risk_row("missing-required-certificates", missing_required_count),
    ]

    return DashboardSummaryRead(
        expiring_count=expiring_count,
        expired_count=expired_count,
        pending_review_count=pending_review_count,
        coverage=coverage,
        certificate_status_rows=certificate_status_rows,
        workload_rows=[row for row in workload_rows if row.count > 0],
        pipeline_steps=pipeline_steps,
        risk_rows=[row for row in risk_rows if row.count > 0],
    )


@router.get("/risk-items/{risk_id}/trace", response_model=DashboardRiskTraceRead)
def get_dashboard_risk_trace(
    risk_id: str,
    db: Session = Depends(get_db),
    limit: int = Query(default=20, ge=1, le=100),
) -> DashboardRiskTraceRead:
    if risk_id == "expired-certificates":
        count = _count_certificates(db, CertificateStatus.EXPIRED)
        certificates = list(
            db.scalars(
                select(EmployeeCertificate)
                .where(EmployeeCertificate.status == CertificateStatus.EXPIRED)
                .order_by(EmployeeCertificate.updated_at.desc())
                .limit(limit)
            ).all()
        )
        documents = _documents_by_ids(db, [certificate.source_document_id for certificate in certificates])
        reminder_tasks = (
            list(
                db.scalars(
                    select(ReminderTask)
                    .where(ReminderTask.employee_certificate_id.in_([certificate.id for certificate in certificates]))
                    .order_by(ReminderTask.created_at.desc())
                    .limit(limit)
                ).all()
            )
            if certificates
            else []
        )
        audit_logs = _audit_logs_for_resource_ids(
            db,
            [
                *[certificate.id for certificate in certificates],
                *[certificate.employee_id for certificate in certificates],
                *[certificate.certificate_type_id for certificate in certificates],
                *[certificate.source_document_id for certificate in certificates],
                *[task.id for task in reminder_tasks],
            ],
        )
        return _dashboard_risk_trace_payload(
            risk=_risk_row(risk_id, count),
            certificates=certificates,
            documents=documents,
            reminder_tasks=reminder_tasks,
            audit_logs=audit_logs,
        )

    if risk_id == "failed-documents":
        count = _count_documents(db, DocumentStatus.FAILED)
        documents = list(
            db.scalars(
                select(CertificateDocument)
                .where(CertificateDocument.status == DocumentStatus.FAILED)
                .order_by(CertificateDocument.updated_at.desc())
                .limit(limit)
            ).all()
        )
        review_tasks = (
            list(
                db.scalars(
                    select(ReviewTask)
                    .options(selectinload(ReviewTask.document), selectinload(ReviewTask.ai_result))
                    .where(ReviewTask.document_id.in_([document.id for document in documents]))
                    .order_by(ReviewTask.created_at.desc())
                    .limit(limit)
                ).all()
            )
            if documents
            else []
        )
        audit_logs = _audit_logs_for_resource_ids(
            db,
            [
                *[document.id for document in documents],
                *[task.id for task in review_tasks],
                *[task.ai_result_id for task in review_tasks],
            ],
        )
        return _dashboard_risk_trace_payload(
            risk=_risk_row(risk_id, count),
            documents=documents,
            review_tasks=review_tasks,
            audit_logs=audit_logs,
        )

    if risk_id == "missing-required-certificates":
        missing_items = _missing_required_certificate_items(db, limit=limit)
        return _dashboard_risk_trace_payload(
            risk=_risk_row(risk_id, _count_missing_required_certificates(db)),
            missing_required_items=missing_items,
        )

    if risk_id == "pending-reviews":
        count = _count_reviews(db, *PENDING_REVIEW_STATUSES)
        review_tasks = list(
            db.scalars(
                select(ReviewTask)
                .options(selectinload(ReviewTask.document), selectinload(ReviewTask.ai_result))
                .where(ReviewTask.status.in_(PENDING_REVIEW_STATUSES))
                .order_by(ReviewTask.updated_at.desc())
                .limit(limit)
            ).all()
        )
        documents = _documents_by_ids(db, [task.document_id for task in review_tasks])
        audit_logs = _audit_logs_for_resource_ids(
            db,
            [
                *[task.id for task in review_tasks],
                *[task.document_id for task in review_tasks],
                *[task.ai_result_id for task in review_tasks],
            ],
        )
        return _dashboard_risk_trace_payload(
            risk=_risk_row(risk_id, count),
            documents=documents,
            review_tasks=review_tasks,
            audit_logs=audit_logs,
        )

    if risk_id == "second-reminders":
        count = _count_reminders(db, *SECOND_REMINDER_STATUSES)
        reminder_tasks = list(
            db.scalars(
                select(ReminderTask)
                .where(ReminderTask.status.in_(SECOND_REMINDER_STATUSES))
                .order_by(ReminderTask.updated_at.desc())
                .limit(limit)
            ).all()
        )
        certificates = _certificates_by_ids(db, [task.employee_certificate_id for task in reminder_tasks])
        documents = _documents_by_ids(db, [certificate.source_document_id for certificate in certificates])
        audit_logs = _audit_logs_for_resource_ids(
            db,
            [
                *[task.id for task in reminder_tasks],
                *[task.employee_certificate_id for task in reminder_tasks],
                *[certificate.source_document_id for certificate in certificates],
            ],
        )
        return _dashboard_risk_trace_payload(
            risk=_risk_row(risk_id, count),
            certificates=certificates,
            documents=documents,
            reminder_tasks=reminder_tasks,
            audit_logs=audit_logs,
        )

    raise HTTPException(status_code=404, detail="Dashboard risk item not found")
