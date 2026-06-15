from __future__ import annotations

import csv
from collections.abc import Iterable
from io import StringIO
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import Response
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.api.deps import RequestContext, audit_context_kwargs, get_request_context
from app.db.session import get_db
from app.domain.enums import CertificateStatus, EmploymentStatus
from app.models import (
    AuditLog,
    CertificateDocument,
    CertificateType,
    Employee,
    EmployeeCertificate,
    ReminderTask,
    ReviewTask,
)
from app.schemas.employees import (
    EmployeeCreate,
    EmployeeImportErrorRead,
    EmployeeImportResultRead,
    EmployeePageRead,
    EmployeeRead,
    EmployeeTraceAuditLogRead,
    EmployeeTraceCertificateRead,
    EmployeeTraceDocumentRead,
    EmployeeTraceRead,
    EmployeeTraceReminderTaskRead,
    EmployeeTraceReviewTaskRead,
    EmployeeUpdate,
)
from app.services.audit import record_audit

router = APIRouter()

_EMPLOYEE_IMPORT_FIELD_ALIASES = {
    "工号": "employee_no",
    "员工编号": "employee_no",
    "employee_no": "employee_no",
    "employee no": "employee_no",
    "姓名": "name",
    "name": "name",
    "部门": "department",
    "department": "department",
    "岗位": "position",
    "职位": "position",
    "position": "position",
    "在职状态": "employment_status",
    "状态": "employment_status",
    "employment_status": "employment_status",
    "employment status": "employment_status",
    "手机": "phone",
    "电话": "phone",
    "phone": "phone",
    "邮箱": "email",
    "email": "email",
}

_EMPLOYMENT_STATUS_ALIASES = {
    "ACTIVE": EmploymentStatus.ACTIVE,
    "在职": EmploymentStatus.ACTIVE,
    "ON_LEAVE": EmploymentStatus.ON_LEAVE,
    "休假": EmploymentStatus.ON_LEAVE,
    "请假": EmploymentStatus.ON_LEAVE,
    "LEFT": EmploymentStatus.LEFT,
    "离职": EmploymentStatus.LEFT,
}


def _clean_cell(value: str | None) -> str | None:
    cleaned = value.strip() if value else ""
    return cleaned or None


def _normalized_import_key(value: str | None) -> str | None:
    if not value:
        return None
    return _EMPLOYEE_IMPORT_FIELD_ALIASES.get(value.strip().lstrip("\ufeff").lower())


def _parse_employment_status(value: str | None) -> EmploymentStatus:
    if not value:
        return EmploymentStatus.ACTIVE
    normalized = value.strip().upper()
    status_value = _EMPLOYMENT_STATUS_ALIASES.get(normalized) or _EMPLOYMENT_STATUS_ALIASES.get(value.strip())
    if not status_value:
        raise ValueError("在职状态必须是 ACTIVE、ON_LEAVE、LEFT 或 在职、休假、离职")
    return status_value


def decode_employee_import_csv(content: bytes) -> str:
    try:
        return content.decode("utf-8-sig")
    except UnicodeDecodeError:
        return content.decode("gb18030")


def parse_employee_import_csv(content: str) -> tuple[list[tuple[int, EmployeeCreate]], list[EmployeeImportErrorRead]]:
    reader = csv.DictReader(StringIO(content))
    if not reader.fieldnames:
        return [], [EmployeeImportErrorRead(row_number=1, message="CSV 缺少表头")]

    rows: list[tuple[int, EmployeeCreate]] = []
    errors: list[EmployeeImportErrorRead] = []
    seen_employee_nos: set[str] = set()
    for row_number, raw_row in enumerate(reader, start=2):
        normalized_row: dict[str, str | None] = {}
        for key, value in raw_row.items():
            normalized_key = _normalized_import_key(key)
            if normalized_key:
                normalized_row[normalized_key] = _clean_cell(value)

        if not any(normalized_row.values()):
            continue

        employee_no = normalized_row.get("employee_no")
        name = normalized_row.get("name")
        if not employee_no or not name:
            errors.append(
                EmployeeImportErrorRead(
                    row_number=row_number,
                    employee_no=employee_no,
                    message="工号和姓名不能为空",
                )
            )
            continue

        if employee_no in seen_employee_nos:
            errors.append(
                EmployeeImportErrorRead(
                    row_number=row_number,
                    employee_no=employee_no,
                    message="同一导入文件内工号重复，请保留一行后重试",
                )
            )
            continue

        try:
            payload = EmployeeCreate(
                employee_no=employee_no,
                name=name,
                department=normalized_row.get("department"),
                position=normalized_row.get("position"),
                employment_status=_parse_employment_status(normalized_row.get("employment_status")),
                phone=normalized_row.get("phone"),
                email=normalized_row.get("email"),
            )
        except ValueError as exc:
            errors.append(
                EmployeeImportErrorRead(row_number=row_number, employee_no=employee_no, message=str(exc))
            )
            continue
        seen_employee_nos.add(employee_no)
        rows.append((row_number, payload))

    return rows, errors


