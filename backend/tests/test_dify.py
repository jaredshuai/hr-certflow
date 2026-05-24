from app.services.dify import normalize_dify_outputs


def test_normalize_dify_outputs_strips_think_and_markdown_json() -> None:
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

    assert output == {
        "holder_name": "张三",
        "certificate_name": "安全生产资格证",
        "certificate_no": "CERT-001",
        "suspicious_points": ["证书边角模糊", "123"],
    }


def test_normalize_dify_outputs_unwraps_nested_json_string() -> None:
    output = normalize_dify_outputs(
        {
            "data": {
                "outputs": '{"holder_name":"李四","confidence":"0.88","suspicious_points":"[\\"需核对钢印\\"]"}'
            }
        }
    )

    assert output["holder_name"] == "李四"
    assert output["confidence"] == 0.88
    assert output["suspicious_points"] == ["需核对钢印"]


def test_normalize_dify_outputs_bounds_dates_confidence_and_suspicious_points() -> None:
    output = normalize_dify_outputs(
        {
            "outputs": {
                "holder_name": "王五",
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

    assert output["holder_name"] == "王五"
    assert output["issue_date"] == "2026-05-09"
    assert output["valid_from"] == "2026-05-10"
    assert output["valid_to"] == "2028-05-09"
    assert "review_date" not in output
    assert output["confidence"] == 0.66
    assert output["suspicious_points"] == ["钢印不清晰", "证书编号边缘模糊"]


def test_normalize_dify_outputs_removes_unclosed_think_and_drops_unexpected_scalars() -> None:
    output = normalize_dify_outputs(
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

    assert output == {
        "raw_text": '{"ocr": "允许作为原文摘要保留"}',
        "suspicious_points": [],
    }
