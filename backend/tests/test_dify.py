from app.services.dify import normalize_dify_outputs


def test_normalize_dify_outputs_strips_think_and_markdown_json() -> None:
    """Flat fields in output_json are wrapped into certificates[0]."""
    output = normalize_dify_outputs(
        {
            "result": """
<think>model reasoning should not be persisted</think>
```json
{
  "holder_name": " 张三 ",
  "certificate_name": "安全生产资格证",
  "certificate_no": "CERT-001",
  "suspicious_points": ["证书边角模糊", 123],
  "unexpected": "drop me"
}
```
""",
        }
    )

    assert output["certificates"] == [
        {
            "holder_name": "张三",
            "certificate_name": "安全生产资格证",
            "certificate_no": "CERT-001",
        }
    ]
    assert output["suspicious_points"] == ["证书边角模糊", "123"]


def test_normalize_dify_outputs_unwraps_nested_json_string() -> None:
    output = normalize_dify_outputs(
        {
            "data": {
                "outputs": '{"holder_name":"李四","certificate_name":"安全员证","confidence":"0.88","suspicious_points":"[\\"需核对钢印\\"]"}'
            }
        }
    )

    assert output["certificates"][0]["holder_name"] == "李四"
    assert output["confidence"] == 0.88
    assert output["suspicious_points"] == ["需核对钢印"]


def test_normalize_dify_outputs_bounds_dates_confidence_and_suspicious_points() -> None:
    output = normalize_dify_outputs(
        {
            "outputs": {
                "holder_name": "王五",
                "certificate_name": "安全员证",
                "issue_date": "2026年5月9日",
                "valid_from": "2026/05/10",
                "valid_to": "2028-05-09T12:30:00+08:00",
                "review_date": "not-a-date",
                "confidence": "88%",
                "suspicious_points": [
                    {"reason": "钢印不清晰"},
                    {"message": "钢印不清晰"},
                    {"description": "证书编号边缘模糊"},
                    {"unexpected": "drop me"},
                ],
            },
            "confidence": "0.66",
        }
    )

    cert = output["certificates"][0]
    assert cert["holder_name"] == "王五"
    assert cert["issue_date"] == "2026-05-09"
    assert cert["valid_from"] == "2026-05-10"
    assert cert["valid_to"] == "2028-05-09"
    assert "review_date" not in cert
    assert output["confidence"] == 0.66
    assert output["suspicious_points"] == ["钢印不清晰", "证书编号边缘模糊"]


def test_normalize_dify_outputs_removes_unclosed_think_and_drops_unexpected_scalars() -> None:
    """No valid certificate → gate raises ValueError."""
    import pytest
    with pytest.raises(ValueError, match="no valid certificates extracted"):
        normalize_dify_outputs(
            {
                "result": {
                    "holder_name": "<think>do not persist reasoning",
                    "certificate_no": False,
                    "issuing_authority": ["not", "a", "short", "field"],
                    "raw_text": {"ocr": "允许作为原文摘要保留"},
                    "extra_url": "https://example.test/drop",
                }
            }
        )


def test_normalize_dify_outputs_accepts_percentage_confidence_without_top_level_override() -> None:
    output = normalize_dify_outputs(
        {
            "outputs": {
                "holder_name": "赵六",
                "certificate_name": "安全员证",
                "confidence": "88%",
            }
        }
    )

    assert output["certificates"][0]["holder_name"] == "赵六"
    assert output["confidence"] == 0.88


def test_normalize_dify_outputs_bounds_oversized_fields_and_suspicious_point_pollution() -> None:
    long_text = "证" * 800
    output = normalize_dify_outputs(
        {
            "answer": {
                "holder_name": long_text,
                "certificate_name": "安全生产资格证",
                "raw_text": "原文" * 12000,
                "suspicious_points": [
                    "<think>hidden chain of thought</think>证书编号区域模糊",
                    {"reason": "钢印不清晰" * 200},
                    {"message": "钢印不清晰" * 200},
                    {"url": "https://example.test/drop-me"},
                ],
                "malicious_url": "https://example.test/drop-me",
                "replace_status": "ACTIVE",
            }
        }
    )

    assert set(output) == {"certificates", "raw_text", "suspicious_points"}
    assert output["certificates"][0]["holder_name"] == long_text[:512]
    assert len(output["raw_text"]) == 20000
    assert output["suspicious_points"] == [
        "证书编号区域模糊",
        ("钢印不清晰" * 200)[:512],
    ]


# ---- 新测试: 多证书 / 门禁 / 向后兼容 --------------------------------


def test_normalize_dify_outputs_explicit_certificates_array() -> None:
    """新 Dify workflow: 返回 certificates[] 数组被直接使用."""
    output = normalize_dify_outputs(
        {
            "certificates": [
                {"holder_name": "孙启凡", "certificate_name": "信息系统项目管理师", "certificate_no": "17201330212"},
                {"holder_name": "孙启凡", "certificate_name": "PMP", "certificate_no": "PMP-2024-001"},
            ],
            "raw_text": "OCR 全文内容",
            "confidence": 0.95,
        }
    )
    assert len(output["certificates"]) == 2
    assert output["certificates"][0]["certificate_name"] == "信息系统项目管理师"
    assert output["certificates"][1]["certificate_no"] == "PMP-2024-001"
    assert output["raw_text"] == "OCR 全文内容"


def test_normalize_dify_outputs_gate_empty_certificates() -> None:
    """空 certificates[] → gate 拒绝."""
    import pytest
    with pytest.raises(ValueError, match="no valid certificates extracted"):
        normalize_dify_outputs({"certificates": []})


def test_normalize_dify_outputs_gate_all_items_missing_required() -> None:
    """所有证书项缺 holder_name/certificate_name → gate 拒绝."""
    import pytest
    with pytest.raises(ValueError, match="no valid certificates extracted"):
        normalize_dify_outputs(
            {
                "certificates": [
                    {"certificate_no": "CERT-001"},
                    {"certificate_name": ""},
                ]
            }
        )


def test_normalize_dify_outputs_filters_invalid_items_partial() -> None:
    """部分证书项无效被过滤,剩余有效项仍可使用."""
    output = normalize_dify_outputs(
        {
            "certificates": [
                {"holder_name": "张三", "certificate_name": "安全员证"},
                {"certificate_no": "CERT-001"},  # 无 holder_name → 被过滤
                {"holder_name": "李四", "certificate_name": "电工证"},
            ]
        }
    )
    assert len(output["certificates"]) == 2


def test_normalize_dify_outputs_flat_backward_compatibility() -> None:
    """旧 Dify workflow: 顶层 flat 字段自动包装成单元素数组."""
    output = normalize_dify_outputs(
        {
            "holder_name": "张三",
            "certificate_name": "安全生产资格证",
            "certificate_no": "CERT-001",
        }
    )
    assert len(output["certificates"]) == 1
    assert output["certificates"][0]["holder_name"] == "张三"
    assert output["certificates"][0]["certificate_name"] == "安全生产资格证"