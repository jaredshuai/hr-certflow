from __future__ import annotations

import asyncio
import smtplib
from dataclasses import dataclass
from email.message import EmailMessage

import httpx

from app.core.config import Settings


@dataclass(frozen=True)
class NotificationMessage:
    title: str
    content: str
    recipients: list[str]
    resource_id: str | None = None


class NotificationRouter:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def send_to_hr(self, message: NotificationMessage, channels: list[str]) -> list[dict]:
        results: list[dict] = []
        for channel in channels:
            try:
                if channel == "wecom" and self.settings.wecom_webhook_url:
                    results.append(await self._send_webhook(channel, str(self.settings.wecom_webhook_url), message))
                elif channel == "feishu" and self.settings.feishu_webhook_url:
                    results.append(await self._send_webhook(channel, str(self.settings.feishu_webhook_url), message))
                elif channel == "dingtalk" and self.settings.dingtalk_webhook_url:
                    results.append(await self._send_webhook(channel, str(self.settings.dingtalk_webhook_url), message))
                elif channel == "email":
                    if self.settings.smtp_host and self.settings.mail_from and message.recipients:
                        results.append(await self._send_email(message))
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
                results.append({"channel": channel, "status": "failed", "error": str(exc)})
        return results

    async def _send_webhook(self, channel: str, webhook_url: str, message: NotificationMessage) -> dict:
        payload = {
            "msgtype": "text",
            "text": {"content": f"{message.title}\n{message.content}"},
        }
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.post(webhook_url, json=payload)
            response.raise_for_status()
            return {"channel": channel, "status": "sent", "response": response.text[:500]}

    async def _send_email(self, message: NotificationMessage) -> dict:
        email = EmailMessage()
        email["Subject"] = message.title
        email["From"] = self.settings.mail_from or ""
        email["To"] = ", ".join(message.recipients)
        email.set_content(message.content)

        await asyncio.to_thread(self._send_email_sync, email)
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
