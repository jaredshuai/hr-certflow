from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "collect_hr_scenario_evidence.py"
MODULE_NAME = "collect_hr_scenario_evidence"
SPEC = importlib.util.spec_from_file_location(MODULE_NAME, SCRIPT_PATH)
assert SPEC and SPEC.loader
scenario_evidence = importlib.util.module_from_spec(SPEC)
sys.modules[MODULE_NAME] = scenario_evidence
SPEC.loader.exec_module(scenario_evidence)

ScenarioEvidenceCollector = scenario_evidence.ScenarioEvidenceCollector
normalize_api_base_url = scenario_evidence.normalize_api_base_url
render_markdown = scenario_evidence.render_markdown


class FakeClient:
    def __init__(self, json_payloads: dict[str, Any], bytes_payloads: dict[str, tuple[bytes, str]]) -> None:
        self.json_payloads = json_payloads
        self.bytes_payloads = bytes_payloads
        self.json_calls: list[tuple[str, dict[str, Any] | None]] = []
        self.bytes_calls: list[str] = []

    def get_json(self, path: str, params: dict[str, Any] | None = None) -> Any:
        self.json_calls.append((path, params))
        payload = self.json_payloads[path]
        return payload(params) if callable(payload) else payload

    def get_bytes(self, path: str, params: dict[str, Any] | None = None) -> tuple[bytes, str]:
        self.bytes_calls.append(path)
        return self.bytes_payloads[path]


def test_collect_hr_scenario_evidence_passes_complete_promoted_chain() -> None:
    client = FakeClient(_complete_json_payloads(), _csv_payloads())
    report = ScenarioEvidenceCollector(
        client,  # type: ignore[arg-type]
        base_url="http://example.test/hr-certflow-dev",
        employee_no="E-SECRET-001",
        certificate_type_code="TYPE-SECRET",
        certificate_no="CERT-SECRET-001",
    ).collect()

    statuses = {item["key"]: item["status"] for item in report["evidence"]}

    assert report["ok"] is True
    assert statuses["health"] == "PASS"
    assert statuses["csv_exports"] == "PASS"
    assert statuses["formal_certificate"] == "PASS"
    assert statuses["certificate_replacement"] == "PASS"
    assert statuses["reminder_feedback_closure"] == "PASS"
    assert report["resource_ids"] == {
        "employee_id": "employee-1",
        "certificate_type_id": "type-1",
        "certificate_id": "certificate-1",
        "document_id": "document-1",
        "ai_result_id": "ai-1",
        "review_task_id": "review-1",
        "reminder_task_id": "reminder-1",
    }

    rendered = json.dumps(report, ensure_ascii=False) + render_markdown(report)
    assert "E-SECRET-001" not in rendered
    assert "TYPE-SECRET" not in rendered
    assert "CERT-SECRET-001" not in rendered


def test_collect_hr_scenario_evidence_fails_without_formal_certificate_anchor() -> None:
    payloads = _complete_json_payloads()
    payloads["/certificates/page"] = {"data": [], "total": 0}
    client = FakeClient(payloads, _csv_payloads())

    report = ScenarioEvidenceCollector(
        client,  # type: ignore[arg-type]
        base_url="http://example.test/hr-certflow-dev",
    ).collect()

    statuses = {item["key"]: item["status"] for item in report["evidence"]}
    assert report["ok"] is False
    assert statuses["scenario_anchor"] == "FAIL"
    assert "certificate_id" not in report["resource_ids"]


def test_collect_hr_scenario_evidence_continues_when_dashboard_trace_fails() -> None:
    payloads = _complete_json_payloads()

    def raise_trace_error(params: dict[str, Any] | None) -> Any:
        raise RuntimeError("HTTP 404")

    payloads["/dashboard/risk-items/expired-certificates/trace"] = raise_trace_error
    client = FakeClient(payloads, _csv_payloads())

    report = ScenarioEvidenceCollector(
        client,  # type: ignore[arg-type]
        base_url="http://example.test/hr-certflow-dev",
        certificate_id="certificate-1",
    ).collect()

    statuses = {item["key"]: item["status"] for item in report["evidence"]}
    assert report["ok"] is False
    assert statuses["dashboard_risk_trace"] == "FAIL"
    assert statuses["csv_exports"] == "PASS"
    assert statuses["formal_certificate"] == "PASS"


def test_normalize_api_base_url_keeps_existing_api_prefix() -> None:
    assert normalize_api_base_url("http://example.test/hr-certflow-dev", None) == (
        "http://example.test/hr-certflow-dev/api/v1"
    )
    assert normalize_api_base_url("http://example.test/hr-certflow-dev/api/v1", None) == (
        "http://example.test/hr-certflow-dev/api/v1"
    )
    assert normalize_api_base_url("http://example.test/web", "http://api.example.test/api/v1") == (
        "http://api.example.test/api/v1"
    )


