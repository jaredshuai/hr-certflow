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
    assert _sanitize_webhook_url(WECOM_URL, channel="wecom") == "https://qyapi.weixin.qq.com/cgi-bin/webhook/send"
    assert _sanitize_webhook_url(DINGTALK_URL, channel="dingtalk") == "https://oapi.dingtalk.com/robot/send"


def test_sanitize_webhook_url_masks_feishu_path_token() -> None:
    # 飞书自定义机器人的令牌在 path 末段：只剥 query 会漏掉，必须一并掩码。
    sanitized = _sanitize_webhook_url(FEISHU_URL, channel="feishu")
    assert sanitized == "https://open.feishu.cn/open-apis/bot/v2/hook/***"
    assert FEISHU_TOKEN not in sanitized


@pytest.mark.parametrize(
    "token", ["ab12", "x", "to-ken_1", "含中文的短令牌"], ids=["4-char", "1-char", "punctuated", "non-ascii"]
)
def test_sanitize_webhook_url_masks_short_feishu_path_token(token: str) -> None:
    # 飞书渠道的末段无论长短、字符集如何都是凭据段，确定性掩码（不靠 >=16 字符的启发式）。
    sanitized = _sanitize_webhook_url(f"https://open.feishu.cn/open-apis/bot/v2/hook/{token}", channel="feishu")
    assert sanitized == "https://open.feishu.cn/open-apis/bot/v2/hook/***"
    assert token not in sanitized


def test_sanitize_webhook_url_leaves_wecom_and_dingtalk_path_visible() -> None:
    # 这两家的凭据只在 query：path（/webhook/send、/robot/send）不是凭据，保留以便排查。
    for url, channel in ((WECOM_URL, "wecom"), (DINGTALK_URL, "dingtalk")):
        assert not _sanitize_webhook_url(url, channel=channel).endswith("***")


@pytest.mark.parametrize(
    ("url", "channel", "expected"),
    [
        ("https://user:secret@example.com/hook?key=abc", "wecom", "https://example.com/hook"),
        ("https://user@example.com/robot/send?access_token=abc", "dingtalk", "https://example.com/robot/send"),
        ("https://user:secret@example.com:8443/hook", "wecom", "https://example.com:8443/hook"),
        ("https://example.com:8443/hook", "wecom", "https://example.com:8443/hook"),
        ("https://user:secret@[2001:db8::1]:8443/hook", "wecom", "https://[2001:db8::1]:8443/hook"),
        ("https://user:secret@open.feishu.cn/open-apis/bot/v2/hook/short", "feishu", "https://open.feishu.cn/open-apis/bot/v2/hook/***"),
    ],
    ids=["userinfo", "user-only", "userinfo-port", "port", "ipv6", "userinfo-feishu"],
)
def test_sanitize_webhook_url_strips_userinfo_and_keeps_host_and_port(url: str, channel: str, expected: str) -> None:
    # netloc 原样带 user:password@；必须从 hostname（加合法 port）重新拼装。
    sanitized = _sanitize_webhook_url(url, channel=channel)
    assert sanitized == expected
    assert "user" not in sanitized
    assert "secret" not in sanitized


@pytest.mark.parametrize(
    "url",
    ["", "not-a-url", "http:///no-host", "https://example.com:abc/hook", "https://[::1:8443/hook"],
    ids=["empty", "garbage", "hostless", "bad-port", "bad-ipv6"],
)
def test_sanitize_webhook_url_invalid_input(url: str) -> None:
    assert _sanitize_webhook_url(url, channel="wecom") == "invalid-webhook-url"


# --- _send_webhook：结果只含原因码与脱敏 target --------------------------------


