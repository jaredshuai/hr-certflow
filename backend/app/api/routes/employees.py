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
from app.domain.enums import EmploymentStatus
from app.models import Employee
from app.schemas.employees import (
    EmployeeCreate,
    EmployeeImportErrorRead,
    EmployeeImportResultRead,
    EmployeePageRead,
    EmployeeRead,
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
) -> Response:
    rows = db.scalars(
        _employee_statement(
            keyword=keyword,
            employee_no=employee_no,
            name=name,
            department=department,
            position=position,
            employment_status=employment_status,
        ).order_by(Employee.created_at.desc())
    ).all()
    return Response(
        content=build_employees_csv(rows),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="employees.csv"'},
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