def _csv_payloads() -> dict[str, tuple[bytes, str]]:
    return {
        "/employees/export.csv": (b"\xef\xbb\xbfemployees\n", "text/csv; charset=utf-8"),
        "/certificate-types/export.csv": (b"\xef\xbb\xbftypes\n", "text/csv; charset=utf-8"),
        "/certificates/export.csv": (b"\xef\xbb\xbfcertificates\n", "text/csv; charset=utf-8"),
        "/documents/export.csv": (b"\xef\xbb\xbfdocuments\n", "text/csv; charset=utf-8"),
        "/reminders/tasks/export.csv": (b"\xef\xbb\xbfreminders\n", "text/csv; charset=utf-8"),
        "/reports/certificate-coverage/export.csv": (b"\xef\xbb\xbfreport\n", "text/csv; charset=utf-8"),
    }


def _complete_json_payloads() -> dict[str, Any]:
    certificate = {
        "id": "certificate-1",
        "employee_id": "employee-1",
        "certificate_type_id": "type-1",
        "source_document_id": "document-1",
        "replaced_by_id": None,
        "certificate_no": "CERT-SECRET-001",
        "holder_name": "Secret Holder",
        "issuing_authority": "Authority",
        "issue_date": "2026-01-01",
        "valid_from": "2026-01-01",
        "valid_to": "2026-12-31",
        "review_date": "2026-01-02",
        "status": "ACTIVE",
        "confirmed_by": "HR",
        "confirmed_at": "2026-01-02T00:00:00Z",
        "created_at": "2026-01-02T00:00:00Z",
        "updated_at": "2026-01-02T00:00:00Z",
    }
    replaced_certificate = {
        **certificate,
        "id": "certificate-old",
        "source_document_id": "document-old",
        "status": "REPLACED",
        "replaced_by_id": "certificate-1",
    }
    source_document = {
        "id": "document-1",
        "employee_id": "employee-1",
        "status": "CONFIRMED",
        "storage_bucket": "bucket",
        "storage_key": "redacted/key.pdf",
        "original_filename": "redacted.pdf",
        "content_type": "application/pdf",
        "file_size": 1024,
        "sha256": "0" * 64,
        "paperless_document_id": None,
        "failure_reason": None,
        "created_at": "2026-01-02T00:00:00Z",
        "updated_at": "2026-01-02T00:00:00Z",
    }
    ai_result = {
        "id": "ai-1",
        "document_id": "document-1",
        "workflow_run_id": "workflow-1",
        "model_name": "dify",
        "output_json": {"holder_name": "Secret Holder"},
        "raw_text": None,
        "suspicious_points": [],
        "confidence": 0.9,
        "raw_response_key": "snapshot/key.json",
        "created_at": "2026-01-02T00:00:00Z",
        "updated_at": "2026-01-02T00:00:00Z",
    }
    review_task = {
        "id": "review-1",
        "document_id": "document-1",
        "ai_result_id": "ai-1",
        "status": "APPROVED",
        "assigned_to": None,
        "reviewed_by": "HR",
        "reviewed_at": "2026-01-02T00:00:00Z",
        "decision_payload": {"certificate_id": "certificate-1"},
        "notes": None,
        "created_at": "2026-01-02T00:00:00Z",
        "updated_at": "2026-01-02T00:00:00Z",
    }
    reminder_task = {
        "id": "reminder-1",
        "employee_certificate_id": "certificate-1",
        "policy_id": "policy-1",
        "status": "RESOLVED",
        "trigger_date": "2026-01-01",
        "due_date": "2026-01-10",
        "last_event_at": "2026-01-03T00:00:00Z",
        "resolved_at": "2026-01-04T00:00:00Z",
        "closed_reason": "renewed",
        "idempotency_key": "key",
        "created_at": "2026-01-02T00:00:00Z",
        "updated_at": "2026-01-04T00:00:00Z",
    }
    audit_log = {
        "id": "audit-1",
        "action": "review_task.approve",
        "resource_type": "review_task",
        "resource_id": "review-1",
        "actor_name": "HR",
        "request_id": "request-1",
        "ip_address": "127.0.0.1",
        "created_at": "2026-01-02T00:00:00Z",
    }
    certificate_trace = {
        "certificate": certificate,
        "employee": {
            "id": "employee-1",
            "employee_no": "E-SECRET-001",
            "name": "Secret Holder",
            "department": "HR",
            "position": "Operator",
            "employment_status": "ACTIVE",
            "phone": None,
            "email": None,
            "created_at": "2026-01-01T00:00:00Z",
            "updated_at": "2026-01-01T00:00:00Z",
        },
        "certificate_type": {
            "id": "type-1",
            "code": "TYPE-SECRET",
            "name": "Required Type",
            "issuing_authority": "Authority",
        },
        "source_document": source_document,
        "ai_results": [ai_result],
        "review_tasks": [review_task],
        "reminder_tasks": [reminder_task],
        "feedback_items": [
            {
                "id": "feedback-1",
                "reminder_task_id": "reminder-1",
                "status": "RENEWED",
                "content": "closed",
                "created_by": "HR",
                "created_at": "2026-01-04T00:00:00Z",
            }
        ],
        "audit_logs": [audit_log],
    }
    document_trace = {
        "source_document": source_document,
        "ai_results": [ai_result],
        "review_tasks": [review_task],
        "certificates": [certificate],
        "audit_logs": [audit_log],
    }
    review_trace = {
        "review_task": review_task,
        "source_document": source_document,
        "ai_result": ai_result,
        "certificate": certificate,
        "audit_logs": [audit_log],
    }
    reminder_timeline = {
        "task": reminder_task,
        "events": [
            {
                "id": "event-1",
                "reminder_task_id": "reminder-1",
                "event_type": "FEEDBACK",
                "event_date": "2026-01-04",
                "channel": "hr_feedback",
                "recipient": "HR",
                "provider_message_id": None,
                "payload": {"status": "RENEWED"},
                "sent_at": "2026-01-04T00:00:00Z",
                "error": None,
                "created_at": "2026-01-04T00:00:00Z",
                "updated_at": "2026-01-04T00:00:00Z",
            }
        ],
        "feedback_items": [
            {
                "id": "feedback-1",
                "reminder_task_id": "reminder-1",
                "employee_certificate_id": "certificate-1",
                "status": "RENEWED",
                "content": "closed",
                "created_by": "HR",
                "created_at": "2026-01-04T00:00:00Z",
                "updated_at": "2026-01-04T00:00:00Z",
            }
        ],
        "audit_logs": [audit_log],
    }
    return {
        "/health": {
            "status": "ok",
            "service": "hr-certflow",
            "environment": "dev",
            "timestamp": "2026-01-01T00:00:00Z",
        },
        "/dashboard/summary": {
            "expiring_count": 1,
            "expired_count": 1,
            "pending_review_count": 0,
            "coverage": 100,
            "certificate_status_rows": [{"category": "有效", "count": 1, "target_path": "/certificates?status=ACTIVE"}],
            "workload_rows": [{"category": "已过期", "count": 1, "target_path": "/certificates?status=EXPIRED"}],
            "pipeline_steps": [{"title": "正式入库", "count": 1, "target_path": "/certificates?status_group=current"}],
            "risk_rows": [{"id": "expired-certificates", "metric": "已过期证书", "count": 1, "target_path": "/x"}],
        },
        "/reports/certificate-coverage": {
            "employee_count": 1,
            "covered_employee_count": 1,
            "coverage": 100,
            "department_rows": [{"department": "HR", "employee_count": 1, "target_path": "/employees?department=HR"}],
            "certificate_type_risk_rows": [
                {
                    "certificate_type_id": "type-1",
                    "certificate_type_name": "Required Type",
                    "is_required": True,
                    "active_count": 1,
                    "expiring_count": 0,
                    "expired_count": 1,
                    "missing_employee_count": 0,
                    "risk_count": 1,
                    "target_path": "/certificates?certificate_type_id=type-1",
                    "active_target_path": "/certificates?status_group=current",
                    "expired_target_path": "/certificates?status=EXPIRED",
                }
            ],
            "expiry_month_rows": [{"category": "2026-12", "count": 1, "target_path": "/certificates?month=2026-12"}],
        },
        "/dashboard/risk-items/expired-certificates/trace": {
            "risk": {"id": "expired-certificates", "metric": "已过期证书", "count": 1},
            "certificates": [replaced_certificate],
            "documents": [source_document],
            "review_tasks": [],
            "reminder_tasks": [reminder_task],
            "audit_logs": [audit_log],
            "missing_required_items": [],
        },
        "/employees/page": {"data": [certificate_trace["employee"]], "total": 1},
        "/certificate-types/page": {"data": [certificate_trace["certificate_type"]], "total": 1},
        "/certificates/page": lambda params: {
            "data": [certificate, replaced_certificate]
            if params and params.get("employee_id")
            else [certificate],
            "total": 2 if params and params.get("employee_id") else 1,
        },
        "/certificates/certificate-1/trace": certificate_trace,
        "/documents/document-1/trace": document_trace,
        "/reviews/review-1/trace": review_trace,
        "/reminders/tasks/reminder-1/timeline": reminder_timeline,
    }
