from __future__ import annotations

from pydantic import BaseModel


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