def import_employee_rows(
    db: Session,
    rows: Iterable[tuple[int, EmployeeCreate]],
    *,
    initial_errors: list[EmployeeImportErrorRead] | None = None,
    request_context: RequestContext | None = None,
) -> EmployeeImportResultRead:
    row_list = list(rows)
    employee_nos = {payload.employee_no for _, payload in row_list}
    existing_by_no: dict[str, Employee] = {}
    if employee_nos:
        existing_by_no = {
            employee.employee_no: employee
            for employee in db.scalars(select(Employee).where(Employee.employee_no.in_(employee_nos))).all()
        }

    created = 0
    updated = 0
    for _, payload in row_list:
        employee = existing_by_no.get(payload.employee_no)
        payload_data = payload.model_dump()
        if employee:
            before = EmployeeRead.model_validate(employee).model_dump(mode="json")
            for field, value in payload_data.items():
                if field != "employee_no":
                    setattr(employee, field, value)
            record_audit(
                db,
                action="employee.import.update",
                resource_type="employee",
                resource_id=str(employee.id),
                before=before,
                after=payload.model_dump(mode="json"),
                **audit_context_kwargs(request_context),
            )
            updated += 1
        else:
            employee = Employee(**payload_data)
            db.add(employee)
            db.flush()
            existing_by_no[payload.employee_no] = employee
            record_audit(
                db,
                action="employee.import.create",
                resource_type="employee",
                resource_id=str(employee.id),
                after=payload.model_dump(mode="json"),
                **audit_context_kwargs(request_context),
            )
            created += 1

    db.commit()
    errors = initial_errors or []
    return EmployeeImportResultRead(
        total=len(row_list) + len(errors),
        created=created,
        updated=updated,
        failed=len(errors),
        errors=errors,
    )


def _employee_statement(
    *,
    keyword: str | None = None,
    employee_no: str | None = None,
    name: str | None = None,
    department: str | None = None,
    position: str | None = None,
    employment_status: EmploymentStatus | None = None,
    missing_certificate_type_id: UUID | None = None,
):
    statement = select(Employee)
    if keyword:
        like = f"%{keyword.strip()}%"
        statement = statement.where(
            or_(
                Employee.employee_no.ilike(like),
                Employee.name.ilike(like),
                Employee.department.ilike(like),
                Employee.position.ilike(like),
                Employee.phone.ilike(like),
                Employee.email.ilike(like),
            )
        )
    if employee_no:
        statement = statement.where(Employee.employee_no.ilike(f"%{employee_no.strip()}%"))
    if name:
        statement = statement.where(Employee.name.ilike(f"%{name.strip()}%"))
    if department:
        statement = statement.where(Employee.department.ilike(f"%{department.strip()}%"))
    if position:
        statement = statement.where(Employee.position.ilike(f"%{position.strip()}%"))
    if employment_status:
        statement = statement.where(Employee.employment_status == employment_status)
    if missing_certificate_type_id:
        covered_employee_ids = select(EmployeeCertificate.employee_id).where(
            EmployeeCertificate.certificate_type_id == missing_certificate_type_id,
            EmployeeCertificate.status.in_([CertificateStatus.ACTIVE, CertificateStatus.EXPIRING]),
        )
        statement = statement.where(Employee.id.not_in(covered_employee_ids))
    return statement


def build_employees_csv(rows: Iterable[Employee]) -> str:
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(["工号", "姓名", "部门", "岗位", "在职状态", "手机", "邮箱"])
    for row in rows:
        writer.writerow([
            row.employee_no,
            row.name,
            row.department or "",
            row.position or "",
            row.employment_status.value,
            row.phone or "",
            row.email or "",
        ])
    return "\ufeff" + output.getvalue()


def build_employee_import_template_csv() -> str:
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(["工号", "姓名", "部门", "岗位", "在职状态", "手机", "邮箱"])
    writer.writerow(["E001", "张三", "工程部", "安全员", "在职", "13800000000", "zhangsan@example.com"])
    return "\ufeff" + output.getvalue()


@router.get("", response_model=list[EmployeeRead])
def list_employees(
    db: Session = Depends(get_db),
    limit: int = 100,
    offset: int = 0,
) -> list[Employee]:
    statement = select(Employee).order_by(Employee.created_at.desc()).limit(limit).offset(offset)
    return list(db.scalars(statement).all())


