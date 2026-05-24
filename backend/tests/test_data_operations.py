from __future__ import annotations

import uuid
from datetime import UTC, date, datetime

from app.api.routes.certificate_types import build_certificate_types_csv, parse_certificate_type_import_csv
from app.api.routes.certificates import build_employee_certificates_csv
from app.api.routes.documents import build_certificate_documents_csv
from app.api.routes.employees import build_employees_csv, parse_employee_import_csv
from app.domain.enums import CertificateStatus, DocumentStatus, EmploymentStatus
from app.models import CertificateDocument, CertificateType, Employee, EmployeeCertificate


def test_build_employees_csv_is_excel_friendly_and_localized() -> None:
    employee = Employee(
        employee_no="E001",
        name="张三",
        department="工程部",
        position="安全员",
        employment_status=EmploymentStatus.ACTIVE,
        phone="13800000000",
        email="zhangsan@example.test",
    )

    payload = build_employees_csv([employee])

    assert payload.startswith("\ufeff")
    assert "工号,姓名,部门,岗位,在职状态,手机,邮箱" in payload
    assert "E001,张三,工程部,安全员,ACTIVE,13800000000,zhangsan@example.test" in payload


def test_build_employee_certificates_csv_uses_display_names_and_dates() -> None:
    employee_id = uuid.uuid4()
    certificate_type_id = uuid.uuid4()
    confirmed_at = datetime(2026, 5, 24, 9, 30, tzinfo=UTC)
    certificate = EmployeeCertificate(
        employee_id=employee_id,
        certificate_type_id=certificate_type_id,
        holder_name="李四",
        certificate_no="CERT-001",
        issuing_authority="住建局",
        issue_date=date(2025, 1, 1),
        valid_from=date(2025, 1, 1),
        valid_to=date(2026, 12, 31),
        status=CertificateStatus.ACTIVE,
        confirmed_by="HR",
        confirmed_at=confirmed_at,
    )

    payload = build_employee_certificates_csv(
        [certificate],
        employee_names={employee_id: "李四（E002）"},
        certificate_type_names={certificate_type_id: "安全员证"},
    )

    assert payload.startswith("\ufeff")
    assert "员工,证书类型,持证人,证书编号,发证机构,发证日期,有效开始,到期日期,状态,确认人,确认时间" in payload
    assert "李四（E002）,安全员证,李四,CERT-001,住建局,2025-01-01,2025-01-01,2026-12-31,ACTIVE,HR" in payload
    assert confirmed_at.isoformat() in payload


def test_build_certificate_documents_csv_exports_trace_fields() -> None:
    document = CertificateDocument(
        status=DocumentStatus.FAILED,
        storage_bucket="bucket",
        storage_key="documents/demo.pdf",
        original_filename="demo.pdf",
        content_type="application/pdf",
        file_size=128,
        sha256="a" * 64,
        failure_reason="RuntimeError: dify unavailable",
        created_at=datetime(2026, 5, 25, 10, 0, tzinfo=UTC),
        updated_at=datetime(2026, 5, 25, 10, 1, tzinfo=UTC),
    )

    payload = build_certificate_documents_csv([document])

    assert payload.startswith("\ufeff")
    assert "文件名,状态,文件类型,文件大小,SHA256,存储 Key,失败原因,创建时间,更新时间" in payload
    assert "demo.pdf,FAILED,application/pdf,128" in payload
    assert "documents/demo.pdf,RuntimeError: dify unavailable" in payload


def test_parse_employee_import_csv_accepts_export_headers_and_status_labels() -> None:
    rows, errors = parse_employee_import_csv(
        "工号,姓名,部门,岗位,在职状态,手机,邮箱\n"
        "E003,王五,工程部,电工,在职,13900000000,wangwu@hr-certflow.cn\n"
    )

    assert errors == []
    assert len(rows) == 1
    row_number, payload = rows[0]
    assert row_number == 2
    assert payload.employee_no == "E003"
    assert payload.name == "王五"
    assert payload.department == "工程部"
    assert payload.position == "电工"
    assert payload.employment_status == EmploymentStatus.ACTIVE


def test_parse_employee_import_csv_collects_row_errors_without_dropping_valid_rows() -> None:
    rows, errors = parse_employee_import_csv(
        "employee_no,name,employment_status,email\n"
        "E004,赵六,LEFT,zhaoliu@hr-certflow.cn\n"
        ",缺工号,ACTIVE,missing-no@hr-certflow.cn\n"
        "E005,错误状态,UNKNOWN,bad-status@hr-certflow.cn\n"
    )

    assert len(rows) == 1
    assert rows[0][1].employee_no == "E004"
    assert rows[0][1].employment_status == EmploymentStatus.LEFT
    assert [(error.row_number, error.employee_no) for error in errors] == [(3, None), (4, "E005")]


def test_build_certificate_types_csv_uses_importable_headers() -> None:
    certificate_type = CertificateType(
        code="SAFETY",
        name="安全员证",
        issuing_authority="住建局",
        default_validity_months=36,
        force_manual_review=True,
        description="施工现场安全管理",
    )

    payload = build_certificate_types_csv([certificate_type])

    assert payload.startswith("\ufeff")
    assert "编码,证书类型,发证机构,默认有效期(月),强制复核,说明" in payload
    assert "SAFETY,安全员证,住建局,36,是,施工现场安全管理" in payload


def test_parse_certificate_type_import_csv_accepts_chinese_headers() -> None:
    rows, errors = parse_certificate_type_import_csv(
        "编码,证书类型,发证机构,默认有效期(月),强制复核,说明\n"
        "ELEC,电工证,应急管理局,72,否,特种作业证\n"
    )

    assert errors == []
    assert len(rows) == 1
    row_number, payload = rows[0]
    assert row_number == 2
    assert payload.code == "ELEC"
    assert payload.name == "电工证"
    assert payload.issuing_authority == "应急管理局"
    assert payload.default_validity_months == 72
    assert payload.force_manual_review is False


def test_parse_certificate_type_import_csv_collects_errors() -> None:
    rows, errors = parse_certificate_type_import_csv(
        "code,name,default_validity_months,force_manual_review\n"
        "WELD,焊工证,36,true\n"
        ",缺编码,36,true\n"
        "BAD,错误有效期,0,maybe\n"
    )

    assert len(rows) == 1
    assert rows[0][1].code == "WELD"
    assert rows[0][1].force_manual_review is True
    assert [(error.row_number, error.code) for error in errors] == [(3, None), (4, "BAD")]
