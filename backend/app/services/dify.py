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

_CERTIFICATE_FLAT_KEYS = frozenset({
    "holder_name", "certificate_name", "certificate_no", "issuing_authority",
    "issue_date", "valid_from", "valid_to", "review_date",
})


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


# ---- 新: 单条证书项模型 ------------------------------------------------

class DifyCertificateItem(BaseModel):
    """单条证书提取结果,包含在 certificates[] 数组中"""
    model_config = ConfigDict(extra="ignore")

    holder_name: str | None = None
    certificate_name: str | None = None
    certificate_no: str | None = None
    issuing_authority: str | None = None
    issue_date: str | None = None
    valid_from: str | None = None
    valid_to: str | None = None
    review_date: str | None = None

    @field_validator(
        "holder_name",
        "certificate_name",
        "certificate_no",
        "issuing_authority",
        mode="before",
    )
    @classmethod
    def clean_short_text(cls, value: Any) -> str | None:
        return _short_text_or_none(value)

    @field_validator("issue_date", "valid_from", "valid_to", "review_date", mode="before")
    @classmethod
    def clean_date_text(cls, value: Any) -> str | None:
        return _date_text_or_none(value)


# ---- 顶层模型: certificates[] + 文档级 metadata -------------------------

def _clean_suspicious_points(value: Any) -> list[str]:
    """Module-level suspicious points cleaner (also referenced by Pydantic validator)."""
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


def _clean_confidence(value: Any) -> float | None:
    """Module-level confidence cleaner (also referenced by Pydantic validator)."""
    if value is None or value == "":
        return None
    is_percentage = False
    if isinstance(value, str):
        text = value.strip()
        is_percentage = text.endswith("%")
        value = text[:-1].strip() if is_percentage else text
    try:
        confidence = float(value)
    except (TypeError, ValueError):
        return None
    if is_percentage:
        confidence = confidence / 100
    elif confidence > 1 and confidence <= 100:
        confidence = confidence / 100
    if confidence < 0 or confidence > 1:
        return None
    return confidence


class DifyCertificateOutput(BaseModel):
    """Dify 提取结果整体模型. certificates[] 是核心,文档级字段为辅助 metadata."""
    model_config = ConfigDict(extra="ignore")

    certificates: list[DifyCertificateItem] = Field(default_factory=list)
    raw_text: str | None = None
    suspicious_points: list[str] = Field(default_factory=list)
    model_name: str | None = None
    confidence: float | None = None

    @field_validator("raw_text", mode="before")
    @classmethod
    def clean_raw_text(cls, value: Any) -> str | None:
        return _text_or_none(value, max_length=20000)

    @field_validator("suspicious_points", mode="before")
    @classmethod
    def clean_suspicious_points(cls, value: Any) -> list[str]:
        return _clean_suspicious_points(value)

    @field_validator("confidence", mode="before")
    @classmethod
    def clean_confidence(cls, value: Any) -> float | None:
        return _clean_confidence(value)


# ---- 转换 / 归一化 -----------------------------------------------------

def _extract_mapping(value: Any) -> dict[str, Any]:
    """递归展开 Dify wrapper keys (outputs/data/result/...),保留所有字段.

    外层字段优先于内层同名字段. 不再过滤字段——多余的 key 会在
    DifyCertificateOutput (extra='ignore') 验证时被丢弃,而 certificates[]
    数组里的 flat 项 (holder_name 等) 需要被保留到 _resolve_certificate_items.
    """
    parsed = _parse_json_like(value)
    if not isinstance(parsed, dict):
        return {}

    current_fields = dict(parsed)

    for key in _JSON_WRAPPER_KEYS:
        if key not in parsed:
            continue
        nested = _extract_mapping(parsed[key])
        if nested:
            # 外层字段优先于内层
            return {**nested, **current_fields}
    return current_fields


def _resolve_certificate_items(output_map: dict[str, Any], raw_text: Any) -> list[Any]:
    """从 output_map 中按优先级解析证书列表."""
    # Source A: 显式 certificates[] 数组 (新 Dify workflow)
    certs_raw = output_map.get("certificates")
    if isinstance(certs_raw, list) and certs_raw:
        return list(certs_raw)

    # Source B: raw_text 包含结构化 JSON (当前 Dify workflow)
    if isinstance(raw_text, str):
        parsed = _parse_json_like(raw_text)
        if isinstance(parsed, dict):
            if parsed.get("certificates") and isinstance(parsed["certificates"], list):
                return list(parsed["certificates"])
            if parsed.get("holder_name"):
                return [parsed]
        elif isinstance(parsed, list):
            # raw_text 可能直接是一个数组
            return [item for item in parsed if isinstance(item, dict)]

    # Source C: 顶层 flat 字段 (向后兼容)
    flat = {k: output_map[k] for k in _CERTIFICATE_FLAT_KEYS if k in output_map}
    if flat:
        return [flat]

    return []


def normalize_dify_outputs(outputs: Any) -> dict[str, Any]:
    """归一化 Dify 返回的 outputs 到标准 schema.

    门禁规则:
    - certificates[] 必须非空且至少一条含 holder_name + certificate_name
    - 否则抛 ValueError (上层转为 FAILED + failure_reason)
    """
    output_map = _extract_mapping(outputs)
    raw_text_raw: Any = output_map.get("raw_text")

    # 1. 解析证书列表
    raw_certs = _resolve_certificate_items(output_map, raw_text_raw)

    # 2. 清理 raw_text: 如果是 JSON,提取内含的 OCR 文本
    clean_raw_text: str | None = None
    if isinstance(raw_text_raw, str):
        parsed_raw = _parse_json_like(raw_text_raw)
        if isinstance(parsed_raw, dict):
            inner = parsed_raw.get("raw_text")
            if isinstance(inner, str):
                clean_raw_text = inner
            elif parsed_raw.get("holder_name"):
                # 这是结构化提取结果 JSON,非 OCR 文本——不保留
                pass
            else:
                clean_raw_text = raw_text_raw
        else:
            clean_raw_text = raw_text_raw
    elif isinstance(raw_text_raw, str | int | float):
        clean_raw_text = str(raw_text_raw)

    # 3. 验证每条证书 (门禁)
    valid_certificates: list[dict[str, Any]] = []
    for item in raw_certs:
        if not isinstance(item, dict):
            continue
        validated = DifyCertificateItem.model_validate(item)
        item_dict = validated.model_dump(exclude_none=True)
        if item_dict.get("holder_name") and item_dict.get("certificate_name"):
            valid_certificates.append(item_dict)

    if not valid_certificates:
        raise ValueError("no valid certificates extracted: all items missing holder_name or certificate_name")

    # 4. 构建结果
    result: dict[str, Any] = {"certificates": valid_certificates}

    if clean_raw_text:
        cleaned = _text_or_none(clean_raw_text, max_length=20000)
        if cleaned:
            result["raw_text"] = cleaned

    for key, cleaner in (
        ("suspicious_points", _clean_suspicious_points),
        ("model_name", lambda v: _short_text_or_none(v)),
        ("confidence", _clean_confidence),
    ):
        val = output_map.get(key)
        if val is not None:
            cleaned = cleaner(val)
            if cleaned is not None and cleaned != []:
                result[key] = cleaned

    return result


# ---- Dify HTTP 客户端 --------------------------------------------------

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

    def run_certificate_extraction(
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

        with httpx.Client(base_url=str(self.settings.dify_base_url), timeout=120) as client:
            response = client.post("/v1/workflows/run", json=payload, headers=headers)
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