@router.get("/page", response_model=EmployeePageRead)
def page_employees(
    db: Session = Depends(get_db),
    current: int = 1,
    page_size: int = 20,
    keyword: str | None = None,
    employee_no: str | None = None,
    name: str | None = None,
    department: str | None = None,
    position: str | None = None,
    employment_status: EmploymentStatus | None = None,
    missing_certificate_type_id: UUID | None = None,
) -> EmployeePageRead:
    current = max(current, 1)
    page_size = min(max(page_size, 1), 200)
    filtered = _employee_statement(
        keyword=keyword,
        employee_no=employee_no,
        name=name,
        department=department,
        position=position,
        employment_status=employment_status,
        missing_certificate_type_id=missing_certificate_type_id,
    )
    total = int(db.scalar(select(func.count()).select_from(filtered.subquery())) or 0)
    rows = db.scalars(
        filtered.order_by(Employee.created_at.desc()).limit(page_size).offset((current - 1) * page_size)
    ).all()
    return EmployeePageRead(data=[EmployeeRead.model_validate(row) for row in rows], total=total)


@router.get("/export.csv")
def export_employees_csv(
    db: Session = Depends(get_db),
    keyword: str | None = None,
    employee_no: str | None = None,
    name: str | None = None,
    department: str | None = None,
    position: str | None = None,
    employment_status: EmploymentStatus | None = None,
    missing_certificate_type_id: UUID | None = None,
) -> Response:
    rows = db.scalars(
        _employee_statement(
            keyword=keyword,
            employee_no=employee_no,
            name=name,
            department=department,
            position=position,
            employment_status=employment_status,
            missing_certificate_type_id=missing_certificate_type_id,
        ).order_by(Employee.created_at.desc())
    ).all()
    return Response(
        content=build_employees_csv(rows),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="employees.csv"'},
    )


@router.get("/import-template.csv")
def export_employee_import_template_csv() -> Response:
    return Response(
        content=build_employee_import_template_csv(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="employees-import-template.csv"'},
    )


@router.post("/import.csv", response_model=EmployeeImportResultRead)
async def import_employees_csv(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    request_context: RequestContext | None = Depends(get_request_context),
) -> EmployeeImportResultRead:
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="CSV 文件不能为空")

    rows, errors = parse_employee_import_csv(decode_employee_import_csv(content))
    if not rows and errors:
        return EmployeeImportResultRead(total=len(errors), created=0, updated=0, failed=len(errors), errors=errors)
    return import_employee_rows(db, rows, initial_errors=errors, request_context=request_context)


def _load_employee_trace_audit_logs(
    db: Session,
    *,
    employee: Employee,
    certificates: Iterable[EmployeeCertificate],
    documents: Iterable[CertificateDocument],
    review_tasks: Iterable[ReviewTask],
    reminder_tasks: Iterable[ReminderTask],
) -> list[AuditLog]:
    from app.services.audit import load_audit_logs_for_resources

    resource_ids = {str(employee.id)}
    resource_ids.update(str(certificate.id) for certificate in certificates)
    resource_ids.update(str(document.id) for document in documents)
    resource_ids.update(str(task.id) for task in review_tasks)
    resource_ids.update(str(task.id) for task in reminder_tasks)

    return load_audit_logs_for_resources(db, resource_ids)


