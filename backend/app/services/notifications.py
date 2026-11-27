from __future__ import annotations

import logging
import re
import smtplib
from dataclasses import dataclass
from email.message import EmailMessage
from urllib.parse import urlsplit

import httpx

from app.core.config import Settings

logger = logging.getLogger(__name__)

# 飞书自定义机器人的令牌在 path 末段（.../bot/v2/hook/<token>），其余两家在 query。
# 末段像凭据（长且只含令牌字符）时同样掩码，避免「只剥 query」漏掉 path 凭据。
_CREDENTIAL_SEGMENT_PATTERN = re.compile(r"^[0-9a-zA-Z_-]{16,}$")


def _delivery_error_code(exc: Exception) -> str:
    """异常映射为固定原因码。

    ``str(exc)``（尤其 ``httpx.HTTPStatusError``）携带完整 Webhook URL，查询串里就是
    企微/钉钉的 key、飞书的 access_token——绝不落库、进审计或回显前端。
    """
    if isinstance(exc, httpx.HTTPStatusError) and exc.response is not None:
        return f"WEBHOOK_HTTP_{exc.response.status_code}"
    if isinstance(exc, httpx.HTTPError):
        return "WEBHOOK_NETWORK_ERROR"
    if isinstance(exc, smtplib.SMTPException):
        return "EMAIL_SMTP_ERROR"
    return "DELIVERY_ERROR"


def _sanitize_webhook_url(webhook_url: str) -> str:
    """Webhook URL 只保留 scheme+host+path（剥离 query）；path 末段像凭据时掩码。"""
    parts = urlsplit(webhook_url)
    if not parts.scheme or not parts.netloc:
        return "invalid-webhook-url"
    segments = [segment for segment in parts.path.split("/") if segment]
    if segments and _CREDENTIAL_SEGMENT_PATTERN.match(segments[-1]):
        segments[-1] = "***"
    path = "/" + "/".join(segments) if segments else "/"
    return f"{parts.scheme}://{parts.netloc}{path}"


@dataclass(frozen=True)
class NotificationMessage:
    title: str
    content: str
    recipients: list[str]
    resource_id: str | None = None


class NotificationRouter:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def send_to_hr(self, message: NotificationMessage, channels: list[str]) -> list[dict]:
        results: list[dict] = []
        for channel in channels:
            try:
                if channel == "wecom" and self.settings.wecom_webhook_url:
                    results.append(self._send_webhook(channel, str(self.settings.wecom_webhook_url), message))
                elif channel == "feishu" and self.settings.feishu_webhook_url:
                    results.append(self._send_webhook(channel, str(self.settings.feishu_webhook_url), message))
                elif channel == "dingtalk" and self.settings.dingtalk_webhook_url:
                    results.append(self._send_webhook(channel, str(self.settings.dingtalk_webhook_url), message))
                elif channel == "email":
                    if self.settings.smtp_host and self.settings.mail_from and message.recipients:
                        results.append(self._send_email(message))
                    else:
                        results.append(
                            {
                                "channel": "email",
                                "status": "skipped",
                                "reason": "smtp_missing_or_no_recipients",
                            }
                        )
                else:
                    results.append({"channel": channel, "status": "skipped"})
            except Exception as exc:
                code = _delivery_error_code(exc)
                # 只记原因码，不打 str(exc)/堆栈：异常文本含 Webhook 凭据。
                logger.warning("Notification delivery failed: channel=%s code=%s", channel, code)
                results.append({"channel": channel, "status": "failed", "error": code})
        return results

    def _send_webhook(self, channel: str, webhook_url: str, message: NotificationMessage) -> dict:
        payload = self._webhook_payload(channel, message)
        target = _sanitize_webhook_url(webhook_url)
        try:
            with httpx.Client(timeout=15) as client:
                response = client.post(webhook_url, json=payload)
                response.raise_for_status()
        except Exception as exc:
            code = _delivery_error_code(exc)
            logger.warning("Webhook delivery failed: channel=%s target=%s code=%s", channel, target, code)
            return {"channel": channel, "status": "failed", "error": code, "target": target}
        return {"channel": channel, "status": "sent", "response": response.text[:500], "target": target}

    def _webhook_payload(self, channel: str, message: NotificationMessage) -> dict:
        text = f"{message.title}\n{message.content}"
        if channel in {"wecom", "dingtalk"}:
            return {
                "msgtype": "text",
                "text": {"content": text},
            }
        if channel == "feishu":
            return {
                "msg_type": "text",
                "content": {"text": text},
            }
        raise ValueError(f"Unsupported webhook channel: {channel}")

    def _send_email(self, message: NotificationMessage) -> dict:
        email = EmailMessage()
        email["Subject"] = message.title
        email["From"] = self.settings.mail_from or ""
        email["To"] = ", ".join(message.recipients)
        email.set_content(message.content)

        self._send_email_sync(email)
        return {"channel": "email", "status": "sent", "recipients": message.recipients}

    def _send_email_sync(self, email: EmailMessage) -> None:
        if not self.settings.smtp_host:
            raise RuntimeError("SMTP host is not configured")

        with smtplib.SMTP(self.settings.smtp_host, self.settings.smtp_port, timeout=15) as client:
            if self.settings.smtp_starttls:
                client.starttls()
            if self.settings.smtp_username:
                client.login(self.settings.smtp_username, self.settings.smtp_password or "")
            client.send_message(email)