class _EchoingWebhookClient:
    """模拟会回显请求 URL 的 Webhook/代理：响应体原样带回带凭据的完整 URL。"""

    def __init__(self, request_url: str) -> None:
        self._request_url = request_url

    def __enter__(self) -> _EchoingWebhookClient:
        return self

    def __exit__(self, *_args: object) -> bool:
        return False

    def post(self, *_args: object, **_kwargs: object) -> httpx.Response:
        request = httpx.Request("POST", self._request_url)
        return httpx.Response(200, request=request, text=f'{{"echo":"{self._request_url}","errmsg":"ok"}}')


@pytest.mark.parametrize(
    ("channel", "url", "secret"),
    [("wecom", WECOM_URL, SECRET_KEY), ("feishu", FEISHU_URL, FEISHU_TOKEN)],
)
def test_send_webhook_success_omits_upstream_response_body(monkeypatch, channel: str, url: str, secret: str) -> None:
    settings = Settings(wecom_webhook_url=WECOM_URL, feishu_webhook_url=FEISHU_URL)
    monkeypatch.setattr(notifications_module.httpx, "Client", lambda *_a, **_k: _EchoingWebhookClient(url))

    result = NotificationRouter(settings)._send_webhook(channel, url, _message())

    # 成功结果不带原始响应体：否则被回显的 URL 会随 ReminderEvent.payload / 审计落库并回显。
    assert result == {"channel": channel, "status": "sent", "target": _sanitize_webhook_url(url, channel=channel)}
    assert secret not in json.dumps(result)


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


def test_send_webhook_failure_target_has_no_userinfo(monkeypatch) -> None:
    url = "https://user:secret@example.com/hook?key=abc"
    settings = Settings(wecom_webhook_url=url)
    monkeypatch.setattr(
        notifications_module.httpx, "Client", lambda *_a, **_k: _FailingWebhookClient(_http_status_error(url))
    )

    # 经真实 send_to_hr → _send_webhook，断言异常串里的 URL 带 userinfo 时失败结果与 target 都不含它。
    results = NotificationRouter(settings).send_to_hr(_message(), ["wecom"])

    assert results == [
        {"channel": "wecom", "status": "failed", "error": "WEBHOOK_HTTP_404", "target": "https://example.com/hook"}
    ]
    dumped = json.dumps(results)
    assert "secret" not in dumped
    assert "user:" not in dumped
    assert "key=" not in dumped


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
        ("session_id=abc123", "session_id=***"),
        ("sessionid=abc123", "sessionid=***"),
        ("?sessionId=abc123&next=/", "?sessionId=***&next=/"),
        ("session-id=abc123", "session-id=***"),
    ],
    ids=[
        "token",
        "access_token",
        "access-token",
        "secret",
        "client_secret",
        "signature",
        "password",
        "key",
        "query",
        "session_id-eq",
        "sessionid-eq",
        "sessionId-query",
        "session-id-eq",
    ],
)
def test_sanitize_audit_payload_masks_credential_value_patterns(value: str, expected: str) -> None:
    assert sanitize_audit_payload(value) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("Authorization: Bearer abc123", "Authorization: ***"),
        ("authorization: bearer abc123", "authorization: ***"),
        ("Authorization: Basic dXNlcjpwYXNz", "Authorization: ***"),
        # 方案名不是 Bearer/Basic 时同样整值掩掉，不留后半截令牌。
        ("X-Authorization: Token abc123", "X-Authorization: ***"),
        ('headers={"Authorization": "Bearer abc123"}', 'headers={"Authorization": "***"}'),
        ('{"Authorization":"Basic dXNlcjpwYXNz","cookie":"c"}', '{"Authorization":"***","cookie":"c"}'),
        ("{'Authorization': 'Bearer abc123', 'cookie': 'x'}", "{'Authorization': '***', 'cookie': 'x'}"),
        ("Bearer abc123", "Bearer ***"),
        ("curl -H 'Authorization: Bearer abc123' http://10.0.0.1/x", "curl -H 'Authorization: ***"),
        ("auth_token=abc123", "auth_token=***"),
        ("oauth_token=abc123", "oauth_token=***"),
        ("?auth_token=abc123&x=1", "?auth_token=***&x=1"),
        ('{"access_token": "abc123", "x": 1}', '{"access_token": "***", "x": 1}'),
        ("{'auth_token': 'abc123'}", "{'auth_token': '***'}"),
        ('"oauth_token":"abc123"', '"oauth_token":"***"'),
        ('token: "abc123"', 'token: "***"'),
        ("token: abc123", "token: ***"),
        (
            '{"token": "abc123", "auth_token": "def456", "oauth_token": "xyz789"}',
            '{"token": "***", "auth_token": "***", "oauth_token": "***"}',
        ),
        ('{"session_id": "abc123", "status": "failed"}', '{"session_id": "***", "status": "failed"}'),
        ("{'sessionid': 'abc123'}", "{'sessionid': '***'}"),
        ("session_id: abc123", "session_id: ***"),
        (
            "Invalid session for sessionid=abc123 bucket=hr-certflow-internal key=hr-certflow/test/secret-cert.pdf",
            "Invalid session for sessionid=*** bucket=hr-certflow-internal key=***",
        ),
    ],
    ids=[
        "bearer-header",
        "bearer-header-lower",
        "basic-header",
        "custom-scheme",
        "quoted-authorization-header",
        "quoted-authorization-compact",
        "quoted-authorization-keeps-siblings",
        "bare-bearer",
        "curl-command",
        "auth_token-eq",
        "oauth_token-eq",
        "auth_token-query",
        "json-quoted",
        "python-repr-quoted",
        "json-colon-compact",
        "quoted-colon-value",
        "bare-colon",
        "multiple-fields",
        "session_id-json",
        "sessionid-repr",
        "session_id-colon",
        "sessionid-in-exception-text",
    ],
)
def test_sanitize_audit_payload_masks_bearer_and_quoted_or_colon_credential_fields(value: str, expected: str) -> None:
    # cubic P1：原规则只认无引号 name=value，漏掉 Bearer 头、auth_token/oauth_token 及 JSON/冒号形态。
    sanitized = sanitize_audit_payload({"detail": value})
    assert sanitized == {"detail": expected}
    for secret in ("abc123", "dXNlcjpwYXNz", "def456", "xyz789"):
        assert secret not in json.dumps(sanitized, ensure_ascii=False)


