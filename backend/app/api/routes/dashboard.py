from __future__ import annotations

from collections.abc import Iterable

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.domain.enums import CertificateStatus, DocumentStatus, ReminderTaskStatus, ReviewStatus
from app.models import CertificateDocument, Employee, EmployeeCertificate, ReminderTask, ReviewTask
from app.schemas.dashboard import (
    DashboardChartRow,
    DashboardPipelineStep,
    DashboardRiskRow,
    DashboardSummaryRead,
)

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
            target_path="/certificates?status=ACTIVE",
        ),
        DashboardPipelineStep(
            title="到期提醒",
            description=f"{open_reminder_count} 件提醒中",
            count=open_reminder_count,
            target_path="/reminders?status=open",
        ),
    ]

    risk_rows = [
        DashboardRiskRow(
            id="expired-certificates",
            metric="已过期证书",
            count=expired_count,
            status="需跟进",
            target_path="/certificates?status=EXPIRED",
        ),
        DashboardRiskRow(
            id="failed-documents",
            metric="识别失败文件",
            count=failed_document_count,
            status="需跟进",
            target_path="/documents?status=FAILED",
        ),
        DashboardRiskRow(
            id="pending-reviews",
            metric="待复核识别",
            count=pending_review_count,
            status="处理中",
            target_path="/review-queue",
        ),
        DashboardRiskRow(
            id="second-reminders",
            metric="二次或升级提醒",
            count=second_reminder_count,
            status="升级前",
            target_path="/reminders?status=SECOND_SENT&status=ESCALATED",
        ),
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
