from __future__ import annotations

import socket
from typing import Any

from celery import current_task

from app.celery_app import celery_app
from app.core.config import get_settings


@celery_app.task(name="app.tasks.probe", bind=True)
def probe(self, expected_env: str, marker: str) -> dict[str, Any]:
    settings = get_settings()
    actual_env = settings.app_env
    if actual_env != expected_env:
        raise RuntimeError(f"probe expected APP_ENV={expected_env}, got {actual_env}")

    request = self.request
    return {
        "marker": marker,
        "expected_env": expected_env,
        "actual_env": actual_env,
        "worker_hostname": getattr(request, "hostname", None) or socket.gethostname(),
        "delivery_info": dict(request.delivery_info or {}),
        "task_id": current_task.request.id,
    }
