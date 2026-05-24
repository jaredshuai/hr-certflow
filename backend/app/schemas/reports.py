from __future__ import annotations

from pydantic import BaseModel


class ReportChartRow(BaseModel):
    category: str
    count: int
    target_path: str


class CertificateCoverageDepartmentRow(BaseModel):
    department: str
    employee_count: int
    covered_employee_count: int
    coverage: float
    target_path: str


class CertificateTypeRiskRow(BaseModel):
    certificate_type_id: str
    certificate_type_name: str
    active_count: int
    expiring_count: int
    expired_count: int
    missing_employee_count: int
    risk_count: int
    target_path: str


class CertificateCoverageReportRead(BaseModel):
    employee_count: int
    covered_employee_count: int
    coverage: float
    department_rows: list[CertificateCoverageDepartmentRow]
    certificate_type_risk_rows: list[CertificateTypeRiskRow]
    expiry_month_rows: list[ReportChartRow]
