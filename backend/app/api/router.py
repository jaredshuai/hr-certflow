from __future__ import annotations

from fastapi import APIRouter

from app.api.routes import (
    audit,
    certificate_types,
    certificates,
    documents,
    employees,
    health,
    reminders,
    reviews,
)

api_router = APIRouter()
api_router.include_router(health.router, tags=["health"])
api_router.include_router(employees.router, prefix="/employees", tags=["employees"])
api_router.include_router(certificate_types.router, prefix="/certificate-types", tags=["certificate-types"])
api_router.include_router(certificates.router, prefix="/certificates", tags=["certificates"])
api_router.include_router(documents.router, prefix="/documents", tags=["documents"])
api_router.include_router(reviews.router, prefix="/reviews", tags=["reviews"])
api_router.include_router(reminders.router, prefix="/reminders", tags=["reminders"])
api_router.include_router(audit.router, prefix="/audit-logs", tags=["audit-logs"])
