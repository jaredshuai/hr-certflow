from __future__ import annotations

import uuid
from contextlib import nullcontext
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi import HTTPException

from app.domain.enums import CertificateStatus, EmploymentStatus
from app.models import CertificateType, Employee, EmployeeCertificate
from app.services.certificates import replace_active_certificates, validate_certificate_business_rules


class FakeScalarResult:
    def __init__(self, items: list[Any]) -> None:
        self.items = items

    def all(self) -> list[Any]:
        return self.items


class FakeCertificateDb:
    def __init__(self, old_certificate: EmployeeCertificate) -> None:
        self.old_certificate = old_certificate
        self.scalars_calls = 0
        self.flush_count = 0
        self.no_autoflush = nullcontext()

    def scalars(self, statement: Any) -> FakeScalarResult:
        self.scalars_calls += 1
        if self.scalars_calls == 1:
            return FakeScalarResult([self.old_certificate])
        return FakeScalarResult([])

    def flush(self) -> None:
        self.flush_count += 1


class FakeBusinessRuleDb:
    def __init__(self, employee: Employee, certificate_type: CertificateType) -> None:
        self.employee = employee
        self.certificate_type = certificate_type

    def get(self, model: type, item_id: Any) -> Any:
        if model is Employee and item_id == self.employee.id:
            return self.employee
        if model is CertificateType and item_id == self.certificate_type.id:
            return self.certificate_type
        return None

    def scalar(self, statement: Any) -> Any:
        return None


def test_employee_certificate_guardrail_indexes_are_declared() -> None:
    indexes = {index.name: index for index in EmployeeCertificate.__table__.indexes}

    current_index = indexes["uq_employee_certificate_one_current_per_type"]
    duplicate_number_index = indexes["uq_employee_certificate_no_open_per_type"]

    assert current_index.unique is True
    assert [column.name for column in current_index.columns] == ["employee_id", "certificate_type_id"]
    assert str(current_index.dialect_options["postgresql"]["where"]) == "status IN ('ACTIVE', 'EXPIRING')"
    assert duplicate_number_index.unique is True
    assert [column.name for column in duplicate_number_index.columns] == [
        "employee_id",
        "certificate_type_id",
        "certificate_no",
    ]
    assert (
        str(duplicate_number_index.dialect_options["postgresql"]["where"])
        == "certificate_no IS NOT NULL AND status IN ('DRAFT', 'PENDING_REVIEW', 'ACTIVE', 'EXPIRING')"
    )


def test_replace_active_certificates_uses_target_status_for_draft_replacement() -> None:
    employee_id = uuid.uuid4()
    certificate_type_id = uuid.uuid4()
    old_certificate = EmployeeCertificate(
        id=uuid.uuid4(),
        employee_id=employee_id,
        certificate_type_id=certificate_type_id,
        holder_name="张三",
        status=CertificateStatus.ACTIVE,
    )
    new_certificate = EmployeeCertificate(
        id=uuid.uuid4(),
        employee_id=employee_id,
        certificate_type_id=certificate_type_id,
        holder_name="张三",
        status=CertificateStatus.DRAFT,
    )
    db = FakeCertificateDb(old_certificate)

    replaced = replace_active_certificates(
        db,
        new_certificate,
        now=datetime(2026, 5, 25, 10, 0, tzinfo=UTC),
        target_status=CertificateStatus.ACTIVE,
    )

    assert replaced == [old_certificate]
    assert old_certificate.status == CertificateStatus.REPLACED
    assert old_certificate.replaced_by_id == new_certificate.id
    assert db.flush_count == 1


def test_validate_certificate_business_rules_rejects_left_employee_for_current_certificate() -> None:
    employee = Employee(
        id=uuid.uuid4(),
        employee_no="E009",
        name="赵六",
        employment_status=EmploymentStatus.LEFT,
    )
    certificate_type = CertificateType(id=uuid.uuid4(), code="SAFETY", name="安全员证")
    db = FakeBusinessRuleDb(employee, certificate_type)

    with pytest.raises(HTTPException) as exc_info:
        validate_certificate_business_rules(
            db,
            employee_id=employee.id,
            certificate_type_id=certificate_type.id,
            holder_name=employee.name,
            certificate_no="CERT-LEFT",
            require_active_employee=True,
        )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail == "Cannot create current certificate for employee who has left"