@router.get("/{employee_id}/trace", response_model=EmployeeTraceRead)
def get_employee_trace(
    employee_id: UUID,
    db: Session = Depends(get_db),
) -> EmployeeTraceRead:
    employee = db.get(Employee, employee_id)
    if not employee:
        raise HTTPException(status_code=404, detail="Employee not found")

    certificates = list(
        db.scalars(
            select(EmployeeCertificate)
            .where(EmployeeCertificate.employee_id == employee.id)
            .order_by(EmployeeCertificate.created_at.desc())
        ).all()
    )
    certificate_ids = [certificate.id for certificate in certificates]
    certificate_type_ids = {certificate.certificate_type_id for certificate in certificates}
    certificate_type_names = (
        {
            certificate_type.id: certificate_type.name
            for certificate_type in db.scalars(
                select(CertificateType).where(CertificateType.id.in_(certificate_type_ids))
            ).all()
        }
        if certificate_type_ids
        else {}
    )

    document_ids = {certificate.source_document_id for certificate in certificates if certificate.source_document_id}
    direct_documents = list(
        db.scalars(select(CertificateDocument).where(CertificateDocument.employee_id == employee.id)).all()
    )
    document_ids.update(document.id for document in direct_documents)
    documents = (
        list(
            db.scalars(
                select(CertificateDocument)
                .where(CertificateDocument.id.in_(document_ids))
                .order_by(CertificateDocument.created_at.desc())
            ).all()
        )
        if document_ids
        else []
    )
    document_ids = {document.id for document in documents}

    review_tasks = (
        list(
            db.scalars(
                select(ReviewTask)
                .where(ReviewTask.document_id.in_(document_ids))
                .order_by(ReviewTask.created_at.desc())
            ).all()
        )
        if document_ids
        else []
    )
    reminder_tasks = (
        list(
            db.scalars(
                select(ReminderTask)
                .where(ReminderTask.employee_certificate_id.in_(certificate_ids))
                .order_by(ReminderTask.created_at.desc())
            ).all()
        )
        if certificate_ids
        else []
    )
    audit_logs = _load_employee_trace_audit_logs(
        db,
        employee=employee,
        certificates=certificates,
        documents=documents,
        review_tasks=review_tasks,
        reminder_tasks=reminder_tasks,
    )

    return EmployeeTraceRead(
        employee=EmployeeRead.model_validate(employee),
        certificates=[
            EmployeeTraceCertificateRead(
                id=certificate.id,
                certificate_type_id=certificate.certificate_type_id,
                certificate_type_name=certificate_type_names.get(certificate.certificate_type_id),
                source_document_id=certificate.source_document_id,
                replaced_by_id=certificate.replaced_by_id,
                certificate_no=certificate.certificate_no,
                holder_name=certificate.holder_name,
                issuing_authority=certificate.issuing_authority,
                valid_to=certificate.valid_to,
                status=certificate.status,
                confirmed_by=certificate.confirmed_by,
                confirmed_at=certificate.confirmed_at,
                created_at=certificate.created_at,
                updated_at=certificate.updated_at,
            )
            for certificate in certificates
        ],
        documents=[
            EmployeeTraceDocumentRead(
                id=document.id,
                status=document.status,
                original_filename=document.original_filename,
                content_type=document.content_type,
                file_size=document.file_size,
                sha256=document.sha256,
                failure_reason=document.failure_reason,
                created_at=document.created_at,
                updated_at=document.updated_at,
            )
            for document in documents
        ],
        review_tasks=[
            EmployeeTraceReviewTaskRead(
                id=task.id,
                document_id=task.document_id,
                ai_result_id=task.ai_result_id,
                status=task.status,
                reviewed_by=task.reviewed_by,
                reviewed_at=task.reviewed_at,
                notes=task.notes,
                created_at=task.created_at,
                updated_at=task.updated_at,
            )
            for task in review_tasks
        ],
        reminder_tasks=[
            EmployeeTraceReminderTaskRead(
                id=task.id,
                employee_certificate_id=task.employee_certificate_id,
                status=task.status,
                trigger_date=task.trigger_date,
                due_date=task.due_date,
                last_event_at=task.last_event_at,
                resolved_at=task.resolved_at,
                closed_reason=task.closed_reason,
            )
            for task in reminder_tasks
        ],
        audit_logs=[
            EmployeeTraceAuditLogRead(
                id=log.id,
                action=log.action,
                resource_type=log.resource_type,
                resource_id=log.resource_id,
                actor_name=log.actor_name,
                request_id=log.request_id,
                ip_address=log.ip_address,
                created_at=log.created_at,
            )
            for log in audit_logs
        ],
    )


@router.post("", response_model=EmployeeRead, status_code=status.HTTP_201_CREATED)
def create_employee(
    payload: EmployeeCreate,
    db: Session = Depends(get_db),
    request_context: RequestContext | None = Depends(get_request_context),
) -> Employee:
    employee = Employee(**payload.model_dump())
    db.add(employee)
    db.flush()
    record_audit(
        db,
        action="employee.create",
        resource_type="employee",
        resource_id=str(employee.id),
        after=payload.model_dump(mode="json"),
        **audit_context_kwargs(request_context),
    )
    db.commit()
    db.refresh(employee)
    return employee


@router.patch("/{employee_id}", response_model=EmployeeRead)
def update_employee(
    employee_id: UUID,
    payload: EmployeeUpdate,
    db: Session = Depends(get_db),
    request_context: RequestContext | None = Depends(get_request_context),
) -> Employee:
    employee = db.get(Employee, employee_id)
    if not employee:
        raise HTTPException(status_code=404, detail="Employee not found")

    before = EmployeeRead.model_validate(employee).model_dump(mode="json")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(employee, field, value)
    record_audit(
        db,
        action="employee.update",
        resource_type="employee",
        resource_id=str(employee.id),
        before=before,
        after=payload.model_dump(exclude_unset=True, mode="json"),
        **audit_context_kwargs(request_context),
    )
    db.commit()
    db.refresh(employee)
    return employee
