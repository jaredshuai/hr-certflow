from __future__ import annotations

import uuid
from datetime import date

from app.api.routes.reports import build_certificate_coverage_report, build_certificate_coverage_report_csv
from app.domain.enums import CertificateStatus, EmploymentStatus
from app.models import CertificateType, Employee, EmployeeCertificate


def test_build_certificate_coverage_report_groups_department_type_and_expiry_risk() -> None:
    employee_a = Employee(
        id=uuid.uuid4(),
        employee_no="E001",
        name="张三",
        department="工程部",
        employment_status=EmploymentStatus.ACTIVE,
    )
    employee_b = Employee(
        id=uuid.uuid4(),
        employee_no="E002",
        name="李四",
        department="工程部",
        employment_status=EmploymentStatus.ACTIVE,
    )
    employee_c = Employee(
        id=uuid.uuid4(),
        employee_no="E003",
        name="王五",
        department="生产部",
        employment_status=EmploymentStatus.LEFT,
    )
    safety_type = CertificateType(id=uuid.uuid4(), code="SAFETY", name="安全员证", is_required=True)
    electric_type = CertificateType(id=uuid.uuid4(), code="ELEC", name="电工证", is_required=False)
    forklift_type = CertificateType(id=uuid.uuid4(), code="FORK", name="叉车证", is_required=True)
    certificates = [
        EmployeeCertificate(
            employee_id=employee_a.id,
            certificate_type_id=safety_type.id,
            holder_name="张三",
            status=CertificateStatus.ACTIVE,
            valid_to=date(2027, 1, 31),
        ),
        EmployeeCertificate(
            employee_id=employee_b.id,
            certificate_type_id=safety_type.id,
            holder_name="李四",
            status=CertificateStatus.EXPIRING,
            valid_to=date(2026, 6, 30),
        ),
        EmployeeCertificate(
            employee_id=employee_b.id,
            certificate_type_id=electric_type.id,
            holder_name="李四",
            status=CertificateStatus.EXPIRED,
            valid_to=date(2026, 5, 31),
        ),
    ]

    report = build_certificate_coverage_report(
        employees=[employee_a, employee_b, employee_c],
        certificate_types=[safety_type, electric_type, forklift_type],
        certificates=certificates,
    )

    assert report.employee_count == 2
    assert report.covered_employee_count == 2
    assert report.coverage == 100
    assert [row.model_dump() for row in report.department_rows] == [
        {
            "department": "工程部",
            "employee_count": 2,
            "covered_employee_count": 2,
            "coverage": 100,
            "target_path": "/employees?department=%E5%B7%A5%E7%A8%8B%E9%83%A8&employment_status=ACTIVE",
        }
    ]
    safety_row = next(row for row in report.certificate_type_risk_rows if row.certificate_type_name == "安全员证")
    electric_row = next(row for row in report.certificate_type_risk_rows if row.certificate_type_name == "电工证")
    forklift_row = next(row for row in report.certificate_type_risk_rows if row.certificate_type_name == "叉车证")
    assert safety_row.is_required is True
    assert safety_row.active_count == 2
    assert safety_row.expiring_count == 1
    assert safety_row.missing_employee_count == 0
    assert safety_row.target_path == f"/certificates?certificate_type_id={safety_type.id}&status_group=risk"
    assert safety_row.active_target_path == f"/certificates?certificate_type_id={safety_type.id}&status_group=current"
    assert safety_row.expiring_target_path == f"/certificates?certificate_type_id={safety_type.id}&status=EXPIRING"
    assert safety_row.expired_target_path == f"/certificates?certificate_type_id={safety_type.id}&status=EXPIRED"
    assert (
        safety_row.missing_employee_target_path
        == f"/employees?employment_status=ACTIVE&missing_certificate_type_id={safety_type.id}"
    )
    assert electric_row.is_required is False
    assert electric_row.expired_count == 1
    assert electric_row.missing_employee_count == 0
    assert electric_row.risk_count == 1
    assert electric_row.target_path == f"/certificates?certificate_type_id={electric_type.id}&status_group=risk"
    assert electric_row.expired_target_path == f"/certificates?certificate_type_id={electric_type.id}&status=EXPIRED"
    assert (
        electric_row.missing_employee_target_path
        == f"/employees?employment_status=ACTIVE&missing_certificate_type_id={electric_type.id}"
    )
    assert forklift_row.is_required is True
    assert forklift_row.missing_employee_count == 2
    assert forklift_row.risk_count == 2
    assert (
        forklift_row.missing_employee_target_path
        == f"/employees?employment_status=ACTIVE&missing_certificate_type_id={forklift_type.id}"
    )
    assert [row.model_dump() for row in report.expiry_month_rows] == [
        {
            "category": "2026-05",
            "count": 1,
            "target_path": "/certificates?status_group=risk&valid_to_from=2026-05-01&valid_to_to=2026-05-31",
        },
        {
            "category": "2026-06",
            "count": 1,
            "target_path": "/certificates?status_group=risk&valid_to_from=2026-06-01&valid_to_to=2026-06-30",
        },
    ]


def test_build_certificate_coverage_report_csv_is_excel_friendly() -> None:
    report = build_certificate_coverage_report(employees=[], certificate_types=[], certificates=[])

    payload = build_certificate_coverage_report_csv(report)

    assert payload.startswith("\ufeff")
    assert "报表,证书覆盖与风险" in payload
    assert "部门,员工数,已覆盖员工数,覆盖率" in payload
    assert "证书类型,是否必备,有效数,即将到期,已过期,缺失员工数,风险合计" in payload
