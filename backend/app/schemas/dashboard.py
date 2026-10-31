from __future__ import annotations

from pydantic import BaseModel

from app.schemas.certificates import EmployeeCertificateRead, TraceAuditLogRead
from app.schemas.documents import CertificateDocumentRead, ReviewTaskRead
from app.schemas.reminders import ReminderTaskRead


class DashboardRiskRow(BaseModel):
    id: str
    metric: str
    count: int
    status: str
    target_path: str


class DashboardChartRow(BaseModel):
    category: str
    count: int
    target_path: str


class DashboardPipelineStep(BaseModel):
    title: str
    description: str
    count: int
    target_path: str


class DashboardSummaryRead(BaseModel):
    expiring_count: int
    expired_count: int
    pending_review_count: int
    coverage: float
    certificate_status_rows: list[DashboardChartRow]
    workload_rows: list[DashboardChartRow]
    pipeline_steps: list[DashboardPipelineStep]
    risk_rows: list[DashboardRiskRow]


class DashboardRiskTraceRead(BaseModel):
    risk: DashboardRiskRow
    certificates: list[EmployeeCertificateRead]
    documents: list[CertificateDocumentRead]
    review_tasks: list[ReviewTaskRead]
    reminder_tasks: list[ReminderTaskRead]
    audit_logs: list[TraceAuditLogRead]
