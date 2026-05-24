from __future__ import annotations

import uuid
from contextlib import nullcontext
from datetime import UTC, datetime
from typing import Any

from app.domain.enums import CertificateStatus
from app.models import EmployeeCertificate
from app.services.certificates import replace_active_certificates


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
