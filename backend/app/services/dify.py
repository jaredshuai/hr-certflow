from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.config import Settings

_THINK_BLOCK_RE = re.compile(r"<think\b[^>]*>.*?</think>", re.IGNORECASE | re.DOTALL)
_UNCLOSED_THINK_RE = re.compile(r"<think\b[^>]*>.*$", re.IGNORECASE | re.DOTALL)
_THINK_CLOSE_RE = re.compile(r"</think>", re.IGNORECASE)
_MARKDOWN_JSON_RE = re.compile(r"^\s*```(?:json)?\s*(.*?)\s*```\s*$", re.IGNORECASE | re.DOTALL)
_DATE_RE = re.compile(r"^\s*(\d{4})(?:年|[./-])(\d{1,2})(?:月|[./-])(\d{1,2})(?:日)?\s*$")

_JSON_WRAPPER_KEYS = (
    "outputs",
    "output",
    "result",
    "text",
    "answer",
    "data",
    "json",
)


def _strip_model_artifacts(value: str) -> str:
    cleaned = _THINK_BLOCK_RE.sub("", value).strip()
    cleaned = _UNCLOSED_THINK_RE.sub("", cleaned).strip()
    cleaned = _THINK_CLOSE_RE.sub("", cleaned).strip()
    match = _MARKDOWN_JSON_RE.match(cleaned)
    if match:
        cleaned = match.group(1).strip()
    return cleaned


def _parse_json_like(value: Any) -> Any:
    current = value
    for _ in range(3):
        if not isinstance(current, str):
            return current
        cleaned = _strip_model_artifacts(current)
        try:
            parsed = json.loads(cleaned)
        except json.JSONDecodeError:
            return cleaned
        current = parsed
    return current


def _text_or_none(value: Any, *, max_length: int = 512) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        text = _strip_model_artifacts(value).strip()
    elif isinstance(value, int | float | bool):
        text = str(value)
    else:
        text = json.dumps(value, ensure_ascii=False, default=str)
    if not text:
        return None
    return text[:max_length]


def _short_text_or_none(value: Any, *, max_length: int = 512) -> str | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, str):
        text = _strip_model_artifacts(value).strip()
    elif isinstance(value, int | float):
        text = str(value)
    else:
        return None
    if not text:
        return None
    return text[:max_length]


def _date_text_or_none(value: Any) -> str | None:
    text = _short_text_or_none(value, max_length=64)
    if not text:
        return None

    match = _DATE_RE.match(text)
    if match:
        year, month, day = (int(part) for part in match.groups())
        try:
            return date(year, month, day).isoformat()
        except ValueError:
            return None

    try:
        return date.fromisoformat(text[:10]).isoformat()
    except ValueError:
        pass

    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        return None


def _suspicious_point_text(value: Any) -> str | None:
    if isinstance(value, dict):
        for key in ("reason", "message", "text", "description"):
            text = _text_or_none(value.get(key))
            if text:
                return text
        return None
    return _text_or_none(value)


class DifyCertificateOutput(BaseModel):
    model_config = ConfigDict(extra="ignore")

    holder_name: str | None = None
    certificate_name: str | None = None
    certificate_no: str | None = None
    issuing_authority: str | None = None
    issue_date: str | None = None
    valid_from: str | None = None
    valid_to: str | None = None
    review_date: str | None = None
    raw_text: str | None = Field(default=None, max_length=20000)
    suspicious_points: list[str] = Field(default_factory=list)
    model_name: str | None = None
    confidence: float | None = None

    @field_validator(
        "holder_name",
        "certificate_name",
        "certificate_no",
        "issuing_authority",
        "issue_date",
        "valid_from",
        "valid_to",
        "review_date",
        "model_name",
        mode="before",
    )
    @classmethod
    def clean_short_text(cls, value: Any) -> str | None:
        return _short_text_or_none(value)

    @field_validator("issue_date", "valid_from", "valid_to", "review_date", mode="before")
    @classmethod
    def clean_date_text(cls, value: Any) -> str | None:
        return _date_text_or_none(value)

    @field_validator("raw_text", mode="before")
    @classmethod
    def clean_raw_text(cls, value: Any) -> str | None:
        return _text_or_none(value, max_length=20000)

    @field_validator("suspicious_points", mode="before")
    @classmethod
    def clean_suspicious_points(cls, value: Any) -> list[str]:
        if value is None:
            return []
        parsed = _parse_json_like(value)
        if isinstance(parsed, str):
            parsed = [parsed]
        if not isinstance(parsed, list):
            return []
        points: list[str] = []
        seen: set[str] = set()
        for item in parsed:
            text = _suspicious_point_text(item)
            if text and text not in seen:
                seen.add(text)
                points.append(text)
            if len(points) >= 20:
                break
        return points

    @field_validator("confidence", mode="before")
    @classmethod
    def clean_confidence(cls, value: Any) -> float | None:
        if value is None or value == "":
            return None
        try:
            confidence = float(value)
        except (TypeError, ValueError):
            return None
        if isinstance(value, str) and value.strip().endswith("%"):
            confidence = confidence / 100
        elif confidence > 1 and confidence <= 100:
            confidence = confidence / 100
        if confidence < 0 or confidence > 1:
            return None
        return confidence


def _extract_mapping(value: Any) -> dict[str, Any]:
    parsed = _parse_json_like(value)
    if not isinstance(parsed, dict):
        return {}

    allowed_fields = set(DifyCertificateOutput.model_fields)
    current_fields = {key: parsed[key] for key in allowed_fields.intersection(parsed.keys())}

    for key in _JSON_WRAPPER_KEYS:
        if key not in parsed:
            continue
        nested = _extract_mapping(parsed[key])
        if nested:
            return {**nested, **current_fields}
    return current_fields


def normalize_dify_outputs(outputs: Any) -> dict[str, Any]:
    output_map = _extract_mapping(outputs)
    normalized = DifyCertificateOutput.model_validate(output_map)
    return normalized.model_dump(exclude_none=True)


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
        normalized_output = normalize_dify_outputs(outputs)
        return DifyExtractionResponse(
            workflow_run_id=data.get("workflow_run_id") or data.get("data", {}).get("workflow_run_id"),
            model_name=normalized_output.get("model_name"),
            output=normalized_output,
            raw_response=data,
        )
