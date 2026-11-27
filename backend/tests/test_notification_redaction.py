"""G-03 Webhook 凭据泄露止血的回归测试。

修复前的泄露链：
``httpx.HTTPStatusError`` 的 ``str(exc)`` 携带完整 Webhook URL（查询串里是企微/钉钉的
key、飞书在 path 末段的令牌），被原样写进派发结果 → ``ReminderEvent.payload``/``error``
→ 审计 ``after["results"]`` → 前端回显。这里锁定修复后的三道闸门：

1. ``_send_webhook``/``send_to_hr`` 只产出固定原因码 + 脱敏后的 ``scheme+host+path``；
2. ``sanitize_audit_payload`` 对字符串做值级凭据掩码（``key=``/``token=`` 等）；
3. 提醒派发失败结果按原因码落 ``ReminderEvent``（见 test_reminder_service_unit）。
"""

from __future__ import annotations

import json
import smtplib

import httpx
import pytest

from app.core.config import Settings
from app.services import notifications as notifications_module
from app.services.audit import sanitize_audit_payload
from app.services.notifications import (
    NotificationMessage,
    NotificationRouter,
    _delivery_error_code,
    _sanitize_webhook_url,
)

SECRET_KEY = "SUPER-SECRET-KEY-123"
WECOM_URL = f"https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key={SECRET_KEY}"
FEISHU_TOKEN = "8c1e7d2f-4a3b-4c5d-9e6f-7a8b9c0d1e2f"
FEISHU_URL = f"https://open.feishu.cn/open-apis/bot/v2/hook/{FEISHU_TOKEN}"
DINGTALK_URL = f"https://oapi.dingtalk.com/robot/send?access_token={SECRET_KEY}"


def _message() -> NotificationMessage:
    return NotificationMessage(title="证书即将到期提醒", content="请跟进", recipients=["hr@example.test"])


def _http_status_error(url: str, status_code: int = 404) -> httpx.HTTPStatusError:
    request = httpx.Request("POST", url)
    response = httpx.Response(status_code, request=request)
    # 真实 httpx 的消息形态：Client error '404 Not Found' for url '...?key=<secret>'
    return httpx.HTTPStatusError(
        f"Client error '{status_code} Not Found' for url '{url}'", request=request, response=response
    )


class _FailingWebhookClient:
    """抛出携带完整 URL（含凭据）的异常，模拟真实 httpx 行为。"""

    def __init__(self, exc: Exception) -> None:
        self._exc = exc

    def __enter__(self) -> _FailingWebhookClient:
        return self

    def __exit__(self, *_args: object) -> bool:
        return False

    def post(self, *_args: object, **_kwargs: object) -> httpx.Response:
        raise self._exc


# --- 原因码映射 ---------------------------------------------------------------


def test_delivery_error_code_maps_http_status_error() -> None:
    assert _delivery_error_code(_http_status_error(WECOM_URL)) == "WEBHOOK_HTTP_404"


def test_delivery_error_code_maps_network_error() -> None:
    assert _delivery_error_code(httpx.ConnectError("connection refused")) == "WEBHOOK_NETWORK_ERROR"
    assert _delivery_error_code(httpx.ReadTimeout("timed out")) == "WEBHOOK_NETWORK_ERROR"


def test_delivery_error_code_maps_smtp_and_unknown() -> None:
    assert _delivery_error_code(smtplib.SMTPException("smtp down")) == "EMAIL_SMTP_ERROR"
    assert _delivery_error_code(RuntimeError("anything")) == "DELIVERY_ERROR"


# --- URL 脱敏 ----------------------------------------------------------------


def test_sanitize_webhook_url_strips_query_credentials() -> None:
    assert _sanitize_webhook_url(WECOM_URL) == "https://qyapi.weixin.qq.com/cgi-bin/webhook/send"
    assert _sanitize_webhook_url(DINGTALK_URL) == "https://oapi.dingtalk.com/robot/send"


def test_sanitize_webhook_url_masks_feishu_path_token() -> None:
    # 飞书自定义机器人的令牌在 path 末段：只剥 query 会漏掉，必须一并掩码。
    sanitized = _sanitize_webhook_url(FEISHU_URL)
    assert sanitized == "https://open.feishu.cn/open-apis/bot/v2/hook/***"
    assert FEISHU_TOKEN not in sanitized


@pytest.mark.parametrize("url", ["", "not-a-url", "http:///no-host"], ids=["empty", "garbage", "hostless"])
def test_sanitize_webhook_url_invalid_input(url: str) -> None:
    assert _sanitize_webhook_url(url) == "invalid-webhook-url"


