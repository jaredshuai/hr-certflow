from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from app.core.config import Settings
from app.services.extraction import normalize_extraction_output


@dataclass(frozen=True)
class DifyExtractionRequest:
    file_url: str
    document_id: str
    user: str


@dataclass(frozen=True)
class DifyExtractionResponse:
    workflow_run_id: str | None
    model_name: str | None
    output: dict[str, Any]
    raw_response: dict[str, Any]


class DifyClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def run_certificate_extraction(
        self,
        request: DifyExtractionRequest,
    ) -> DifyExtractionResponse:
        if not self.settings.dify_base_url or not self.settings.dify_api_key:
            raise RuntimeError("DIFY_BASE_URL and DIFY_API_KEY are required")

        payload = {
            "workflow_id": self.settings.dify_workflow_id,
            "inputs": {
                "file_url": request.file_url,
                "document_id": request.document_id,
            },
            "response_mode": "blocking",
            "user": request.user,
        }
        headers = {"Authorization": f"Bearer {self.settings.dify_api_key}"}

        async with httpx.AsyncClient(base_url=str(self.settings.dify_base_url), timeout=120) as client:
            response = await client.post("/v1/workflows/run", json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()

        outputs = data.get("data", {}).get("outputs") or data.get("outputs") or {}
        if not isinstance(outputs, dict):
            outputs = {}
        normalized_outputs = normalize_extraction_output(outputs)
        model_name = normalized_outputs.get("model_name")
        return DifyExtractionResponse(
            workflow_run_id=data.get("workflow_run_id") or data.get("data", {}).get("workflow_run_id"),
            model_name=model_name if isinstance(model_name, str) else None,
            output=normalized_outputs,
            raw_response=data,
        )
