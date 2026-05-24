from __future__ import annotations

import csv
from calendar import monthrange
from collections import defaultdict
from datetime import date
from io import StringIO
from urllib.parse import urlencode

from fastapi import APIRouter, Depends
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.domain.enums import CertificateStatus, EmploymentStatus
from app.models import CertificateType, Employee, EmployeeCertificate
from app.schemas.reports import (
    CertificateCoverageDepartmentRow,
    CertificateCoverageReportRead,
    CertificateTypeRiskRow,
    ReportChartRow,
)

router = APIRouter()

ACTIVE_COVERAGE_STATUSES = {CertificateStatus.ACTIVE, CertificateStatus.EXPIRING}
RISK_STATUSES = {CertificateStatus.EXPIRING, CertificateStatus.EXPIRED}


def _coverage_ratio(covered_count: int, total_count: int) -> float:
    return round((covered_count / total_count) * 100, 1) if total_count else 0


def _month_range(month: str) -> tuple[str, str]:
    year, month_value = (int(part) for part in month.split("-"))
    start = date(year, month_value, 1)
    end = date(year, month_value, monthrange(year, month_value)[1])
    return start.isoformat(), end.isoformat()


def build_certificate_coverage_report(
    *,
    employees: list[Employee],
    certificate_types: list[CertificateType],
    certificates: list[EmployeeCertificate],
) -> CertificateCoverageReportRead:
    active_employees = [employee for employee in employees if employee.employment_status == EmploymentStatus.ACTIVE]
    active_employee_ids = {employee.id for employee in active_employees}
    covered_employee_ids = {
        certificate.employee_id
        for certificate in certificates
        if certificate.status in ACTIVE_COVERAGE_STATUSES and certificate.employee_id in active_employee_ids
    }

    department_employee_ids: dict[str, set] = defaultdict(set)
    department_covered_ids: dict[str, set] = defaultdict(set)
    for employee in active_employees:
        department = employee.department or "未设置部门"
        department_employee_ids[department].add(employee.id)
        if employee.id in covered_employee_ids:
            department_covered_ids[department].add(employee.id)

    department_rows = [
        CertificateCoverageDepartmentRow(
            department=department,
            employee_count=len(employee_ids),
            covered_employee_count=len(department_covered_ids[department]),
            coverage=_coverage_ratio(len(department_covered_ids[department]), len(employee_ids)),
            target_path="/employees?"
            + urlencode({"department": department, "employment_status": EmploymentStatus.ACTIVE.value}),
        )
        for department, employee_ids in sorted(department_employee_ids.items())
    ]

    certificates_by_type: dict[str, list[EmployeeCertificate]] = defaultdict(list)
    for certificate in certificates:
        certificates_by_type[str(certificate.certificate_type_id)].append(certificate)

    certificate_type_risk_rows: list[CertificateTypeRiskRow] = []
    for certificate_type in sorted(certificate_types, key=lambda item: item.name):
        type_certificates = certificates_by_type[str(certificate_type.id)]
        active_count = sum(1 for item in type_certificates if item.status in ACTIVE_COVERAGE_STATUSES)
        expiring_count = sum(1 for item in type_certificates if item.status == CertificateStatus.EXPIRING)
        expired_count = sum(1 for item in type_certificates if item.status == CertificateStatus.EXPIRED)
        covered_for_type = {
            item.employee_id
            for item in type_certificates
            if item.status in ACTIVE_COVERAGE_STATUSES and item.employee_id in active_employee_ids
        }
        missing_employee_count = max(len(active_employee_ids - covered_for_type), 0)
        risk_count = expiring_count + expired_count + missing_employee_count
        certificate_type_risk_rows.append(
            CertificateTypeRiskRow(
                certificate_type_id=str(certificate_type.id),
                certificate_type_name=certificate_type.name,
                active_count=active_count,
                expiring_count=expiring_count,
                expired_count=expired_count,
                missing_employee_count=missing_employee_count,
                risk_count=risk_count,
                target_path=f"/certificates?certificate_type_id={certificate_type.id}",
            )
        )

    expiry_month_counts: dict[str, int] = defaultdict(int)
    for certificate in certificates:
        if certificate.status in RISK_STATUSES and isinstance(certificate.valid_to, date):
            expiry_month_counts[certificate.valid_to.strftime("%Y-%m")] += 1

    return CertificateCoverageReportRead(
        employee_count=len(active_employee_ids),
        covered_employee_count=len(covered_employee_ids),
        coverage=_coverage_ratio(len(covered_employee_ids), len(active_employee_ids)),
        department_rows=department_rows,
        certificate_type_risk_rows=certificate_type_risk_rows,
        expiry_month_rows=[
            ReportChartRow(
                category=month,
                count=count,
                target_path="/certificates?"
                + urlencode(
                    {
                        "status_group": "risk",
                        "valid_to_from": _month_range(month)[0],
                        "valid_to_to": _month_range(month)[1],
                    }
                ),
            )
            for month, count in sorted(expiry_month_counts.items())
        ],
    )


def build_certificate_coverage_report_csv(report: CertificateCoverageReportRead) -> str:
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(["报表", "证书覆盖与风险"])
    writer.writerow(["在职员工数", report.employee_count])
    writer.writerow(["已覆盖员工数", report.covered_employee_count])
    writer.writerow(["覆盖率", report.coverage])
    writer.writerow([])
    writer.writerow(["部门", "员工数", "已覆盖员工数", "覆盖率"])
    for row in report.department_rows:
        writer.writerow([row.department, row.employee_count, row.covered_employee_count, row.coverage])
    writer.writerow([])
    writer.writerow(["证书类型", "有效数", "即将到期", "已过期", "缺失员工数", "风险合计"])
    for row in report.certificate_type_risk_rows:
        writer.writerow([
            row.certificate_type_name,
            row.active_count,
            row.expiring_count,
            row.expired_count,
            row.missing_employee_count,
            row.risk_count,
        ])
    writer.writerow([])
    writer.writerow(["到期月份", "风险证书数"])
    for row in report.expiry_month_rows:
        writer.writerow([row.category, row.count])
    return "\ufeff" + output.getvalue()


def _load_certificate_coverage_report(db: Session) -> CertificateCoverageReportRead:
    employees = list(db.scalars(select(Employee)).all())
    certificate_types = list(db.scalars(select(CertificateType)).all())
    certificates = list(db.scalars(select(EmployeeCertificate)).all())
    return build_certificate_coverage_report(
        employees=employees,
        certificate_types=certificate_types,
        certificates=certificates,
    )


@router.get("/certificate-coverage", response_model=CertificateCoverageReportRead)
def get_certificate_coverage_report(db: Session = Depends(get_db)) -> CertificateCoverageReportRead:
    return _load_certificate_coverage_report(db)


@router.get("/certificate-coverage/export.csv")
def export_certificate_coverage_report_csv(db: Session = Depends(get_db)) -> Response:
    return Response(
        content=build_certificate_coverage_report_csv(_load_certificate_coverage_report(db)),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="certificate-coverage-report.csv"'},
    )