# --- _send_webhook：结果只含原因码与脱敏 target --------------------------------


def test_send_webhook_http_failure_returns_reason_code_only(monkeypatch) -> None:
    settings = Settings(wecom_webhook_url=WECOM_URL)
    monkeypatch.setattr(
        notifications_module.httpx,
        "Client",
        lambda *_a, **_k: _FailingWebhookClient(_http_status_error(WECOM_URL)),
    )

    result = NotificationRouter(settings)._send_webhook("wecom", WECOM_URL, _message())

    assert result == {
        "channel": "wecom",
        "status": "failed",
        "error": "WEBHOOK_HTTP_404",
        "target": "https://qyapi.weixin.qq.com/cgi-bin/webhook/send",
    }
    assert SECRET_KEY not in json.dumps(result)


def test_send_webhook_network_failure_returns_reason_code_only(monkeypatch) -> None:
    settings = Settings(feishu_webhook_url=FEISHU_URL)
    monkeypatch.setattr(
        notifications_module.httpx,
        "Client",
        lambda *_a, **_k: _FailingWebhookClient(httpx.ConnectError(f"failed to connect to {FEISHU_URL}")),
    )

    result = NotificationRouter(settings)._send_webhook("feishu", FEISHU_URL, _message())

    assert result["status"] == "failed"
    assert result["error"] == "WEBHOOK_NETWORK_ERROR"
    assert result["target"] == "https://open.feishu.cn/open-apis/bot/v2/hook/***"
    assert FEISHU_TOKEN not in json.dumps(result)


def test_send_to_hr_email_smtp_failure_returns_reason_code(monkeypatch) -> None:
    settings = Settings(
        smtp_host="smtp.example.test",
        mail_from="hr@example.test",
        notification_hr_recipients="hr@example.test",
    )
    exc = smtplib.SMTPRecipientsRefused({"hr@example.test": (550, "b'b'")})

    def raising_sync(*_args: object) -> None:
        raise exc

    monkeypatch.setattr(NotificationRouter, "_send_email_sync", raising_sync)

    results = NotificationRouter(settings).send_to_hr(_message(), ["email"])

    assert results == [{"channel": "email", "status": "failed", "error": "EMAIL_SMTP_ERROR"}]


# --- 审计值级掩码 -------------------------------------------------------------


def test_sanitize_audit_payload_masks_credential_query_strings() -> None:
    leaked = f"Client error '404 Not Found' for url '{WECOM_URL}' and '{DINGTALK_URL}'"
    sanitized = sanitize_audit_payload({"error": leaked})

    text = json.dumps(sanitized, ensure_ascii=False)
    assert SECRET_KEY not in text
    assert "key=***" in text
    assert "access_token=***" in text


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("token=abc123", "token=***"),
        ("access_token=abc123", "access_token=***"),
        ("access-token=abc123", "access-token=***"),
        ("secret=abc123", "secret=***"),
        ("client_secret=abc123", "client_secret=***"),
        ("signature=abc123", "signature=***"),
        ("password=abc123", "password=***"),
        ("api key=hunter2", "api key=***"),
        ("错误：?key=abc123&x=1", "错误：?key=***&x=1"),
    ],
    ids=["token", "access_token", "access-token", "secret", "client_secret", "signature", "password", "key", "query"],
)
def test_sanitize_audit_payload_masks_credential_value_patterns(value: str, expected: str) -> None:
    assert sanitize_audit_payload(value) == expected


@pytest.mark.parametrize(
    "value",
    [
        "keyword=员工",
        "storage_key=documents/2026/demo.pdf",
        "event_window_key=abc:FIRST_REMINDER",
        "覆盖率=87.5",
        "已覆盖员工数=36",
    ],
    ids=["keyword", "storage_key", "event_window_key", "chinese-eq", "chinese-count"],
)
def test_sanitize_audit_payload_keeps_non_credential_text(value: str) -> None:
    assert sanitize_audit_payload(value) == value


def test_sanitize_audit_payload_masks_nested_failure_results() -> None:
    payload = {
        "results": [
            {
                "channel": "wecom",
                "status": "failed",
                "error": f"Client error '404' for url '{WECOM_URL}'",
            }
        ]
    }
    sanitized = sanitize_audit_payload(payload)
    text = json.dumps(sanitized, ensure_ascii=False)
    assert SECRET_KEY not in text
    assert "key=***" in text
