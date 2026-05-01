from __future__ import annotations

from dataclasses import dataclass

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
            if channel == "wecom" and self.settings.wecom_webhook_url:
                results.append(await self._send_webhook(str(self.settings.wecom_webhook_url), message))
            elif channel == "feishu" and self.settings.feishu_webhook_url:
                results.append(await self._send_webhook(str(self.settings.feishu_webhook_url), message))
            elif channel == "dingtalk" and self.settings.dingtalk_webhook_url:
                results.append(await self._send_webhook(str(self.settings.dingtalk_webhook_url), message))
            elif channel == "email":
                results.append({"channel": "email", "status": "not_configured"})
            else:
                results.append({"channel": channel, "status": "skipped"})
        return results

    async def _send_webhook(self, webhook_url: str, message: NotificationMessage) -> dict:
        payload = {
            "msgtype": "text",
            "text": {"content": f"{message.title}\n{message.content}"},
        }
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.post(webhook_url, json=payload)
            response.raise_for_status()
            return {"channel": "webhook", "status": "sent", "response": response.text[:500]}
