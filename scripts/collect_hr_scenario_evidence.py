from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


EvidenceStatus = Literal["PASS", "FAIL", "WARN"]

CURRENT_CERTIFICATE_STATUSES = {"ACTIVE", "EXPIRING"}
FORMAL_CERTIFICATE_STATUSES = {"ACTIVE", "EXPIRING", "EXPIRED", "RENEWED", "REPLACED", "ARCHIVED"}
CLOSED_REMINDER_STATUSES = {"RESOLVED", "CLOSED"}
CSV_EXPORT_PATHS = {
    "employees": "/employees/export.csv",
    "certificate_types": "/certificate-types/export.csv",
    "certificates": "/certificates/export.csv",
    "documents": "/documents/export.csv",
    "reminders": "/reminders/tasks/export.csv",
    "coverage_report": "/reports/certificate-coverage/export.csv",
}


@dataclass
class EvidenceItem:
    key: str
    title: str
    status: EvidenceStatus
    summary: str
    resource_ids: dict[str, str] = field(default_factory=dict)
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "key": self.key,
            "title": self.title,
            "status": self.status,
            "summary": self.summary,
        }
        if self.resource_ids:
            payload["resource_ids"] = self.resource_ids
        if self.details:
            payload["details"] = self.details
        return payload


class ApiClient:
    def __init__(self, api_base_url: str, *, timeout: int = 10) -> None:
        self.api_base_url = api_base_url.rstrip("/")
        self.timeout = timeout

    def get_json(self, path: str, params: dict[str, Any] | None = None) -> Any:
        content, _content_type = self.get_bytes(path, params=params)
        try:
            return json.loads(content.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"GET {path} returned non-JSON payload") from exc

    def get_bytes(self, path: str, params: dict[str, Any] | None = None) -> tuple[bytes, str]:
        request = Request(
            self._build_url(path, params),
            headers={"User-Agent": "hr-certflow-scenario-evidence/0.1"},
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:
                status = int(getattr(response, "status", response.getcode()))
                if status >= 400:
                    raise RuntimeError(f"GET {path} failed: HTTP {status}")
                content_type = response.headers.get("content-type", "")
                return response.read(), content_type
        except HTTPError as exc:
            body = exc.read(512).decode("utf-8", errors="replace")
            raise RuntimeError(f"GET {path} failed: HTTP {exc.code}: {body[:200]}") from exc
        except (TimeoutError, URLError) as exc:
            raise RuntimeError(f"GET {path} failed: {exc}") from exc

    def _build_url(self, path: str, params: dict[str, Any] | None) -> str:
        normalized_path = path if path.startswith("/") else f"/{path}"
        url = f"{self.api_base_url}{normalized_path}"
        if not params:
            return url
        filtered_params = {
            key: value
            for key, value in params.items()
            if value is not None and value != "" and value != []
        }
        if not filtered_params:
            return url
        return f"{url}?{urlencode(filtered_params, doseq=True)}"


class ScenarioEvidenceCollector:
    def __init__(
        self,
        client: ApiClient,
        *,
        base_url: str,
        employee_no: str | None = None,
        certificate_type_code: str | None = None,
        certificate_no: str | None = None,
        certificate_id: str | None = None,
        document_id: str | None = None,
        review_task_id: str | None = None,
        reminder_task_id: str | None = None,
    ) -> None:
        self.client = client
        self.base_url = base_url.rstrip("/")
        self.employee_no = employee_no
        self.certificate_type_code = certificate_type_code
        self.certificate_no = certificate_no
        self.certificate_id = certificate_id
        self.document_id = document_id
        self.review_task_id = review_task_id
        self.reminder_task_id = reminder_task_id
        self.items: list[EvidenceItem] = []
        self.resources: dict[str, str] = {}

    def collect(self) -> dict[str, Any]:
        self._run("health", "环境健康", self._check_health)
        self._run("dashboard_reports", "看板与报表钻取", self._check_dashboard_and_reports)
        self._run("exports", "导出接口", self._check_exports)
        self._run("scenario_chain", "端到端 HR 业务链路", self._check_scenario_chain)

        ok = not any(item.status == "FAIL" for item in self.items)
        return {
            "ok": ok,
            "generated_at": datetime.now(UTC).isoformat(),
            "base_url": self.base_url,
            "selector_presence": {
                "employee_no": bool(self.employee_no),
                "certificate_type_code": bool(self.certificate_type_code),
                "certificate_no": bool(self.certificate_no),
                "certificate_id": bool(self.certificate_id),
                "document_id": bool(self.document_id),
                "review_task_id": bool(self.review_task_id),
                "reminder_task_id": bool(self.reminder_task_id),
            },
            "resource_ids": self.resources,
            "evidence": [item.to_dict() for item in self.items],
        }

    def _run(self, key: str, title: str, callback) -> None:
        try:
            callback()
        except Exception as exc:
            self._add(key, title, "FAIL", str(exc))

    def _add(
        self,
        key: str,
        title: str,
        status: EvidenceStatus,
        summary: str,
        *,
        resource_ids: dict[str, str] | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.items.append(
            EvidenceItem(
                key=key,
                title=title,
                status=status,
                summary=summary,
                resource_ids=resource_ids or {},
                details=details or {},
            )
        )

    def _check_health(self) -> None:
        health = self.client.get_json("/health")
        if health.get("status") != "ok":
            self._add("health", "API 健康检查", "FAIL", "健康检查未返回 ok")
            return
        self._add(
            "health",
            "API 健康检查",
            "PASS",
            "API health 返回 ok",
            details={
                "service": health.get("service"),
                "environment": health.get("environment"),
            },
        )

    def _check_dashboard_and_reports(self) -> None:
        summary = self.client.get_json("/dashboard/summary")
        report = self.client.get_json("/reports/certificate-coverage")
        summary_target_count = self._count_target_paths(
            summary.get("certificate_status_rows", []),
            summary.get("workload_rows", []),
            summary.get("pipeline_steps", []),
            summary.get("risk_rows", []),
        )
        report_target_count = self._count_target_paths(
            report.get("department_rows", []),
            report.get("certificate_type_risk_rows", []),
            report.get("expiry_month_rows", []),
        )
        if summary_target_count == 0 or report_target_count == 0:
            self._add(
                "dashboard_report_targets",
                "看板/报表钻取路径",
                "FAIL",
                "看板或报表没有可验证的 target_path",
                details={
                    "dashboard_target_paths": summary_target_count,
                    "report_target_paths": report_target_count,
                },
            )
        else:
            self._add(
                "dashboard_report_targets",
                "看板/报表钻取路径",
                "PASS",
                "看板和报表返回可钻取 target_path",
                details={
                    "dashboard_target_paths": summary_target_count,
                    "report_target_paths": report_target_count,
                },
            )

        risk_rows = [row for row in summary.get("risk_rows", []) if row.get("id") and int(row.get("count") or 0) > 0]
        if not risk_rows:
            self._add("dashboard_risk_trace", "看板风险追踪", "WARN", "当前环境没有非零风险行可追踪")
            return

        traced = 0
        trace_payloads = 0
        trace_errors: list[str] = []
        for row in risk_rows[:3]:
            risk_id = str(row["id"])
            try:
                trace = self.client.get_json(f"/dashboard/risk-items/{risk_id}/trace", params={"limit": 5})
            except Exception as exc:
                trace_errors.append(f"{risk_id}: {exc}")
                continue
            traced += 1
            trace_payloads += sum(
                len(trace.get(field) or [])
                for field in (
                    "certificates",
                    "documents",
                    "review_tasks",
                    "reminder_tasks",
                    "audit_logs",
                    "missing_required_items",
                )
            )
        if trace_payloads:
            self._add(
                "dashboard_risk_trace",
                "看板风险追踪",
                "PASS",
                "非零风险行可以追踪到源记录",
                details={"risk_rows_checked": traced, "trace_payload_items": trace_payloads},
            )
        elif trace_errors:
            self._add(
                "dashboard_risk_trace",
                "看板风险追踪",
                "FAIL",
                "非零风险行 trace 接口不可用或返回错误",
                details={"risk_rows_checked": traced, "trace_errors": trace_errors[:3]},
            )
        else:
            self._add(
                "dashboard_risk_trace",
                "看板风险追踪",
                "FAIL",
                "非零风险行没有返回源记录",
                details={"risk_rows_checked": traced},
            )

    def _check_exports(self) -> None:
        failed: list[str] = []
        export_sizes: dict[str, int] = {}
        for name, path in CSV_EXPORT_PATHS.items():
            content, content_type = self.client.get_bytes(path)
            export_sizes[name] = len(content)
            if len(content) == 0 or "csv" not in content_type.lower():
                failed.append(name)
        if failed:
            self._add(
                "csv_exports",
                "CSV 导出",
                "FAIL",
                "存在不可用的 CSV 导出接口",
                details={"failed_exports": failed, "byte_counts": export_sizes},
            )
            return
        self._add(
            "csv_exports",
            "CSV 导出",
            "PASS",
            "员工、证书类型、证书、原件、提醒、覆盖报表导出均可访问",
            details={"byte_counts": export_sizes},
        )

    def _check_scenario_chain(self) -> None:
        selected_employee = self._find_employee_by_selector()
        selected_type = self._find_certificate_type_by_selector()
        certificate = self._find_certificate(selected_employee, selected_type)
        if not certificate:
            self._add(
                "scenario_anchor",
                "场景锚点",
                "FAIL",
                "没有找到可用于证明端到端链路的正式证书；请提供 certificate_no 或 certificate_id",
            )
            return

        certificate_id = str(certificate["id"])
        self.resources["certificate_id"] = certificate_id
        trace = self.client.get_json(f"/certificates/{certificate_id}/trace")
        self._check_master_data(trace, selected_employee, selected_type)
        self._check_upload_and_ai(trace)
        self._check_review_and_certificate(trace)
        self._check_replacement(trace.get("certificate") or certificate)
        self._check_trace_endpoints(trace)
        self._check_reminder_loop(trace)

    def _find_employee_by_selector(self) -> dict[str, Any] | None:
        if not self.employee_no:
            return None
        payload = self.client.get_json(
            "/employees/page",
            params={"current": 1, "page_size": 10, "employee_no": self.employee_no},
        )
        employee = self._first(payload.get("data", []))
        if employee:
            self.resources["employee_id"] = str(employee["id"])
        return employee

    def _find_certificate_type_by_selector(self) -> dict[str, Any] | None:
        if not self.certificate_type_code:
            return None
        payload = self.client.get_json(
            "/certificate-types/page",
            params={"current": 1, "page_size": 10, "code": self.certificate_type_code},
        )
        certificate_type = self._first(payload.get("data", []))
        if certificate_type:
            self.resources["certificate_type_id"] = str(certificate_type["id"])
        return certificate_type

    def _find_certificate(
        self,
        selected_employee: dict[str, Any] | None,
        selected_type: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        if self.certificate_id:
            return {"id": self.certificate_id}

        params: dict[str, Any] = {
            "current": 1,
            "page_size": 100,
            "certificate_no": self.certificate_no,
            "employee_id": selected_employee.get("id") if selected_employee else None,
            "certificate_type_id": selected_type.get("id") if selected_type else None,
        }
        if not self.certificate_no:
            params["status_group"] = "current"

        payload = self.client.get_json("/certificates/page", params=params)
        rows = list(payload.get("data", []))
        if not rows and params.get("status_group"):
            params.pop("status_group")
            payload = self.client.get_json("/certificates/page", params=params)
            rows = list(payload.get("data", []))

        return self._prefer_linked_certificate(rows)

    def _check_master_data(
        self,
        trace: dict[str, Any],
        selected_employee: dict[str, Any] | None,
        selected_type: dict[str, Any] | None,
    ) -> None:
        employee = trace.get("employee") or selected_employee
        certificate_type = trace.get("certificate_type") or selected_type
        if employee:
            self.resources["employee_id"] = str(employee["id"])
            self._add(
                "employee_master_data",
                "员工主数据",
                "PASS",
                "正式证书可以追踪到员工主数据",
                resource_ids={"employee_id": str(employee["id"])},
                details={"employment_status": employee.get("employment_status")},
            )
        else:
            self._add("employee_master_data", "员工主数据", "FAIL", "正式证书未返回员工主数据追踪")

        if certificate_type:
            self.resources["certificate_type_id"] = str(certificate_type["id"])
            self._add(
                "certificate_type_master_data",
                "证书类型主数据",
                "PASS",
                "正式证书可以追踪到证书类型主数据",
                resource_ids={"certificate_type_id": str(certificate_type["id"])},
            )
        else:
            self._add("certificate_type_master_data", "证书类型主数据", "FAIL", "正式证书未返回证书类型追踪")

    def _check_upload_and_ai(self, trace: dict[str, Any]) -> None:
        document = trace.get("source_document")
        if not document:
            self._add("upload_integrity", "上传完整性", "FAIL", "正式证书没有 source_document")
            self._add("dify_extraction", "Dify 抽取结果", "FAIL", "缺少 source_document，无法证明 AI 抽取链路")
            return

        self.resources["document_id"] = str(document["id"])
        upload_ok = (
            document.get("status") == "CONFIRMED"
            and bool(document.get("sha256"))
            and bool(document.get("file_size"))
            and bool(document.get("content_type"))
        )
        self._add(
            "upload_integrity",
            "上传完整性",
            "PASS" if upload_ok else "FAIL",
            "原件已确认并带有 hash/类型/大小" if upload_ok else "原件缺少确认状态、hash、类型或大小",
            resource_ids={"document_id": str(document["id"])},
            details={"document_status": document.get("status"), "has_sha256": bool(document.get("sha256"))},
        )

        ai_results = trace.get("ai_results") or []
        ai_result = self._first(ai_results)
        ai_ok = bool(
            ai_result
            and isinstance(ai_result.get("output_json"), dict)
            and isinstance(ai_result.get("suspicious_points"), list)
        )
        if ai_result:
            self.resources["ai_result_id"] = str(ai_result["id"])
        self._add(
            "dify_extraction",
            "Dify 抽取结果",
            "PASS" if ai_ok else "FAIL",
            "AI 抽取结果已按结构化字段持久化" if ai_ok else "缺少结构化 AI 抽取结果",
            resource_ids={"ai_result_id": str(ai_result["id"])} if ai_result else {},
            details={"ai_result_count": len(ai_results)},
        )

    def _check_review_and_certificate(self, trace: dict[str, Any]) -> None:
        review_tasks = trace.get("review_tasks") or []
        approved_review = self._first([task for task in review_tasks if task.get("status") == "APPROVED"])
        review_ok = bool(approved_review and approved_review.get("ai_result_id") and approved_review.get("reviewed_at"))
        if approved_review:
            self.resources["review_task_id"] = str(approved_review["id"])
        self._add(
            "human_review",
            "人工复核",
            "PASS" if review_ok else "FAIL",
            "存在已批准复核任务并关联 AI 结果" if review_ok else "缺少已批准复核任务或 AI 结果关联",
            resource_ids={"review_task_id": str(approved_review["id"])} if approved_review else {},
            details={"review_task_count": len(review_tasks)},
        )

        certificate = trace.get("certificate") or {}
        certificate_status = certificate.get("status")
        certificate_ok = bool(
            certificate.get("id")
            and certificate_status in FORMAL_CERTIFICATE_STATUSES
            and certificate.get("source_document_id")
            and certificate.get("confirmed_at")
        )
        self._add(
            "formal_certificate",
            "正式证书台账",
            "PASS" if certificate_ok else "FAIL",
            "正式证书已入库并关联来源原件" if certificate_ok else "正式证书缺少状态、确认时间或来源原件",
            resource_ids={"certificate_id": str(certificate.get("id"))} if certificate.get("id") else {},
            details={"certificate_status": certificate_status},
        )

    def _check_replacement(self, certificate: dict[str, Any]) -> None:
        selected_id = str(certificate.get("id"))
        if certificate.get("replaced_by_id"):
            self._add(
                "certificate_replacement",
                "证书替换链",
                "PASS",
                "所选证书本身已记录 replaced_by_id",
                resource_ids={"certificate_id": selected_id, "replaced_by_id": str(certificate["replaced_by_id"])},
            )
            return

        employee_id = certificate.get("employee_id")
        certificate_type_id = certificate.get("certificate_type_id")
        if not employee_id or not certificate_type_id:
            self._add("certificate_replacement", "证书替换链", "FAIL", "证书缺少员工或证书类型，无法验证替换链")
            return

        payload = self.client.get_json(
            "/certificates/page",
            params={
                "current": 1,
                "page_size": 100,
                "employee_id": employee_id,
                "certificate_type_id": certificate_type_id,
            },
        )
        related = payload.get("data", [])
        replaced_rows = [
            row
            for row in related
            if str(row.get("id")) != selected_id
            and (str(row.get("replaced_by_id")) == selected_id or row.get("status") in {"REPLACED", "RENEWED"})
        ]
        self._add(
            "certificate_replacement",
            "证书替换链",
            "PASS" if replaced_rows else "FAIL",
            "同员工/类型下存在被替换历史证书" if replaced_rows else "未找到证书替换历史",
            details={"related_certificate_count": len(related), "replaced_certificate_count": len(replaced_rows)},
        )

    def _check_trace_endpoints(self, certificate_trace: dict[str, Any]) -> None:
        certificate = certificate_trace.get("certificate") or {}
        document = certificate_trace.get("source_document") or {}
        review_tasks = certificate_trace.get("review_tasks") or []
        review = self._select_review_for_trace(review_tasks)

        document_trace = None
        if self.document_id or document.get("id"):
            document_id = self.document_id or str(document["id"])
            document_trace = self.client.get_json(f"/documents/{document_id}/trace")
            document_ok = bool(
                document_trace.get("source_document")
                and document_trace.get("ai_results")
                and document_trace.get("review_tasks")
                and document_trace.get("certificates")
            )
            self._add(
                "document_trace",
                "原件追踪",
                "PASS" if document_ok else "FAIL",
                "原件 trace 连接 AI、复核和正式证书" if document_ok else "原件 trace 缺少 AI、复核或正式证书",
                resource_ids={"document_id": document_id},
            )
        else:
            self._add("document_trace", "原件追踪", "FAIL", "缺少 document_id，无法验证原件 trace")

        review_trace = None
        if self.review_task_id or review:
            review_id = self.review_task_id or str(review["id"])
            review_trace = self.client.get_json(f"/reviews/{review_id}/trace")
            review_trace_ok = bool(
                review_trace.get("review_task")
                and review_trace.get("source_document")
                and review_trace.get("ai_result")
                and review_trace.get("certificate")
            )
            self._add(
                "review_trace",
                "复核追踪",
                "PASS" if review_trace_ok else "FAIL",
                "复核 trace 连接原件、AI 和正式证书" if review_trace_ok else "复核 trace 缺少原件、AI 或正式证书",
                resource_ids={"review_task_id": review_id},
            )
        else:
            self._add("review_trace", "复核追踪", "FAIL", "缺少 review_task_id，无法验证复核 trace")

        audit_logs = [
            *(certificate_trace.get("audit_logs") or []),
            *((document_trace or {}).get("audit_logs") or []),
            *((review_trace or {}).get("audit_logs") or []),
        ]
        audit_context_logs = [log for log in audit_logs if log.get("actor_name") and log.get("request_id")]
        self._add(
            "audit_trace",
            "审计追踪",
            "PASS" if audit_context_logs else "FAIL",
            "审计记录包含 actor 和 request_id" if audit_context_logs else "审计记录缺少 actor 或 request_id",
            details={"audit_log_count": len(audit_logs), "context_log_count": len(audit_context_logs)},
            resource_ids={"certificate_id": str(certificate.get("id"))} if certificate.get("id") else {},
        )

    def _check_reminder_loop(self, trace: dict[str, Any]) -> None:
        reminder = self._select_reminder(trace.get("reminder_tasks") or [])
        if not reminder:
            self._add("reminder_loop", "提醒闭环", "FAIL", "正式证书没有提醒任务")
            return

        reminder_id = self.reminder_task_id or str(reminder["id"])
        self.resources["reminder_task_id"] = reminder_id
        timeline = self.client.get_json(f"/reminders/tasks/{reminder_id}/timeline")
        task = timeline.get("task") or {}
        events = timeline.get("events") or []
        feedback_items = timeline.get("feedback_items") or []
        timeline_ok = bool(task and events)
        closure_ok = bool(task.get("status") in CLOSED_REMINDER_STATUSES and feedback_items)
        self._add(
            "reminder_timeline",
            "提醒时间线",
            "PASS" if timeline_ok else "FAIL",
            "提醒时间线包含任务和事件" if timeline_ok else "提醒时间线缺少任务或事件",
            resource_ids={"reminder_task_id": reminder_id},
            details={"event_count": len(events), "feedback_count": len(feedback_items), "task_status": task.get("status")},
        )
        self._add(
            "reminder_feedback_closure",
            "提醒反馈关闭",
            "PASS" if closure_ok else "FAIL",
            "提醒任务已通过反馈关闭或解决" if closure_ok else "提醒任务缺少反馈闭环",
            resource_ids={"reminder_task_id": reminder_id},
            details={"task_status": task.get("status"), "feedback_count": len(feedback_items)},
        )

    @staticmethod
    def _count_target_paths(*groups: list[dict[str, Any]]) -> int:
        count = 0
        for group in groups:
            for item in group:
                count += sum(1 for key, value in item.items() if key.endswith("target_path") and value)
        return count

    @staticmethod
    def _first(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
        return rows[0] if rows else None

    @staticmethod
    def _prefer_linked_certificate(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
        if not rows:
            return None
        current_linked = [
            row
            for row in rows
            if row.get("status") in CURRENT_CERTIFICATE_STATUSES and row.get("source_document_id")
        ]
        if current_linked:
            return current_linked[0]
        linked = [row for row in rows if row.get("source_document_id")]
        return linked[0] if linked else rows[0]

    @staticmethod
    def _select_review_for_trace(review_tasks: list[dict[str, Any]]) -> dict[str, Any] | None:
        approved = [task for task in review_tasks if task.get("status") == "APPROVED"]
        return approved[0] if approved else (review_tasks[0] if review_tasks else None)

    def _select_reminder(self, reminder_tasks: list[dict[str, Any]]) -> dict[str, Any] | None:
        if self.reminder_task_id:
            return {"id": self.reminder_task_id}
        closed = [task for task in reminder_tasks if task.get("status") in CLOSED_REMINDER_STATUSES]
        return closed[0] if closed else (reminder_tasks[0] if reminder_tasks else None)


def normalize_api_base_url(base_url: str, api_base_url: str | None) -> str:
    if api_base_url:
        return api_base_url.rstrip("/")
    normalized = base_url.rstrip("/")
    if normalized.endswith("/api/v1"):
        return normalized
    return f"{normalized}/api/v1"


def render_markdown(report: dict[str, Any]) -> str:
    status = "PASS" if report["ok"] else "FAIL"
    lines = [
        "# HR CertFlow Scenario Evidence",
        "",
        f"- Overall: {status}",
        f"- Generated at: {report['generated_at']}",
        f"- Base URL: {report['base_url']}",
        "",
        "## Resource Anchors",
        "",
    ]
    if report["resource_ids"]:
        for key, value in sorted(report["resource_ids"].items()):
            lines.append(f"- `{key}`: `{value}`")
    else:
        lines.append("- No scenario resource anchors were found.")

    lines.extend([
        "",
        "## Evidence Checks",
        "",
        "| Status | Check | Summary |",
        "| --- | --- | --- |",
    ])
    for item in report["evidence"]:
        lines.append(f"| {item['status']} | {item['title']} | {item['summary']} |")
    return "\n".join(lines) + "\n"


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Collect non-secret evidence for a promoted HR CertFlow end-to-end scenario.",
    )
    parser.add_argument("--base-url", required=True, help="Web base URL, for example http://host/hr-certflow-dev")
    parser.add_argument("--api-base-url", help="Optional API base URL. Defaults to <base-url>/api/v1")
    parser.add_argument("--timeout", type=int, default=10)
    parser.add_argument("--employee-no", help="Optional employee number selector. Value is not printed.")
    parser.add_argument("--certificate-type-code", help="Optional certificate type code selector. Value is not printed.")
    parser.add_argument("--certificate-no", help="Optional certificate number selector. Value is not printed.")
    parser.add_argument("--certificate-id", help="Optional certificate UUID selector.")
    parser.add_argument("--document-id", help="Optional source document UUID selector.")
    parser.add_argument("--review-task-id", help="Optional review task UUID selector.")
    parser.add_argument("--reminder-task-id", help="Optional reminder task UUID selector.")
    parser.add_argument("--output", type=Path, help="Write JSON report to this path.")
    parser.add_argument("--markdown-output", type=Path, help="Write Markdown report to this path.")
    parser.add_argument("--print-json", action="store_true", help="Print JSON instead of Markdown to stdout.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    api_base_url = normalize_api_base_url(args.base_url, args.api_base_url)
    client = ApiClient(api_base_url, timeout=args.timeout)
    collector = ScenarioEvidenceCollector(
        client,
        base_url=args.base_url,
        employee_no=args.employee_no,
        certificate_type_code=args.certificate_type_code,
        certificate_no=args.certificate_no,
        certificate_id=args.certificate_id,
        document_id=args.document_id,
        review_task_id=args.review_task_id,
        reminder_task_id=args.reminder_task_id,
    )
    report = collector.collect()
    json_report = json.dumps(report, ensure_ascii=False, indent=2)
    markdown_report = render_markdown(report)

    if args.output:
        args.output.write_text(json_report + "\n", encoding="utf-8")
    if args.markdown_output:
        args.markdown_output.write_text(markdown_report, encoding="utf-8")
    print(json_report if args.print_json else markdown_report)
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
