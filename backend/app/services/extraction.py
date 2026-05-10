from __future__ import annotations

import json
from typing import Any

CANONICAL_OUTPUT_FIELDS = (
    "holder_name",
    "certificate_name",
    "certificate_no",
    "issuing_authority",
    "issue_date",
    "valid_from",
    "valid_to",
    "review_date",
    "raw_text",
    "suspicious_points",
    "model_name",
)


def _field_score(value: object) -> int:
    if not isinstance(value, dict):
        return 0
    return sum(1 for field in CANONICAL_OUTPUT_FIELDS if field in value)


def extract_json_object_from_text(text: str) -> dict[str, Any] | None:
    """Recover the last schema-shaped JSON object from a noisy model response."""
    decoder = json.JSONDecoder()
    best: dict[str, Any] | None = None

    for index, char in enumerate(text):
        if char != "{":
            continue

        try:
            parsed, _ = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            continue

        if isinstance(parsed, dict) and _field_score(parsed) >= 2:
            best = parsed

    return best


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]


def normalize_extraction_output(output: dict[str, Any]) -> dict[str, Any]:
    """Normalize Dify/model outputs before storing structured extraction fields."""
    normalized = dict(output)
    raw_text = output.get("raw_text")
    if not isinstance(raw_text, str):
        return normalized

    embedded = extract_json_object_from_text(raw_text)
    if not embedded:
        return normalized

    for field in CANONICAL_OUTPUT_FIELDS:
        if field in embedded:
            normalized[field] = embedded[field]

    suspicious_points = [
        *_string_list(output.get("suspicious_points")),
        *_string_list(embedded.get("suspicious_points")),
    ]
    if "<think" in raw_text or "</think>" in raw_text:
        suspicious_points.append("模型返回包含非结构化文本，系统已从末尾 JSON 恢复字段，请人工核对。")

    if suspicious_points:
        normalized["suspicious_points"] = list(dict.fromkeys(suspicious_points))

    return normalized