def test_sanitize_audit_payload_masks_session_id_by_key_name() -> None:
    # cubic P1：session id 作为键出现时整值掩掉，大小写与连字符写法都算。
    payload = {
        "session_id": "abc123",
        "sessionid": "def456",
        "sessionId": "ghi789",
        "SESSION_ID": "jkl012",
        "Session-Id": "mno345",
        "status": "failed",
    }
    sanitized = sanitize_audit_payload(payload)

    assert sanitized == {
        "session_id": "***",
        "sessionid": "***",
        "sessionId": "***",
        "SESSION_ID": "***",
        "Session-Id": "***",
        "status": "failed",
    }


def test_sanitize_audit_payload_masks_bearer_header_inside_nested_exception_text() -> None:
    leaked = "HTTPStatusError: request failed, headers: {'Authorization': 'Bearer abc123'}, token: 'def456'"
    assert sanitize_audit_payload([{"error": leaked}]) == [
        {"error": "HTTPStatusError: request failed, headers: {'Authorization': '***'}, token: '***'"}
    ]


@pytest.mark.parametrize(
    "value",
    [
        "keyword=员工",
        "storage_key=documents/2026/demo.pdf",
        "event_window_key=abc:FIRST_REMINDER",
        "覆盖率=87.5",
        "已覆盖员工数=36",
        "basic auth login",
        "登录方式：basic 认证",
        "authorization pending",
        "event_window_key:abc:FIRST_REMINDER",
    ],
    ids=[
        "keyword",
        "storage_key",
        "event_window_key",
        "chinese-eq",
        "chinese-count",
        "basic-prose",
        "basic-prose-cn",
        "authorization-word",
        "event_window_key-colon",
    ],
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
